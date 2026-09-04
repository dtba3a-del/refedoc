#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_private.py — заготовка приватной зоны справочного корпуса.

Публичная зона (`refedoc`) и приватная — две половины одного корпуса, и
раскладка между ними идёт **по правовому разряду**, а не по объёму:

| зона | что лежит |
|---|---|
| `refedoc` (публичная) | инструменты, разборы, перепись, указатели, карточки; материал с решением «публично» — целыми файлами |
| `refedoc-private` (приватная) | всё прочее: спорное, непубличное, не установленное; исходники, полные наборы кусков, индексы с координатами |

    python3 tools/seed_private.py --dest /home/user/refedoc-private
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

README = """# `refedoc-private` — приватная зона справочного корпуса

Вторая половина корпуса. Публичная — [`refedoc`](https://github.com/dtba3a-del/refedoc).

Раскладка идёт **по правовому разряду**, а не по объёму:

| зона | что лежит |
|---|---|
| `refedoc` | инструменты, разборы, перепись, указатели, карточки; материал с решением **«публично»** — целыми файлами, без нарезки |
| **здесь** | **спорное, непубличное и не установленное**; исходники, полные наборы кусков, индексы с координатами и соседями |

## Почему так, а не «объём наружу, механизм внутрь»

Замер 2026-09-03 (`refedoc/docs/ИНДЕКС-В-ПРИВАТЕ.md`): 103 стыка из 104
сходятся побайтно за 2.3 секунды по одному лишь нахлёсту, без индекса и без
имён. Изъятие индекса набор не защищает. А место кусков **безразлично для
чтения и решающе для права**: модель достаёт их одинаково хоть отсюда, хоть
из публичного репозитория.

Отсюда правило: выбирать место по праву, а не по удобству.

## Что здесь лежит

```
<Репозиторий-источник>/<тот же путь, что был там>      исходники
наборы/<Репозиторий>/<путь>/                           куски, текст, индексы
```

Структура каталогов источника сохраняется, имена файлов не меняются.

## Инструменты

Свои не заводятся. Всё работает инструментами из `refedoc/tools/`:

```bash
python3 refedoc/tools/doc_slicer.py slice ФАЙЛ -o наборы/... --max-px 6000
python3 refedoc/tools/doc_slicer.py get наборы/.../index.json --page 7 --tile 45
python3 refedoc/tools/refdoc_inventory.py --workspace .. --out . --hash --signature
```

## Чего здесь нет

**Стенограмм переписки, журналов сессий и лотков проектов.** Приватность
этого репозитория — не основание сваливать сюда всё: он про справочный
материал. Стенограммы живут в своих проектах.

## Правило объёма

Перенос материала из проектного репозитория **не освобождает** там место,
пока история не переписана: файлы остаются в паках. Выигрыш по объёму
наступает отдельным шагом и с отдельной ценой — см. `refedoc/docs/ПУБЛИЧНОСТЬ-ПО-УМОЛЧАНИЮ.md` §2.
"""

GITIGNORE = """# Производное от прогонов — собирается заново.
sliced_output/
_test/
__pycache__/
*.pyc

# Сюда не сваливается то, что живёт в проектах.
chatlog/
sessions/
context-export/
*.jsonl
.env
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--rights", default=str(HERE.parent / "rights.json"))
    a = ap.parse_args()

    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.md").write_text(README, encoding="utf-8")
    (dest / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    rows = json.loads(Path(a.rights).read_text(encoding="utf-8"))
    plan = [r for r in rows if r["verdict"] != "публично"]
    by = {}
    for r in plan:
        by.setdefault(r["repo"], []).append(r)
    lines = ["# План наполнения приватной зоны", "",
             "**Файл производный.** Собран `refedoc/tools/seed_private.py` по",
             "`refedoc/rights.json`. Руками не править.", "",
             f"К переносу сюда: **{len(plan)}** файлов "
             f"({sum(r['bytes'] for r in plan) / 2**20:.1f} МиБ).", ""]
    for repo in sorted(by):
        sel = by[repo]
        lines += [f"## {repo} — {len(sel)} файлов "
                  f"({sum(r['bytes'] for r in sel) / 2**20:.1f} МиБ)", "",
                  "| файл | решение | МиБ |", "|---|---|---:|"]
        lines += [f"| `{r['rel']}` | {r['verdict']} | {r['bytes'] / 2**20:.2f} |"
                  for r in sorted(sel, key=lambda x: x["rel"])]
        lines.append("")
    (dest / "ПЛАН-НАПОЛНЕНИЯ.md").write_text("\n".join(lines), encoding="utf-8")
    for repo in sorted(by):
        (dest / repo).mkdir(parents=True, exist_ok=True)
        (dest / repo / ".gitkeep").touch()
    print(f"заготовка записана: {dest}")
    print(f"к переносу сюда: {len(plan)} файлов, "
          f"{sum(r['bytes'] for r in plan) / 2**20:.1f} МиБ")


if __name__ == "__main__":
    main()
