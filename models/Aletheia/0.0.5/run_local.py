#!/usr/bin/env python3
"""Aletheia 0.0.5 — одна команда на хосте: замер → набор → обучение →
досмотр → GGUF. Комплект живёт ЗДЕСЬ, в публичной зоне (папка модели);
приватное — набор из диалогов и его сборщик — живёт в репозитории-источнике
и сюда не кладётся: шаг data берёт набор по --data, либо находит сборщик в
соседнем клоне источника и запускает его там.

    python run_local.py                      # всё подряд, с возобновлением
    python run_local.py --only probe         # один шаг: probe|data|train|leak|gguf
    python run_local.py --data <папка с train.jsonl/val.jsonl>
    python run_local.py --base Qwen/Qwen2.5-3B-Instruct --max-len 512

Каждый шаг пишет отметку в runs/LOCAL_STATE.json; повтор команды
продолжает с места остановки (--redo — повторить сделанное).
Что прислать обратно (файлами): runs/LOCAL_STATE.json,
runs/aiasa-0.0.5/TRAIN_REPORT.json, runs/aiasa-0.0.5/merged/LEAK_TEST.json,
host_log.json. Веса (GGUF) — в Releases частями; в чат их не слать.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
RUNS = HERE / "runs"
STATE = RUNS / "LOCAL_STATE.json"
STEPS = ("probe", "data", "train", "leak", "gguf")
SOURCE_REPO = "InvesePolar"     # репозиторий-источник (приватный): там сборщик набора

#: Профиль хоста по VRAM: (порог GiB, база, max_len). 7B в 4 битах не входит в 4 GiB.
PROFILES = ((12, "Qwen/Qwen2.5-7B-Instruct", 2048), (6, "Qwen/Qwen2.5-3B-Instruct", 1024),
            (0, "Qwen/Qwen2.5-1.5B-Instruct", 1024))


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {"шаги": {}}


def save(st: dict) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def run(cmd: list, st: dict, step: str, cwd=None) -> int:
    t0 = time.time()
    print(f"\n== шаг {step}: {' '.join(map(str, cmd))}")
    rc = subprocess.call([str(c) for c in cmd], cwd=cwd)
    st["шаги"][step] = {"код": rc, "секунд": round(time.time() - t0), "когда": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save(st)
    return rc


def host_profile() -> dict:
    """host_log.json после probe: есть ли CUDA, VRAM, выбор базы."""
    log_path = HERE / "host_log.json"
    if not log_path.is_file():
        return {}
    log = json.loads(log_path.read_text(encoding="utf-8"))
    smi = str(log.get("nvidia-smi", ""))
    vram = None
    if "MiB" in smi:
        for tok in smi.replace(",", " ").split():
            if tok.isdigit():
                vram = int(tok); break
    cuda = bool(log.get("cuda", {}).get("available")) if isinstance(log.get("cuda"), dict) else False
    prof = {"gpu": smi, "vram_MiB": vram, "cuda": cuda, "torch": log.get("torch"), "python": log.get("python")}
    gib = (vram or 0) / 1024
    for thr, base, max_len in PROFILES:
        if gib >= thr:
            prof["base"], prof["max_len"] = base, max_len
            break
    return prof


def missing_modules() -> list:
    """Модули комплекта, которые не ввозятся. Ловится любая ошибка ввоза, не
    только ImportError: после `pip --force-reinstall torch` (04.09) pip
    перетянул fsspec 2026.7.0 при требовании datasets fsspec<=2026.6.0 — такой
    разлад проявляется не отсутствием модуля, а ошибкой внутри ввоза."""
    out = []
    for m in ("torch", "transformers", "peft", "datasets", "accelerate"):
        try:
            __import__(m)
        except Exception as e:  # noqa: BLE001 — любая причина, поимённо
            out.append(m)
            msg = f"{type(e).__name__}: {e}"
            print(f"!! {m}: ввоз не удался — {msg[:200]}")
            if "fsspec" in msg:
                print('   лечится: pip install "fsspec[http]<=2026.6.0"')
    return out


def find_builder() -> pathlib.Path | None:
    """Сборщик набора в соседнем клоне репозитория-источника (приватного)."""
    roots = [HERE / SOURCE_REPO, HERE.parents[3] / SOURCE_REPO if len(HERE.parents) > 3 else None,
             pathlib.Path.home() / SOURCE_REPO, pathlib.Path(os.environ.get("AIASA_SOURCE", "")) if os.environ.get("AIASA_SOURCE") else None]
    if os.name == "nt":
        roots.append(pathlib.Path("C:/") / SOURCE_REPO)
    for root in roots:
        if root is None:
            continue
        hits = sorted(root.glob("ENV/*/model/build_dataset.py"))
        if hits:
            return hits[0]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=STEPS)
    ap.add_argument("--data", default=None, help="папка с train.jsonl/val.jsonl (по умолчанию — data/ рядом либо сборщик источника)")
    ap.add_argument("--base", default=None, help="база; без флага — по профилю хоста (VRAM)")
    ap.add_argument("--max-len", type=int, default=None, help="без флага — по профилю хоста")
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--out", default=str(RUNS / "aiasa-0.0.5"))
    ap.add_argument("--cpu-ok", action="store_true", help="учить на CPU, даже если GPU есть, а CUDA в torch нет")
    ap.add_argument("--redo", action="store_true", help="повторить уже сделанные шаги")
    a = ap.parse_args(argv)
    st = load()
    py = sys.executable
    data_dir = pathlib.Path(a.data) if a.data else pathlib.Path(st.get("data") or (HERE / "data"))
    steps = [a.only] if a.only else list(STEPS)
    for step in steps:
        if not a.redo and st["шаги"].get(step, {}).get("код") == 0 and step != "probe":
            print(f"== шаг {step}: уже сделан ({st['шаги'][step]['когда']}) — пропуск (--redo, чтобы повторить)")
            continue
        rc = 0
        if step == "probe":
            rc = run([py, HERE / "probe_host.py"], st, step)
            miss = missing_modules()
            if miss:
                print(f"!! не хватает модулей: {miss} — pip install {' '.join(miss)} bitsandbytes")
                st["не хватает"] = miss; save(st)
                if not a.only:
                    return 2
            prof = host_profile()
            st["профиль"] = prof; save(st)
            if prof:
                print(f"профиль хоста: GPU «{prof.get('gpu')}», VRAM {prof.get('vram_MiB')} MiB, CUDA в torch: {prof.get('cuda')} → база {prof.get('base')}, max_len {prof.get('max_len')}")
            if prof and prof.get("vram_MiB") and not prof.get("cuda") and not a.cpu_ok:
                print("!! CUDA-драйвер и карта NVIDIA есть (nvidia-smi отвечает), а УСТАНОВЛЕННАЯ СБОРКА torch — CPU (+cpu):")
                print("   карта простаивает (0 % в диспетчере), обучение пошло бы на CPU. Поставить сборку cu128")
                print("   (колёса для Python 3.13/3.14, Windows/Linux, есть):")
                print("   pip install --force-reinstall --no-deps torch --index-url https://download.pytorch.org/whl/cu128")
                print("   (--no-deps: меняется только torch; без него pip перетягивает fsspec и печатает красные строки о конфликтах —")
                print("   datasets требует fsspec[http]<=2026.6.0; лечится: pip install \"fsspec[http]<=2026.6.0\"; конфликты чужих пакетов —")
                print("   open-interpreter/starlette, selenium/urllib3 — комплекта не касаются)")
                print("   Вторая карта другого производителя (экранная) для CUDA невидима — выбирать устройство не нужно,")
                print("   torch cu128 увидит одну карту NVIDIA как device 0. Учить на CPU всё равно — флаг --cpu-ok (1.5B: часы)")
                st["шаги"][step] = {"код": 4, "почему": "torch без CUDA при наличии GPU"}; save(st)
                if not a.only:
                    return 4
        elif step == "data":
            if (data_dir / "train.jsonl").is_file():
                print(f"== шаг data: набор есть — {data_dir}")
                st["шаги"][step] = {"код": 0, "когда": time.strftime("%Y-%m-%dT%H:%M:%S"), "откуда": str(data_dir)}
            else:
                builder = find_builder()
                if builder is None:
                    print(f"!! набора нет ({data_dir / 'train.jsonl'}) и сборщик источника не найден: положить клон {SOURCE_REPO} рядом "
                          f"(или задать AIASA_SOURCE=<путь к клону>), либо указать --data <папка с train.jsonl>")
                    st["шаги"][step] = {"код": 5, "почему": "нет набора и сборщика"}; save(st)
                    if not a.only:
                        return 5
                    continue
                rc = run([py, "-B", builder], st, step, cwd=builder.parent)
                data_dir = builder.parent / "data"
            st["data"] = str(data_dir); save(st)
        elif step == "train":
            prof = st.get("профиль") or host_profile()
            base = a.base or prof.get("base") or PROFILES[0][1]
            max_len = a.max_len or prof.get("max_len") or PROFILES[0][2]
            rc = run([py, "-B", HERE / "train_lora.py", "--base", base, "--data", data_dir, "--out", a.out, "--epochs", str(a.epochs), "--max-len", str(max_len)], st, step)
        elif step == "leak":
            rc = run([py, "-B", HERE / "leak_test.py", "--model", pathlib.Path(a.out) / "merged", "--data", data_dir / "train.jsonl", "--n", "100"], st, step)
            if rc != 0:
                print("!! досмотр не пройден: веса НЕ публиковать (см. LEAK_TEST.json)")
        elif step == "gguf":
            if not pathlib.Path("llama.cpp").is_dir():
                print("!! llama.cpp не найден рядом: git clone https://github.com/ggml-org/llama.cpp && pip install -r llama.cpp/requirements.txt && cmake -B llama.cpp/build -S llama.cpp && cmake --build llama.cpp/build --config Release -j")
                st["шаги"][step] = {"код": 3, "почему": "нет llama.cpp"}; save(st)
                continue
            rc = run([py, "-B", HERE / "export_gguf.py", pathlib.Path(a.out) / "merged", "Aletheia-0.0.5"], st, step)
        if rc != 0 and not a.only:
            print(f"!! шаг {step} завершился кодом {rc}; остальное не запускалось. Повтор: python {pathlib.Path(__file__).name}")
            return rc
    print("\nитог:", json.dumps(st["шаги"], ensure_ascii=False))
    print(f"прислать: {STATE}, {pathlib.Path(a.out) / 'TRAIN_REPORT.json'}, {pathlib.Path(a.out) / 'merged' / 'LEAK_TEST.json'}, {HERE / 'host_log.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
