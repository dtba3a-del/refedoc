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
    lines.insert(4, f"Итого к переносу: **{g_take}** файлов, **{g_bytes / 2**20:.1f} МиБ**; "
                    f"остаётся на месте: **{g_skip}**.\n")
    (out / "INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"к переносу: {g_take} файлов, {g_bytes / 2**20:.1f} МиБ; на месте: {g_skip}")
    print(f"записано: {out / 'INVENTORY.md'}, {out / 'inventory.json'}")


if __name__ == "__main__":
    main()
