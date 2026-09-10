#!/usr/bin/env python3
"""Слитая модель → GGUF для LM Studio, переносимо (Windows/Linux/macOS):
convert_hf_to_gguf.py + llama-quantize из клона llama.cpp рядом (Gerganov
et al.). Части до 2 ГБ для GitHub Releases режутся здесь же, без `split`.

    python export_gguf.py runs/aiasa-0.0.5/merged Aletheia-0.0.5 [--llama llama.cpp] [--outdir .]

Пути: относительные — от папки комплекта (где лежит этот файл), не от текущей
папки оболочки; llama.cpp ищется в папке комплекта, рядом с ней, по LLAMA_CPP
и в текущей папке; GGUF и части кладутся в --outdir (по умолчанию — папка
комплекта), а не туда, откуда набрана команда.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PART = 1900 * 2 ** 20   # 1900 МиБ < предел Releases 2 ГБ


def absol(path) -> pathlib.Path:
    """Относительный путь — от папки комплекта; если там его нет, а от текущей папки есть — оттуда."""
    p = pathlib.Path(path)
    if p.is_absolute():
        return p
    here = HERE / p
    cwd = pathlib.Path.cwd() / p
    return (cwd if not here.exists() and cwd.exists() else here).resolve()


def find_llama(given: str | None) -> pathlib.Path | None:
    cands = ([absol(given)] if given else []) + [HERE / "llama.cpp", HERE.parent / "llama.cpp",
             pathlib.Path(os.environ["LLAMA_CPP"]) if os.environ.get("LLAMA_CPP") else None,
             pathlib.Path.cwd() / "llama.cpp"]
    for c in cands:
        if c is not None and (c / "convert_hf_to_gguf.py").is_file():
            return c.resolve()
    return None


def find_quantize(llama: pathlib.Path):
    names = ("llama-quantize", "llama-quantize.exe", "quantize", "quantize.exe")
    for sub in ("build/bin", "build/bin/Release", "build", "."):
        for n in names:
            p = llama / sub / n
            if p.is_file():
                return p
    return shutil.which("llama-quantize")


def split_parts(path: pathlib.Path) -> list:
    if path.stat().st_size <= PART:
        return []
    parts = []
    with path.open("rb") as f:
        i = 0
        while chunk := f.read(PART):
            out = path.with_name(f"{path.name}.part-{i:02d}")
            out.write_bytes(chunk)
            parts.append(out)
            i += 1
    return parts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("merged")
    ap.add_argument("name", nargs="?", default="Aletheia-0.0.5")
    ap.add_argument("--llama", default=None, help="клон llama.cpp (без флага — поиск: папка комплекта, рядом, LLAMA_CPP, текущая)")
    ap.add_argument("--outdir", default=None, help="куда класть GGUF и части (без флага — папка комплекта)")
    ap.add_argument("--quants", default="Q4_K_M,Q8_0")
    a = ap.parse_args(argv)
    merged = absol(a.merged)
    if not (merged / "config.json").is_file():
        print(f"!! слитая модель не найдена: {merged / 'config.json'} (шаг train не завершён или другая папка --out)")
        return 2
    llama = find_llama(a.llama)
    if llama is None:
        print(f"!! llama.cpp не найден ни в {HERE}, ни рядом, ни по LLAMA_CPP: cd {HERE} && git clone https://github.com/ggml-org/llama.cpp && pip install -r llama.cpp/requirements.txt")
        return 3
    conv = llama / "convert_hf_to_gguf.py"
    outdir = absol(a.outdir) if a.outdir else HERE
    outdir.mkdir(parents=True, exist_ok=True)
    f16 = outdir / f"{a.name}-f16.gguf"
    rc = subprocess.call([sys.executable, str(conv), str(merged), "--outfile", str(f16), "--outtype", "f16"])
    if rc:
        return rc
    q = find_quantize(llama)
    if q is None:
        print(f"!! llama-quantize не собран: cmake -B {llama / 'build'} -S {llama} && cmake --build {llama / 'build'} --config Release -j; пока есть только {f16}")
        return 4
    made = []
    for quant in a.quants.split(","):
        out = outdir / f"{a.name}-{quant}.gguf"
        rc = subprocess.call([str(q), str(f16), str(out), quant])
        if rc:
            return rc
        made.append(out)
        parts = split_parts(out)
        if parts:
            print(f"части для Releases: {[p.name for p in parts]} (собрать: cat/copy /b … > {out.name})")
    print(f"готово в {outdir}:", ", ".join(m.name for m in made), "— положить в каталог моделей LM Studio: <models>/Aletheia/Aletheia-0.0.5/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
