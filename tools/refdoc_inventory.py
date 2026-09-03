#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refdoc_inventory.py — перепись справочного материала в репозиториях-источниках.

Производное собирается прогоном: INVENTORY.md и inventory.json НЕ правятся
руками, правка идёт в tools/refdoc_rules.json.

    python3 tools/refdoc_inventory.py --workspace /home/user --out .
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "refdoc_rules.json"


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()



ENV = {**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}


def signature(path: Path, probe_pages: int = 3) -> str:
    """
    Подпись СОДЕРЖИМОГО, а не файла.

    Замер 2026-09-03 в `GPIBNIE7-12/docs`: три пары патентов различаются по
    sha256 файла (свыше 800 тыс. байт различий), но вложенный растр первой
    страницы у них побайтно один и тот же — это один документ в двух
    обёртках PDF. Хеш файла такие пары не видит.

    Первая редакция подписи строилась по описи потоков (страница, размеры,
    кодировка, ppi) и на том же корпусе дала **две ложные пары**: разные
    патенты с одинаковым форматом скана неотличимы по описи. Поэтому подпись
    считается по самим потокам: sha256 растров первых `probe_pages` страниц
    плюс число страниц и длина текстового слоя.

    Ложное совпадение при этом не исключено полностью — совпасть могут
    первые страницы при разных последующих. Перед удалением чего-либо
    сверять файлы целиком, а не подписью.
    """
    ext = path.suffix.lower()
    parts = []
    if ext == ".pdf" and shutil.which("pdfimages") and shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True,
                              errors="replace", env=ENV).stdout
        m = re.search(r"^Pages:\s+(\d+)", info, re.M)
        parts.append("pages=" + (m.group(1) if m else "?"))
        if shutil.which("pdftotext"):
            t = subprocess.run(["pdftotext", str(path), "-"], capture_output=True,
                               text=True, errors="replace", env=ENV).stdout
            parts.append(f"txt={len(t.strip())}")
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["pdfimages", "-f", "1", "-l", str(probe_pages), "-png",
                            str(path), str(Path(td) / "p")],
                           capture_output=True, env=ENV)
            for f in sorted(Path(td).iterdir()):
                parts.append(f.name.split("-")[-1] + "=" + sha256(f)[:32])
    elif ext in (".djvu", ".djv") and shutil.which("djvused"):
        n = subprocess.run(["djvused", str(path), "-e", "n"], capture_output=True,
                           text=True, errors="replace", env=ENV).stdout.strip()
        parts.append("pages=" + n)
        if shutil.which("ddjvu"):
            with tempfile.TemporaryDirectory() as td:
                for pg in range(1, probe_pages + 1):
                    out = Path(td) / f"p{pg}.pnm"
                    r = subprocess.run(["ddjvu", "-format=pnm", f"-page={pg}",
                                        str(path), str(out)], capture_output=True, env=ENV)
                    if r.returncode == 0 and out.exists():
                        parts.append(f"p{pg}=" + sha256(out)[:32])
    if len(parts) < 2:
        return ""                      # подписи нет — молчим, а не выдумываем
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def scan_repo(root: Path, rule: dict) -> dict:
    """Возвращает {'taken': [...], 'skipped': [...], 'total': N} по одному репозиторию."""
    exts = {e.lower() for e in rule["_exts"]}
    taken, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            p = Path(dirpath) / fn
            ext = p.suffix.lower().lstrip(".")
            if ext not in exts:
                continue
            rel = p.relative_to(root).as_posix()
            inc = any(rel.startswith(i) for i in rule["include"])
            exc = any(rel.startswith(e) for e in rule["exclude"])
            rec = {"rel": rel, "bytes": p.stat().st_size, "ext": ext}
            if inc and not exc:
                taken.append(rec)
            else:
                rec["reason"] = "исключён правилом" if exc else "вне include"
                skipped.append(rec)
    taken.sort(key=lambda r: r["rel"])
    skipped.sort(key=lambda r: r["rel"])
    return {"taken": taken, "skipped": skipped, "total": len(taken) + len(skipped)}


