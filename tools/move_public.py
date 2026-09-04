#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
move_public.py — перенос бесспорного в публичную зону.

Порядок жёсткий и не меняется: **скопировать → сверить sha256 → и только
потом удалить из источника.** Обратный порядок однажды стоил профилю 99 МиБ
дистрибутивов.

Переносится только то, у чего решение **«публично»**. Всё прочее —
«спорно», «непублично», «не установлено», «не определён» — не трогается:
отсутствие решения разрешением не считается.

    python3 tools/move_public.py --workspace /home/user --dry-run
    python3 tools/move_public.py --workspace /home/user            # копия + сверка
    python3 tools/move_public.py --workspace /home/user --delete   # + удаление из источника
"""
import argparse
import hashlib
import json
import shutil
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
    ap.add_argument("--delete", action="store_true",
                    help="удалить исходники ПОСЛЕ успешной сверки хешей")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = Path(a.refedoc)
    ws = Path(a.workspace)
    rows = json.loads((root / "rights.json").read_text(encoding="utf-8"))
    clones = {r["repo"]: r["clone"] for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    inv = {}
    for rep in json.loads((root / "inventory.json").read_text(encoding="utf-8"))["repos"]:
        for x in rep["taken"]:
            inv[(rep["repo"], x["rel"])] = x

    plan = [r for r in rows if r["verdict"] == "публично"]
    ok, mismatch, missing = [], [], []

    for r in plan:
        src = ws / clones[r["repo"]] / r["rel"]
        dst = root / r["repo"] / r["rel"]
        if not src.is_file():
            if dst.is_file():
                ok.append((r, "уже перенесён"))
            else:
                missing.append((r, "нет ни в источнике, ни в публичной зоне"))
            continue
        if a.dry_run:
            print(f"[план] {r['repo']}/{r['rel']}  ({r['bytes'] / 2**20:.2f} МиБ)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        h_src, h_dst = sha256(src), sha256(dst)
        known = inv.get((r["repo"], r["rel"]), {}).get("sha256")
        if h_src != h_dst or (known and known != h_src):
            mismatch.append((r, f"src {h_src[:12]} dst {h_dst[:12]} перепись {(known or '—')[:12]}"))
            dst.unlink(missing_ok=True)
            continue
        ok.append((r, h_dst))

    if a.dry_run:
        print(f"\nплан: {len(plan)} файлов, "
              f"{sum(r['bytes'] for r in plan) / 2**20:.1f} МиБ")
        return

    print(f"скопировано и сверено: {len(ok)} из {len(plan)}")
    for r, why in mismatch:
        print(f"  РАСХОЖДЕНИЕ ХЕША: {r['repo']}/{r['rel']} — {why}")
    for r, why in missing:
        print(f"  пропущен: {r['repo']}/{r['rel']} — {why}")

    if a.delete:
        if mismatch:
            print("\nудаление НЕ выполняется: есть расхождения хешей.")
            return
        n = 0
        for r, why in ok:
            src = ws / clones[r["repo"]] / r["rel"]
            if src.is_file():
                src.unlink()
                n += 1
        print(f"удалено из источников: {n}")


if __name__ == "__main__":
    main()
