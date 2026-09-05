#!/usr/bin/env python3
"""Обучение модели этапа 0.0.5 — LoRA/QLoRA поверх открытой базы на наборе
(ChatML JSONL: data/train.jsonl, val.jsonl — набор приватный, сюда не кладётся).
Одна команда; на GPU — QLoRA 4 бита, база по профилю хоста (run_local.py);
на CPU — только дымовой прогон на малой базе (проверка дороги).

    python train_lora.py --base Qwen/Qwen2.5-7B-Instruct --out runs/aiasa-0.0.5 --epochs 2
    python train_lora.py --base Qwen/Qwen2.5-0.5B-Instruct --steps 3 --max-len 512 --out /tmp/smoke   # дым

Беседы режутся на окна ≤ max-len токенов по репликам (шаблон чата базы);
обучение — на ответах исполнителя (маска на реплики автора и system).
После обучения адаптер сливается в базу (--merge, по умолчанию) —
готово к convert_hf_to_gguf.py (export_gguf.py) и LM Studio.

Авторство: Hu et al. 2021 (LoRA), Dettmers et al. 2023 (QLoRA), Qwen
Team 2024 (база, Apache-2.0), HF transformers/peft (Wolf 2020, Mangrulkar
2022). NOT_MEASURED: качество после обучения здесь не замерено (нет GPU;
дымовой прогон проверяет дорогу, не модель).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent


def windows(examples, tok, max_len: int):
    """Беседа → окна токенов по репликам; метки −100 вне ответов исполнителя.
    Длины считаются по одной токенизации на реплику (шаблон чата базы),
    без повторной токенизации всего окна на каждом шаге."""
    for ex in examples:
        msgs = ex["messages"]
        sysm = [m for m in msgs if m["role"] == "system"][:1]
        turns = [m for m in msgs if m["role"] != "system"]
        if not turns:
            continue
        # одна токенизация на реплику: сегмент реплики = шаблон(system + реплика) минус шаблон(system)
        head = tok.apply_chat_template(sysm, tokenize=True, add_generation_prompt=False, return_dict=False) if sysm else []
        seg = [head] + [tok.apply_chat_template(sysm + [t], tokenize=True, add_generation_prompt=False, return_dict=False)[len(head):] for t in turns]
        i = 0
        while i < len(turns):
            ids = list(head); labels = [-100] * len(head); j = i
            while j < len(turns) and len(ids) + len(seg[j + 1]) <= max_len:
                piece = seg[j + 1]
                ids += piece
                labels += piece if turns[j]["role"] == "assistant" else [-100] * len(piece)
                j += 1
            if j == i:
                piece = seg[i + 1][:max_len - len(head)]
                ids += piece
                labels += piece if turns[i]["role"] == "assistant" else [-100] * len(piece)
                j = i + 1
            i = j
            if any(l != -100 for l in labels):
                yield {"input_ids": ids, "labels": labels, "attention_mask": [1] * len(ids)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--data", default=str(HERE / "data"))
    ap.add_argument("--out", default=str(HERE / "runs" / "aiasa-0.0.5"))
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--steps", type=int, default=0, help="если > 0 — столько шагов и стоп (дым)")
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--max-examples", type=int, default=0)
    a = ap.parse_args(argv)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq, Trainer,
                              TrainerCallback, TrainingArguments)

    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    progress_path = out / "PROGRESS.json"
    t_start = time.perf_counter()

    def progress(**kw):
        """Ход — файлом, который читает run_local.py каждую минуту (письмо
        хоста 05.09: «молчаливое поведение не даёт информации о состоянии»)."""
        kw["когда"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        kw["прошло, с"] = round(time.perf_counter() - t_start)
        progress_path.write_text(json.dumps(kw, ensure_ascii=False, indent=1), encoding="utf-8")

    progress(этап="загрузка базы", база=a.base)
    print(f"[{time.strftime('%H:%M:%S')}] загрузка базы {a.base} (первый раз — скачивание, минуты)", flush=True)

    cuda = torch.cuda.is_available()
    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    kw = {}
    if cuda:
        try:
            from transformers import BitsAndBytesConfig
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
            kw["device_map"] = {"": 0}
        except ImportError:
            kw["torch_dtype"] = torch.bfloat16; kw["device_map"] = {"": 0}
    else:
        kw["torch_dtype"] = torch.float32
    model = AutoModelForCausalLM.from_pretrained(a.base, **kw)
    if "quantization_config" in kw:
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()

    def load(name):
        rows = [json.loads(l) for l in open(pathlib.Path(a.data) / f"{name}.jsonl", encoding="utf-8")]
        if a.max_examples:
            rows = rows[:a.max_examples]
        return Dataset.from_list(list(windows(rows, tok, a.max_len)))

    progress(этап="окна набора")
    train_ds, val_ds = load("train"), load("val")
    print(f"окон: train {len(train_ds)}, val {len(val_ds)}; max_len {a.max_len}; cuda {cuda}")
    import math
    full_total = math.ceil(len(train_ds) / (a.batch * a.accum)) * max(a.epochs, 1e-9)
    full_total = int(math.ceil(full_total))

    class Progress(TrainerCallback):
        """PROGRESS.json на каждом логе: шаг, всего, с/шаг, остаток, loss."""
        def __init__(self):
            self.t0 = None
        def on_train_begin(self, args, state, control, **kw):
            self.t0 = time.perf_counter()
            progress(этап="train", шаг=0, всего=state.max_steps, **{"полных шагов": full_total})
        def on_log(self, args, state, control, logs=None, **kw):
            done = max(state.global_step, 1)
            sps = round((time.perf_counter() - self.t0) / done, 2)
            left = round(sps * max(state.max_steps - state.global_step, 0))
            loss = (logs or {}).get("loss")
            progress(этап="train", шаг=state.global_step, всего=state.max_steps, **{"с/шаг": sps, "осталось, с": left,
                     "loss": loss, "полных шагов": full_total})
            print(f"[{time.strftime('%H:%M:%S')}] шаг {state.global_step}/{state.max_steps}, {sps} с/шаг, осталось ~{left // 60} мин, loss {loss}", flush=True)
    args = TrainingArguments(output_dir=a.out, per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.accum,
                             num_train_epochs=a.epochs, max_steps=a.steps if a.steps > 0 else -1, learning_rate=a.lr,
                             lr_scheduler_type="cosine", warmup_steps=10, logging_steps=5, save_strategy="epoch", disable_tqdm=False,
                             eval_strategy="epoch" if len(val_ds) else "no", bf16=cuda, fp16=False,
                             gradient_checkpointing=cuda, report_to=[], remove_unused_columns=False)
    trainer = Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds if len(val_ds) else None,
                      data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100),
                      callbacks=[Progress()])
    t0 = time.perf_counter()
    trainer.train()
    dt = time.perf_counter() - t0
    steps_done = max(trainer.state.global_step, 1)
    progress(этап="сохранение адаптера", шаг=trainer.state.global_step, всего=trainer.state.max_steps,
             **{"с/шаг": round(dt / steps_done, 2), "полных шагов": full_total})
    model.save_pretrained(out / "adapter"); tok.save_pretrained(out / "adapter")
    import hashlib
    tr_path = pathlib.Path(a.data) / "train.jsonl"
    report = {"база": a.base, "окон train": len(train_ds), "окон val": len(val_ds), "шагов": trainer.state.global_step,
              "полных шагов при epochs": full_total, "с/шаг": round(dt / steps_done, 2),
              "время, с": round(dt, 1), "cuda": cuda, "потеря последняя": next((h["loss"] for h in reversed(trainer.state.log_history) if "loss" in h), None),
              "набор sha256": hashlib.sha256(tr_path.read_bytes()).hexdigest()[:16] if tr_path.is_file() else None,
              "набор байт": tr_path.stat().st_size if tr_path.is_file() else None}
    if not a.no_merge:
        progress(этап="слияние адаптера с базой", шаг=trainer.state.global_step, всего=trainer.state.max_steps)
        merged = model.merge_and_unload() if not cuda or "quantization_config" not in kw else None
        if merged is None:
            # QLoRA: слияние — в bf16 поверх незаквантованной базы
            base = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": "cpu"})
            from peft import PeftModel
            merged = PeftModel.from_pretrained(base, out / "adapter").merge_and_unload()
        merged.save_pretrained(out / "merged"); tok.save_pretrained(out / "merged")
        report["слито"] = str(out / "merged")
    (out / "TRAIN_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    progress(этап="готово", шаг=trainer.state.global_step, всего=trainer.state.max_steps, **{"с/шаг": report["с/шаг"], "полных шагов": full_total})
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