def main():
    ap = argparse.ArgumentParser(description="Перепись справочных PDF/DjVu в репозиториях-источниках.")
    ap.add_argument("--workspace", default="/home/user", help="каталог, где лежат клоны репозиториев")
    ap.add_argument("--out", default=str(HERE.parent), help="куда писать INVENTORY.md и inventory.json")
    ap.add_argument("--hash", action="store_true", help="считать sha256 (медленно, для сверки после переноса)")
    ap.add_argument("--signature", action="store_true",
                    help="считать подпись содержимого — ловит один документ в разных обёртках")
    args = ap.parse_args()

    rules = json.loads(RULES.read_text(encoding="utf-8"))
    ws = Path(args.workspace)
    out = Path(args.out)

    repos = sorted(rules["repos"], key=lambda r: r["order"])
    for r in repos:
        r["_exts"] = rules["extensions"]

    def work(rule):
        root = ws / rule["clone"]
        if not root.is_dir():
            return rule, {"taken": [], "skipped": [], "total": 0, "error": f"нет клона: {root}"}
        res = scan_repo(root, rule)
        if args.hash:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for rec, h in zip(res["taken"], ex.map(lambda rc: sha256(root / rc["rel"]), res["taken"])):
                    rec["sha256"] = h
        if args.signature:
            with ThreadPoolExecutor(max_workers=4) as ex:
                for rec, sg in zip(res["taken"], ex.map(lambda rc: signature(root / rc["rel"]), res["taken"])):
                    rec["signature"] = sg
        return rule, res

    with ThreadPoolExecutor(max_workers=len(repos) or 1) as ex:
        results = list(ex.map(work, repos))

    data = {"workspace": str(ws), "extensions": rules["extensions"], "repos": []}
    for rule, res in results:
        data["repos"].append({
            "repo": rule["repo"], "order": rule["order"], "note": rule.get("note", ""),
            "include": rule["include"], "exclude": rule["exclude"], **res,
        })

    (out / "inventory.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Перепись справочного материала", "",
             "**Файл производный.** Собран `tools/refdoc_inventory.py` по правилам",
             "`tools/refdoc_rules.json`. Руками не править — правка уходит в правила.", ""]
    g_take = g_skip = g_bytes = 0
    for r in data["repos"]:
        tb = sum(x["bytes"] for x in r["taken"])
        g_take += len(r["taken"]); g_skip += len(r["skipped"]); g_bytes += tb
        lines += [f"## {r['order']}. `{r['repo']}`", "",
                  f"Найдено PDF/DjVu: **{r['total']}**; к переносу: **{len(r['taken'])}** "
                  f"({tb / 2**20:.1f} МиБ); остаётся на месте: **{len(r['skipped'])}**.", ""]
        if r.get("note"):
            lines += [f"Основание отбора: {r['note']}", ""]
        lines += ["| путь в источнике | МиБ |", "|---|---:|"]
        lines += [f"| `{x['rel']}` | {x['bytes'] / 2**20:.2f} |" for x in r["taken"]]
        lines.append("")
        if r["skipped"]:
            lines += ["<details><summary>Остаётся на месте</summary>", "",
                      "| путь | причина |", "|---|---|"]
            lines += [f"| `{x['rel']}` | {x['reason']} |" for x in r["skipped"]]
            lines += ["", "</details>", ""]
    def groups(key):
        acc = {}
        for r in data["repos"]:
            for x in r["taken"]:
                k = x.get(key)
                if k:
                    acc.setdefault(k, []).append((r["repo"], x["rel"], x["bytes"]))
        return {k: v for k, v in acc.items() if len(v) > 1}

    exact, near = groups("sha256"), groups("signature")
    if exact or near:
        lines += ["## Дубли", ""]
        seen_exact = {tuple(sorted((r, p) for r, p, _ in v)) for v in exact.values()}
        for title, gs, only_new in (("Побайтно одинаковые", exact, False),
                                    ("Один документ в разной обёртке", near, True)):
            gg = {k: v for k, v in gs.items()
                  if not (only_new and tuple(sorted((r, p) for r, p, _ in v)) in seen_exact)}
            if not gg:
                continue
            waste = sum(v[0][2] * (len(v) - 1) for v in gg.values())
            lines += [f"**{title}:** {len(gg)} групп, лишних копий "
                      f"{sum(len(v) - 1 for v in gg.values())}, впустую {waste / 2**20:.1f} МиБ.", ""]
            for k, v in sorted(gg.items(), key=lambda kv: -kv[1][0][2]):
                lines.append(f"* {v[0][2] / 2**20:.2f} МиБ — " +
                             "; ".join(f"`{r}/{p}`" for r, p, _ in sorted(v)))
            lines.append("")

    lines.insert(4, f"Итого к переносу: **{g_take}** файлов, **{g_bytes / 2**20:.1f} МиБ**; "
                    f"остаётся на месте: **{g_skip}**.\n")
    (out / "INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"к переносу: {g_take} файлов, {g_bytes / 2**20:.1f} МиБ; на месте: {g_skip}")
    print(f"записано: {out / 'INVENTORY.md'}, {out / 'inventory.json'}")


if __name__ == "__main__":
    main()
