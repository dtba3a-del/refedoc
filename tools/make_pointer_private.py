#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_pointer_private.py — указатели на материал, уехавший в приватную зону.

Отличие от публичных указателей одно и существенное: **прямой ссылки для
скачивания нет.** `prefedoc` приватен, ссылка на него бесполезна тому, у
кого нет доступа, и вредна тем, что выглядит рабочей. Поэтому указатель
называет путь и способ получить — клон репозитория, — а не адрес файла.

Производное: собирается прогоном по факту наличия файла в приватной зоне.

    python3 tools/make_pointer_private.py --workspace /home/user --dry-run
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIV_REPO = "https://github.com/dtba3a-del/prefedoc"

FILE_TPL = """# {name} — переехал в приватную зону

Справочный материал профиля разложен по двум зонам **по правовому разряду**.
Этот файл получил решение **«{verdict}»** и потому в публичную зону не едет;
он лежит в приватном репозитории [`prefedoc`]({repo}).

| | |
|---|---|
| было здесь | `{rel}` |
| стало | `prefedoc/{dest}` |
| решение разбора | **{verdict}** |
| вес | {mib:.2f} МиБ |
| sha256 | `{sha}` |

Прямой ссылки для скачивания здесь нет намеренно: репозиторий приватный, и
адрес файла в нём не работает у того, у кого нет доступа. Получить —
клонировать репозиторий:

```bash
git clone {repo}
```

Почему разряд именно такой — `refedoc/ПРАВА-ПОФАЙЛОВО.md`. Прежнее имя
файла, если оно менялось, — `prefedoc/ИМЕНА.md`.

Файл производный: собран `refedoc/tools/make_pointer_private.py`.
"""

DIR_TPL = """# Справочник этого каталога переехал в приватную зону

{n} файлов ({mib:.1f} МиБ) перенесены в приватный репозиторий
[`prefedoc`]({repo}), в `prefedoc/{dest_dir}` — структура каталога сохранена.

В публичную зону они не едут: решения разбора прав — «{verdicts}».

| файл | вес, МиБ | решение |
|---|---:|---|
{rows}

Файл производный: собран `refedoc/tools/make_pointer_private.py`.
"""


def sha256_of(p: Path) -> str:
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
    ap.add_argument("--private", default="/home/user/prefedoc")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root, priv, ws = Path(a.refedoc), Path(a.private), Path(a.workspace)
    rules = {r["repo"]: r["clone"] for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    rights = json.loads((root / "rights.json").read_text(encoding="utf-8"))
    inv = {}
    for rep in json.loads((root / "inventory.json").read_text(encoding="utf-8"))["repos"]:
        for x in rep["taken"]:
            inv[(rep["repo"], x["rel"])] = x
    renamed = {}
    np = priv / "имена.json"
    if np.is_file():
        for r in json.loads(np.read_text(encoding="utf-8")):
            renamed[r.get("источник", "")] = r["путь"]

    by_dir = defaultdict(list)
    written = 0
    for r in rights:
        if r["verdict"] == "публично":
            continue
        src_key = f"{r['repo']}/{r['rel']}"
        dest = renamed.get(src_key, src_key)
        pub = priv / dest
        if not pub.is_file():
            continue
        rec = inv.get((r["repo"], r["rel"]), {})
        size = rec.get("bytes") or pub.stat().st_size
        sha = rec.get("sha256") or sha256_of(pub)
        name = Path(r["rel"]).name
        out = ws / rules[r["repo"]] / (r["rel"] + ".где.md")
        by_dir[(r["repo"], Path(r["rel"]).parent.as_posix())].append(
            (name, size, r["verdict"], dest))
        if a.dry_run:
            print(f"[указатель] {out.relative_to(ws)}")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(FILE_TPL.format(name=name, rel=r["rel"], dest=dest,
                                           verdict=r["verdict"], mib=size / 2**20,
                                           sha=sha, repo=PRIV_REPO), encoding="utf-8")
        written += 1

    for (repo, d), items in by_dir.items():
        rows = "\n".join(f"| `{n}` | {sz / 2**20:.2f} | {v} |"
                         for n, sz, v, _ in sorted(items))
        verdicts = ", ".join(sorted({v for _, _, v, _ in items}))
        out = ws / rules[repo] / d / "КУДА-ПЕРЕЕХАЛО-ПРИВАТНО.md"
        if a.dry_run:
            print(f"[каталог]   {out.relative_to(ws)}  ({len(items)})")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(DIR_TPL.format(n=len(items),
                                          mib=sum(x[1] for x in items) / 2**20,
                                          dest_dir=f"{repo}/{d}", rows=rows,
                                          verdicts=verdicts, repo=PRIV_REPO),
                           encoding="utf-8")
        written += 1
    print(f"{'план: ' if a.dry_run else 'записано: '}{written} указателей")


if __name__ == "__main__":
    main()
