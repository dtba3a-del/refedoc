#!/usr/bin/env python3
"""Слитая модель → GGUF для LM Studio, переносимо (Windows/Linux/macOS):
convert_hf_to_gguf.py + llama-quantize из клона llama.cpp рядом (Gerganov
et al.). Части до 2 ГБ для GitHub Releases режутся здесь же, без `split`.

    python export_gguf.py runs/aiasa-0.0.5/merged Aletheia-0.0.5 [--llama llama.cpp]
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

PART = 1900 * 2 ** 20   # 1900 МиБ < предел Releases 2 ГБ


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
    ap.add_argument("--llama", default="llama.cpp")
    ap.add_argument("--quants", default="Q4_K_M,Q8_0")
    a = ap.parse_args(argv)
    llama = pathlib.Path(a.llama)
    conv = llama / "convert_hf_to_gguf.py"
    if not conv.is_file():
        print(f"!! {conv} не найден: git clone https://github.com/ggml-org/llama.cpp && pip install -r llama.cpp/requirements.txt")
        return 3
    f16 = pathlib.Path(f"{a.name}-f16.gguf")
    rc = subprocess.call([sys.executable, str(conv), a.merged, "--outfile", str(f16), "--outtype", "f16"])
    if rc:
        return rc
    q = find_quantize(llama)
    if q is None:
        print("!! llama-quantize не собран: cmake -B llama.cpp/build -S llama.cpp && cmake --build llama.cpp/build --config Release -j; пока есть только f16")
        return 4
    made = []
    for quant in a.quants.split(","):
        out = pathlib.Path(f"{a.name}-{quant}.gguf")
        rc = subprocess.call([str(q), str(f16), str(out), quant])
        if rc:
            return rc
        made.append(out)
        parts = split_parts(out)
        if parts:
            print(f"части для Releases: {[p.name for p in parts]} (собрать: cat/copy /b … > {out.name})")
    print("готово:", ", ".join(m.name for m in made), "— положить в каталог моделей LM Studio: <models>/Aletheia/Aletheia-0.0.5/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
