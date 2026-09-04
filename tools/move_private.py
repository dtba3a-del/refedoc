#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
move_private.py — перенос НЕбесспорного в приватную зону `prefedoc`.

Зеркало `move_public.py`: тот же жёсткий порядок — **скопировать → сверить
sha256 → и только потом удалить из источника**, — но принимает всё, что
НЕ получило решения «публично»: спорное, непубличное, не установленное и
не разобранное.

Приватная зона не публикует ничего; решение о разряде на неё не влияет, и
поэтому ворот по правам здесь нет. Есть другой предел: сюда не едут
стенограммы, журналы и лотки проектов — этот репозиторий про справочник.

    python3 tools/move_private.py --workspace /home/user --dry-run
    python3 tools/move_private.py --workspace /home/user            # копия + сверка
    python3 tools/move_private.py --workspace /home/user --delete   # + удаление
"""
import argparse
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="/home/user")
    ap.add_argument("--refedoc", default=str(HERE.parent))
    ap.add_argument("--private", default="/home/user/prefedoc")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()

    root = Path(a.refedoc)
    priv = Path(a.private)
    ws = Path(a.workspace)
    rows = json.loads((root / "rights.json").read_text(encoding="utf-8"))
    clones = {r["repo"]: r["clone"] for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    inv = {}
    for rep in json.loads((root / "inventory.json").read_text(encoding="utf-8"))["repos"]:
        for x in rep["taken"]:
            inv[(rep["repo"], x["rel"])] = x

    plan = [r for r in rows if r["verdict"] != "публично"]
    if a.dry_run:
        print(f"план: {len(plan)} файлов, "
              f"{sum(r['bytes'] for r in plan) / 2**20:.1f} МиБ")
        for r in plan[:5]:
            print(f"  [{r['verdict']}] {r['repo']}/{r['rel']}")
        return

    def one(r):
        src = ws / clones[r["repo"]] / r["rel"]
        dst = priv / r["repo"] / r["rel"]
        if not src.is_file():
            return ("нет", r, "уже перенесён" if dst.is_file() else "нет в источнике")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        h_src, h_dst = sha256(src), sha256(dst)
        known = inv.get((r["repo"], r["rel"]), {}).get("sha256")
        if h_src != h_dst or (known and known != h_src):
            dst.unlink(missing_ok=True)
            return ("расхождение", r, f"src {h_src[:12]} dst {h_dst[:12]} "
                                      f"перепись {(known or '—')[:12]}")
        return ("ок", r, h_dst)

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        res = list(ex.map(one, plan))

    ok = [x for x in res if x[0] == "ок"]
    bad = [x for x in res if x[0] == "расхождение"]
    miss = [x for x in res if x[0] == "нет"]
    print(f"скопировано и сверено: {len(ok)} из {len(plan)}")
    for _, r, why in bad:
        print(f"  РАСХОЖДЕНИЕ ХЕША: {r['repo']}/{r['rel']} — {why}")
    for _, r, why in miss:
        print(f"  пропущен: {r['repo']}/{r['rel']} — {why}")

    if a.delete:
        if bad:
            print("\nудаление НЕ выполняется: есть расхождения хешей.")
            return
        n = 0
        for _, r, _h in ok:
            src = ws / clones[r["repo"]] / r["rel"]
            if src.is_file():
                src.unlink()
                n += 1
        print(f"удалено из источников: {n}")


if __name__ == "__main__":
    main()
