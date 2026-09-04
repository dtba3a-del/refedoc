#!/usr/bin/env python3
"""То же, что run_local.py рядом (имя, под которым команда уже набиралась на
хосте: python C:\\0.0.5\\run_local_0_0_5.py). Аргументы передаются как есть."""
import pathlib
import runpy
import sys

kit = pathlib.Path(__file__).resolve().parent / "run_local.py"
if not kit.is_file():
    raise SystemExit(f"{kit} не найден: скачать папку модели целиком (bootstrap.ps1 делает это одной вставкой)")
sys.argv = [str(kit)] + sys.argv[1:]
runpy.run_path(str(kit), run_name="__main__")
