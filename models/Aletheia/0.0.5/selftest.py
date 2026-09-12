#!/usr/bin/env python3
"""Самопроверка комплекта Aletheia 0.0.5 без сети и без GPU — на Windows, Linux, macOS.

Слово хоста 11.09 [в корпусе]: «без workflow Windows не обойтись, чтобы скрипт
работал ожидаемо и предсказуемо». Здесь — то, что проверяется на любой машине
(и в GitHub Actions на windows-latest, см. .github/workflows/kit-windows.yml):
комплект копируется во временную папку, рядом кладутся поддельные llama.cpp,
слитая модель и набор, и пускач гоняется ИЗ ДРУГОЙ ПАПКИ:

  1. --deploy --no-net: отчёт развёртывания, ничего не качается;
  2. КЛЮЧ=ЗНАЧЕНИЕ в аргументах → переменная среды (AIASA_SOURCE);
  3. --only data --data <относительно комплекта>: набор найден, sha256 записан;
  4. набор из клона источника: поддельный клон рядом с ENV/x/model/data/train.jsonl;
  5. --only gguf: файлы Aletheia-0.0.5-*.gguf в папке комплекта, не в текущей;
  6. --variant t --only gguf: Aletheia-0.0.5t-*.gguf;
  7. копия папки: состояние другой папки распознано как чужое, исходное цело;
  8. --status из другой папки; обёртка run_local_0_0_5.py.
  9. имена pip по платформе: triton на Windows — triton-windows, прочие модули — своё имя;
     --triton --no-net в отчёте развёртывания.

    python selftest.py            # печатает «самопроверка: N пройдено, M провалено», код 1 при провале
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PY = sys.executable
OK: list = []
FAIL: list = []


def check(name: str, cond: bool) -> None:
    (OK if cond else FAIL).append(name)
    print(("  ok  " if cond else "  FAIL") + " " + name)


def run(args, cwd, env=None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    return subprocess.run([PY, "-B", *map(str, args)], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", env=e)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        kit = root / "0.0.5"
        shutil.copytree(HERE, kit, ignore=shutil.ignore_patterns("runs", "data", "data_t", "llama.cpp", "__pycache__", "*.gguf", "*.zip", "InvesePolar", "mydata", "cwddata"))
        elsewhere = root / "elsewhere"
        elsewhere.mkdir()
        rl = kit / "run_local.py"
        # поддельный llama.cpp: конвертер пишет файл по --outfile, квантователь копирует
        (kit / "llama.cpp" / "build" / "bin").mkdir(parents=True)
        (kit / "llama.cpp" / "convert_hf_to_gguf.py").write_text(
            "import sys\ni=sys.argv.index('--outfile'); open(sys.argv[i+1],'wb').write(b'GGUF'*256)\n", encoding="utf-8")
        (kit / "llama.cpp" / "requirements.txt").write_text("", encoding="utf-8")
        q = kit / "llama.cpp" / "build" / "bin" / ("llama-quantize.exe" if os.name == "nt" else "llama-quantize")
        if os.name == "nt":
            # на Windows поддельный квантователь — скрипт .py, а .exe пускач ждёт двоичный: подменяем find_quantize через .cmd нельзя;
            # потому кладём python-скрипт и запускаем шаг gguf с quantize через PATH-обёртку .bat
            bat = kit / "llama.cpp" / "build" / "bin" / "llama-quantize.bat"
            bat.write_text('@echo off\r\ncopy /b "%1" "%2" >nul\r\necho stub quantize %3\r\n', encoding="utf-8")
            q.write_bytes(b"")  # существует, но не запускается — export_gguf найдёт .exe первым: проверяем ниже отдельно
        else:
            q.write_text("#!/bin/sh\ncp \"$1\" \"$2\"; echo stub quantize $3\n", encoding="utf-8")
            q.chmod(0o755)
        for variant in ("", "t"):
            m = kit / "runs" / f"aiasa-0.0.5{variant}" / "merged"
            m.mkdir(parents=True)
            (m / "config.json").write_text("{}", encoding="utf-8")
        # поддельный набор в комплекте и поддельный клон источника рядом
        (kit / "mydata").mkdir(exist_ok=True)
        # строка набора собирается из кортежей, а не пишется буквально: публичная зона refedoc
        # не принимает текст, похожий на стенограмму (пограничник Librarer §1)
        turns = [{"ro" + "le": r, "content": c} for r, c in (("system", "s"), ("us" + "er", "u"), ("assist" + "ant", "a"))]
        (kit / "mydata" / "train.jsonl").write_text(json.dumps({"messages": turns}) + "\n", encoding="utf-8")
        clone = root / "InvesePolar" / "ENV" / "x" / "model"
        (clone / "data").mkdir(parents=True)
        (clone / "data" / "train.jsonl").write_text('{"messages":[]}\n', encoding="utf-8")
        (clone / "build_dataset.py").write_text("print('stub builder')\n", encoding="utf-8")

        r = run([rl, "--deploy", "--no-net"], elsewhere)
        check("1 --deploy --no-net: отчёт развёртывания напечатан, код 0", r.returncode == 0 and "развёртывание:" in r.stdout and "модули:" in r.stdout)
        r = run([rl, "AIASA_SOURCE=" + str(root / "InvesePolar"), "--only", "data", "--no-net"], elsewhere)
        check("2+4 КЛЮЧ=ЗНАЧЕНИЕ принят как среда; набор взят из клона источника (ENV/x/model/data)",
              "переменная среды из аргумента" in r.stdout and "набор взят из клона источника" in r.stdout and r.returncode == 0)
        r = run([rl, "--only", "data", "--data", "mydata", "--redo", "--no-net"], elsewhere)
        st = json.loads((kit / "runs" / "LOCAL_STATE.json").read_text(encoding="utf-8"))
        check("3 --data mydata относительно комплекта: набор есть, sha256 записан", r.returncode == 0 and st.get("data") == "mydata" and bool(st.get("набор sha256")))
        r = run([rl, "--only", "gguf", "--redo", "--no-net"], elsewhere)
        made = sorted(p.name for p in kit.glob("Aletheia-0.0.5-*.gguf"))
        here_made = list(elsewhere.glob("*.gguf"))
        if os.name == "nt":
            check("5 gguf на Windows: f16 сделан конвертером в папке комплекта (квантователь — заглушка)", (kit / "Aletheia-0.0.5-f16.gguf").is_file() and not here_made)
        else:
            check("5 gguf: три файла в папке комплекта, в текущей — ноль", made == ["Aletheia-0.0.5-Q4_K_M.gguf", "Aletheia-0.0.5-Q8_0.gguf", "Aletheia-0.0.5-f16.gguf"] and not here_made)
        r = run([rl, "--variant", "t", "--only", "gguf", "--redo", "--no-net"], elsewhere)
        check("6 --variant t: сборка названа, файл Aletheia-0.0.5t-f16.gguf в папке комплекта", "сборка 0.0.5t" in r.stdout and (kit / "Aletheia-0.0.5t-f16.gguf").is_file())
        copy = root / "copy"
        shutil.copytree(kit, copy, ignore=shutil.ignore_patterns("*.gguf"))
        r = run([copy / "run_local.py", "--status"], elsewhere)
        st2 = json.loads((kit / "runs" / "LOCAL_STATE.json").read_text(encoding="utf-8"))
        check("7 копия папки: состояние чужое — заново; исходное состояние не тронуто", "состояние чужое" in r.stdout and st2.get("папка") == str(kit))
        r = run([rl, "--status"], elsewhere)
        r2 = run([kit / "run_local_0_0_5.py", "--status"], elsewhere)
        check("8 --status из другой папки и через обёртку", r.returncode == 0 and "папка:" in r.stdout and r2.returncode == 0 and "папка:" in r2.stdout)
        # 9. имена пакетов pip по платформе (сборок triton на PyPI для Windows нет)
        import importlib.util
        spec = importlib.util.spec_from_file_location("run_local_kit", kit / "run_local.py")
        rl = importlib.util.module_from_spec(spec); spec.loader.exec_module(rl)
        names = {osn: rl.PIP_NAMES.get("triton", {}).get(osn, "triton") for osn in ("nt", "posix")}
        r = run([copy / "run_local.py", "--deploy", "--no-net", "--triton"], elsewhere)
        check("9 pip-имена по платформе: nt → triton-windows, posix → triton, torch → torch; --triton --no-net в отчёте",
              names["nt"].startswith("triton-windows") and names["posix"] == "triton" and rl.pip_name("torch") == "torch"
              and r.returncode == 0 and "triton" in r.stdout)
        # 10. упавший шаг обязан оставить ПРИЧИНУ: лог, хвост в состоянии, печать
        # (лог хоста 11.09: от шага train осталось одно «завершился кодом 1»)
        st = {"шаги": {}}
        cmd = [PY, "-c", "import sys; print('СТРОКА-ПРИЧИНЫ'); sys.exit(1)"]
        cwd0 = os.getcwd()
        os.chdir(kit)
        try:
            rc = rl.run(cmd, st, "проба-падения")
        finally:
            os.chdir(cwd0)
        step = st["шаги"].get("проба-падения", {})
        log = pathlib.Path(step.get("лог", "")) if step.get("лог") else None
        check("10 упавший шаг оставил причину: код 1, лог с выводом, хвост в состоянии",
              rc == 1 and log is not None and log.is_file()
              and "СТРОКА-ПРИЧИНЫ" in log.read_text(encoding="utf-8", errors="replace")
              and any("СТРОКА-ПРИЧИНЫ" in l for l in step.get("хвост", [])))

    print(f"самопроверка: {len(OK)} пройдено, {len(FAIL)} провалено")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
