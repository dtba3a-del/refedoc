#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_safety.py — досмотр справочных PDF на исполняемое и внешние действия.

Положение автора (2026-09-04): закладок ради пустых данных мы не
предполагаем, но проверять, что исходник не содержит вредоносного, —
можем и должны.

Проверяется не «вирусность» вообще, а конкретные места, где PDF перестаёт
быть бумагой и становится программой:

| признак | что это |
|---|---|
| `/JavaScript`, `/JS` | сценарий в документе |
| `/OpenAction`, `/AA` | действие при открытии или по событию |
| `/Launch` | запуск внешней программы |
| `/EmbeddedFile`, `/Filespec` | вложенный файл внутри документа |
| `/RichMedia`, `/Movie`, `/Sound` | встроенный проигрыватель |
| `/XFA` | форма со своей логикой |
| `/URI` | внешняя ссылка (не опасно само по себе, считается для сведения) |

**Что этот досмотр НЕ делает** — и это надо назвать: он не ищет
эксплойты в самих потоках изображений, не проверяет подписи и не
заменяет антивирус. Он отвечает на один вопрос: есть ли в документе
исполняемая часть. Отсутствие признаков есть отсутствие ЭТИХ признаков,
а не доказательство безопасности.

    python3 tools/pdf_safety.py --root /home/user/prefedoc
"""
import argparse
import json
import re
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MARKS = {
    "/JavaScript": "сценарий", "/JS": "сценарий",
    "/OpenAction": "действие при открытии", "/AA": "действие по событию",
    "/Launch": "запуск внешней программы",
    "/EmbeddedFile": "вложенный файл", "/Filespec": "ссылка на файл",
    "/RichMedia": "встроенный проигрыватель", "/Movie": "видео", "/Sound": "звук",
    "/XFA": "форма XFA",
}
INFO = {"/URI": "внешняя ссылка"}
DANGEROUS = {"/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/RichMedia", "/XFA",
             "/OpenAction", "/AA"}


def scan(path: Path) -> dict:
    try:
        raw = path.read_bytes()
    except OSError as e:
        return {"файл": str(path), "ошибка": str(e)}
    # часть объектов лежит в сжатых потоках: распаковываем то, что поддаётся
    blobs = [raw]
    for m in re.finditer(rb"stream\r?\n(.{20,200000}?)endstream", raw, re.S):
        try:
            blobs.append(zlib.decompress(m.group(1)))
        except zlib.error:
            pass
    found, info = {}, {}
    for b in blobs:
        for k, why in MARKS.items():
            n = b.count(k.encode())
            if n:
                found[k] = found.get(k, 0) + n
        for k, why in INFO.items():
            n = b.count(k.encode())
            if n:
                info[k] = info.get(k, 0) + n
    return {"файл": str(path), "исполняемое": {k: v for k, v in found.items()},
            "для сведения": info,
            "опасно": sorted(set(found) & DANGEROUS),
            "потоков распаковано": len(blobs) - 1}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()

    root = Path(a.root)
    files = [f for f in root.rglob("*.pdf") if f.is_file() and ".git" not in f.parts]
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        rows = list(ex.map(scan, files))
    bad = [r for r in rows if r.get("опасно")]
    print(f"просмотрено файлов: {len(rows)}; с исполняемой частью: {len(bad)}")
    for r in bad:
        print(f"  ! {Path(r['файл']).name[:60]}")
        det = r["исполняемое"]
        print("      " + ", ".join(f"{k}×{det[k]} ({MARKS[k]})" for k in r["опасно"]))
    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"подробности: {a.out}")
    print("\nОтсутствие признаков есть отсутствие ЭТИХ признаков, а не доказательство "
          "безопасности: эксплойты в потоках изображений этим досмотром не ищутся.")


if __name__ == "__main__":
    main()
