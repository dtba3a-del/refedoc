#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebalance_zones.py — привести раскладку в соответствие с решениями.

Решение о файле может измениться: разбор дошёл до титула, автор принял
решение по «не установлено», признак поправлен. Файл обязан переехать
следом — иначе раскладка расходится с разбором, и расходится молча.

Порядок тот же: **скопировать → сверить sha256 → и только потом удалить**.

    python3 tools/rebalance_zones.py --dry-run
    python3 tools/rebalance_zones.py --apply
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="/home/user")
    ap.add_argument("--refedoc", default=str(HERE.parent))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = Path(a.refedoc)
    ws = Path(a.workspace)
    zones = json.loads((HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["zones"]
    pub, priv = ws / zones["публичная"], ws / zones["приватная"]
    rights = json.loads((root / "rights.json").read_text(encoding="utf-8"))
    where = {}
    for rep in json.loads((root / "inventory.json").read_text(encoding="utf-8"))["repos"]:
        for x in rep["taken"]:
            where[(rep["repo"], x["rel"])] = x

    moves = []
    for r in rights:
        rec = where.get((r["repo"], r["rel"]))
        if not rec:
            continue
        want = "публичная" if r["verdict"] == "публично" else "приватная"
        if rec.get("зона") == want:
            continue
        src = Path(rec["abs"])
        dst = (pub if want == "публичная" else priv) / r["repo"] / r["rel"]
        moves.append((r["verdict"], rec.get("зона"), want, src, dst))

    for v, was, want, src, dst in moves:
        print(f"  [{v}] {was} → {want}: {src.name[:60]}")
    print(f"{'план: ' if not a.apply else ''}переложить {len(moves)}")
    if not a.apply:
        return

    done = 0
    for v, was, want, src, dst in moves:
        if not src.is_file():
            print(f"  пропущен, нет файла: {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha256(src) != sha256(dst):
            dst.unlink(missing_ok=True)
            print(f"  РАСХОЖДЕНИЕ ХЕША, оставлен на месте: {src.name}")
            continue
        src.unlink()
        done += 1
    print(f"переложено: {done}")


if __name__ == "__main__":
    main()
