#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_pointer.py — указатели на месте переехавшего справочника.

Производное: указатели собираются прогоном и руками не правятся.

    python3 tools/make_pointer.py --workspace /home/user --refedoc . --dry-run
    python3 tools/make_pointer.py --workspace /home/user --refedoc . --repo GPIBNIE7-12
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = "https://github.com/dtba3a-del/refedoc/raw/main"
WEB = "https://github.com/dtba3a-del/refedoc/blob/main"

FILE_TPL = """# {name} — переехал

Справочный материал профиля хранится в публичном репозитории
[`refedoc`](https://github.com/dtba3a-del/refedoc): он тяжёл, меняется
редко, а здесь тянулся при каждом клоне.

| | |
|---|---|
| было здесь | `{rel}` |
| стало | [`{dest}`]({web}) |
| вес | {mib:.2f} МиБ |
| sha256 | `{sha}` |
| скачать | `{raw}` |

```bash
curl -L -o "{name}" "{raw}"
```

Файл производный: собран `tools/make_pointer.py` в `refedoc`. Правка идёт
в генератор, не сюда.
"""

DIR_TPL = """# Справочник этого каталога переехал

{n} файлов ({mib:.1f} МиБ) перенесены в публичный репозиторий
[`refedoc`](https://github.com/dtba3a-del/refedoc), в
[`{dest_dir}`]({web_dir}) — структура каталога сохранена.

| файл | вес, МиБ | там |
|---|---:|---|
{rows}

Файл производный: собран `tools/make_pointer.py`. Правка идёт в генератор.
"""


def main():
    ap = argparse.ArgumentParser(description="Указатели на месте переехавшего справочника.")
    ap.add_argument("--workspace", default="/home/user")
    ap.add_argument("--refedoc", default=str(HERE.parent))
    ap.add_argument("--repo", default=None, help="только один репозиторий переписи")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root_pub = Path(a.refedoc)
    inv = json.loads((root_pub / "inventory.json").read_text(encoding="utf-8"))
    # Указатель ставится только на то, что ДЕЙСТВИТЕЛЬНО лежит в публичной
    # зоне. Указатель на непереехавший файл — ложь в производном файле,
    # и хуже отсутствия указателя.
    moved = {(r["repo"], r["rel"]) for r in
             json.loads((root_pub / "rights.json").read_text(encoding="utf-8"))
             if r["verdict"] == "публично"
             and (root_pub / r["repo"] / r["rel"]).is_file()}
    rules = {r["repo"]: r for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    ws = Path(a.workspace)
    written = 0

    for r in inv["repos"]:
        if a.repo and r["repo"] != a.repo:
            continue
        root = ws / rules[r["repo"]]["clone"]
        by_dir = defaultdict(list)
        for rec in r["taken"]:
            rel = rec["rel"]
            if (r["repo"], rel) not in moved:
                continue
            dest = f"{r['repo']}/{rel}"
            name = Path(rel).name
            body = FILE_TPL.format(
                name=name, rel=rel, dest=dest, web=f"{WEB}/{dest}",
                raw=f"{RAW}/{dest}", mib=rec["bytes"] / 2**20,
                sha=rec.get("sha256", "— (перепись без --hash)"))
            out = root / (rel + ".где.md")
            by_dir[Path(rel).parent.as_posix()].append((name, rec, dest))
            if a.dry_run:
                print(f"[указатель] {out.relative_to(ws)}")
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(body, encoding="utf-8")
            written += 1

        for d, items in by_dir.items():
            rows = "\n".join(
                f"| `{n}` | {rec['bytes'] / 2**20:.2f} | [там]({WEB}/{dest}) |"
                for n, rec, dest in sorted(items))
            dest_dir = f"{r['repo']}/{d}"
            body = DIR_TPL.format(n=len(items),
                                  mib=sum(x[1]["bytes"] for x in items) / 2**20,
                                  dest_dir=dest_dir, web_dir=f"{WEB}/{dest_dir}", rows=rows)
            out = root / d / "КУДА-ПЕРЕЕХАЛО.md"
            if a.dry_run:
                print(f"[каталог]   {out.relative_to(ws)}  ({len(items)} файлов)")
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(body, encoding="utf-8")
            written += 1

    print(f"{'план: ' if a.dry_run else 'записано: '}{written} указателей")


if __name__ == "__main__":
    main()
