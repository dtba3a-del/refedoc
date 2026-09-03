#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rights_classify.py — пофайловый разбор правового статуса справочного корпуса.

Производное: `ПРАВА-ПОФАЙЛОВО.md` собирается прогоном, руками не правится;
правка идёт в `tools/rights_rules.json`.

Разбор ведётся по **уликам в самом файле**: метаданные PDF и текст первых
страниц. Улика приводится в отчёте дословно — вывод без предъявленной улики
есть догадка.

**Покрытие объявляется числом.** Файл, в котором улик не нашлось, попадает в
разряд «не определён» и НЕ считается разобранным: ноль улик есть факт об
извлекателе, а не о файле.

    python3 tools/rights_classify.py --workspace /home/user --out .
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = {**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
PROBE_PAGES = 3


def ocr_first_page(path: Path) -> str:
    """Распознавание первой страницы. Улика, снятая машиной, помечается как таковая."""
    try:
        with tempfile.TemporaryDirectory() as td:
            pref = Path(td) / "p"
            # -scale-to, а не -r: разрешение задаёт документ, и у патентов
            # «200 dpi» означало 6444×9467 — распознаванию титульной страницы
            # столько не нужно, а время растёт с площадью. Замер 2026-09-03:
            # прогон по 50 сканам не уложился в десять минут и был прерван.
            subprocess.run(["pdftoppm", "-png", "-scale-to", "2200", "-f", "1", "-l", "1",
                            "-singlefile", str(path), str(pref)],
                           check=True, capture_output=True, env=ENV)
            r = subprocess.run(["tesseract", str(pref.with_suffix(".png")), "stdout",
                                "-l", "rus+eng"], capture_output=True, text=True,
                               errors="replace", env=ENV)
            return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def evidence_text(path: Path) -> str:
    """Метаданные плюс текст первых страниц — то, по чему судим."""
    parts = []
    ext = path.suffix.lower()
    if ext == ".pdf":
        if shutil.which("pdfinfo"):
            parts.append(subprocess.run(["pdfinfo", str(path)], capture_output=True,
                                        text=True, errors="replace", env=ENV).stdout)
        page_text = ""
        if shutil.which("pdftotext"):
            page_text = subprocess.run(["pdftotext", "-layout", "-f", "1",
                                        "-l", str(PROBE_PAGES), str(path), "-"],
                                       capture_output=True, text=True,
                                       errors="replace", env=ENV).stdout
            parts.append(page_text)
        # Патенты и ГОСТы в корпусе — сканы без текстового слоя. Прогон
        # 2026-09-03: улик не нашлось у 50 файлов из 125, и все патенты попали
        # в «не определён» — ноль улик был фактом об извлекателе, не о файлах.
        # Порог считается ТОЛЬКО по тексту страниц: первая редакция мерила его
        # вместе с метаданными, метаданные всегда длиннее порога, и
        # распознавание не запускалось ни разу.
        if len(page_text.strip()) < 200 and shutil.which("tesseract") and shutil.which("pdftoppm"):
            parts.append(ocr_first_page(path))
    elif ext in (".djvu", ".djv"):
        if shutil.which("djvutxt"):
            for pg in range(1, PROBE_PAGES + 1):
                parts.append(subprocess.run(["djvutxt", f"--page={pg}", str(path)],
                                            capture_output=True, text=True,
                                            errors="replace", env=ENV).stdout)
    return "\n".join(parts)


def classify(text: str, classes):
    """Все сработавшие разряды с уликами; решение — по строгости."""
    hits = []
    for c in classes:
        found = [m for m in c["markers"] if m in text]
        if found:
            snippet = ""
            m = re.search(re.escape(found[0]) + r".{0,90}", text, re.S)
            if m:
                snippet = " ".join(m.group(0).split())[:110]
            hits.append({"id": c["id"], "verdict": c["verdict"],
                         "marker": found[0], "snippet": snippet, "why": c["why"]})
    return hits


ORDER = {"непублично": 0, "спорно": 1, "публично": 2}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="/home/user")
    ap.add_argument("--out", default=str(HERE.parent))
    ap.add_argument("--inventory", default=None)
    a = ap.parse_args()

    out = Path(a.out)
    inv = json.loads(Path(a.inventory or (out / "inventory.json")).read_text(encoding="utf-8"))
    rules = json.loads((HERE / "rights_rules.json").read_text(encoding="utf-8"))["classes"]
    clones = {r["repo"]: r for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    ws = Path(a.workspace)

    jobs = []
    for r in inv["repos"]:
        root = ws / clones[r["repo"]]["clone"]
        for x in r["taken"]:
            jobs.append((r["repo"], x["rel"], root / x["rel"], x["bytes"]))

    def work(j):
        repo, rel, path, size = j
        hits = classify(evidence_text(path), rules) if path.exists() else []
        if hits:
            verdict = sorted(hits, key=lambda h: ORDER[h["verdict"]])[0]["verdict"]
        else:
            verdict = "не определён"
        return {"repo": repo, "rel": rel, "bytes": size, "verdict": verdict, "hits": hits}

    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(work, jobs))

    counts = {}
    for x in rows:
        counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
    determined = len(rows) - counts.get("не определён", 0)

    lines = ["# Правовой статус пофайлово — черновой разбор", "",
             "**Файл производный.** Собран `tools/rights_classify.py` по признакам",
             "`tools/rights_rules.json`. Руками не править.", "",
             "Разбор ведётся по уликам в самом файле: метаданные PDF и текст первых",
             f"{PROBE_PAGES} страниц. Улика приводится дословно — вывод без",
             "предъявленной улики есть догадка, а не разбор.", "",
             "## Покрытие", "",
             f"Файлов в переписи: **{len(rows)}**. Улики найдены у **{determined}** "
             f"(**{100 * determined / max(1, len(rows)):.0f} %**); "
             f"у **{counts.get('не определён', 0)}** улик нет — эти файлы "
             "**не разобраны**, а не «свободны».", "",
             "| разряд решения | файлов |", "|---|---:|"]
    for v in ("публично", "спорно", "непублично", "не определён"):
        if v in counts:
            lines.append(f"| {v} | {counts[v]} |")
    lines += ["", "Решение при нескольких сработавших разрядах берётся **строжайшее**.",
              "", "## Разбор", ""]

    for v in ("публично", "спорно", "непублично", "не определён"):
        sel = [x for x in rows if x["verdict"] == v]
        if not sel:
            continue
        lines += [f"### {v} — {len(sel)} файлов", ""]
        if sel[0]["hits"]:
            lines.append(sel[0]["hits"][0]["why"] + "\n")
        lines += ["| файл | разряд | улика в файле |", "|---|---|---|"]
        for x in sorted(sel, key=lambda x: (x["repo"], x["rel"])):
            h = x["hits"][0] if x["hits"] else None
            lines.append(f"| `{x['repo']}/{x['rel']}` | {h['id'] if h else '—'} | "
                         f"{('`' + h['snippet'] + '`') if h and h['snippet'] else '— улик не найдено'} |")
        lines.append("")

    lines += ["## Чего этот разбор не делает", "",
              "* Не читает лицензию конкретного препринта arXiv — она задаётся автором",
              "  пофайлово и лежит на странице препринта, а не в PDF. Разряд «спорно»",
              "  здесь означает «идти и читать», а не «наверное можно».",
              "* Не проверяет, правомерно ли получен файл. Разбор говорит о статусе",
              "  документа, не о происхождении копии.",
              "* Не заменяет решения правообладателя или юриста; это разбор улик.", ""]
    (out / "ПРАВА-ПОФАЙЛОВО.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "rights.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    print(f"файлов {len(rows)}; улики найдены у {determined} "
          f"({100 * determined / max(1, len(rows)):.0f} %)")
    for v in ("публично", "спорно", "непублично", "не определён"):
        if v in counts:
            print(f"  {v:14s} {counts[v]}")


if __name__ == "__main__":
    main()
