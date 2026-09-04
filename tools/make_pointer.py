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
import urllib.parse
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
| прежнее имя сохранено в | `refedoc/ИМЕНА.md` |
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
    # Имя в публичной зоне могло смениться на понятное (правило 4е канона):
    # указатель обязан вести на НЫНЕШНЕЕ имя, иначе он ведёт в пустоту.
    renamed = {}
    np = root_pub / "имена.json"
    if np.is_file():
        for r in json.loads(np.read_text(encoding="utf-8")):
            renamed[r["путь"]] = r.get("стало_путь", r["путь"])

    moved = {}
    for r in json.loads((root_pub / "rights.json").read_text(encoding="utf-8")):
        if r["verdict"] != "публично":
            continue
        dest_rel = f"{r['repo']}/{r['rel']}"
        dest_rel = renamed.get(dest_rel, dest_rel)
        if (root_pub / dest_rel).is_file():
            moved[(r["repo"], r["rel"])] = dest_rel
    rules = {r["repo"]: r for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    ws = Path(a.workspace)
    written = 0
    by_dir = defaultdict(list)

    # Итерация идёт по РЕШЕНИЯМ и по факту наличия файла в публичной зоне,
    # а не по переписи источника: после переноса файла в переписи источника
    # его уже нет, и обход по ней даёт ноль указателей там, где перенос
    # состоялся. Замер 2026-09-04: так генератор написал «0 указателей»
    # после переноса пятнадцати файлов.
    inv_by = {}
    for rep in inv["repos"]:
        for x in rep["taken"]:
            inv_by[(rep["repo"], x["rel"])] = x

    import hashlib

    def sha256_of(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    for (repo, rel), dest in sorted(moved.items()):
        if a.repo and repo != a.repo:
            continue
        root_src = ws / rules[repo]["clone"]
        pub = Path(a.refedoc) / dest
        rec = inv_by.get((repo, rel), {})
        size = rec.get("bytes") or pub.stat().st_size
        sha = rec.get("sha256") or sha256_of(pub)
        name = Path(rel).name
        # Пробелы и кириллица в имени обязаны быть закодированы: иначе ссылка
        # и команда скачивания не работают, а указатель без рабочей ссылки —
        # не указатель.
        q = urllib.parse.quote(dest)
        body = FILE_TPL.format(name=name, rel=rel, dest=dest, web=f"{WEB}/{q}",
                               raw=f"{RAW}/{q}", mib=size / 2**20, sha=sha)
        out = root_src / (rel + ".где.md")
        by_dir.setdefault(Path(rel).parent.as_posix(), []).append(
            (repo, name, size, dest))
        if a.dry_run:
            print(f"[указатель] {out.relative_to(ws)}")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
        written += 1

    for d, items in by_dir.items():
        repo = items[0][0]
        root_src = ws / rules[repo]["clone"]
        rows = "\n".join(f"| `{n}` | {sz / 2**20:.2f} | [там]({WEB}/{urllib.parse.quote(dest)}) |"
                          for _, n, sz, dest in sorted(items, key=lambda x: x[1]))
        body = DIR_TPL.format(n=len(items),
                              mib=sum(x[2] for x in items) / 2**20,
                              dest_dir=f"{repo}/{d}",
                              web_dir=f"{WEB}/{urllib.parse.quote(repo + '/' + d)}",
                              rows=rows)
        out = root_src / d / "КУДА-ПЕРЕЕХАЛО.md"
        if a.dry_run:
            print(f"[каталог]   {out.relative_to(ws)}  ({len(items)} файлов)")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
        written += 1

    print(f"{'план: ' if a.dry_run else 'записано: '}{written} указателей")


if __name__ == "__main__":
    main()
