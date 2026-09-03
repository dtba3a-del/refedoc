#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_repos.py — уведомление репозиториям-источникам об изменении порядка.

Когда справочный материал уезжает, исполнитель в репозитории-источнике
теряет опору: файл был — файла нет. Уведомление кладётся **в лоток
репозитория** (`inbox/`), если у него нет дома, и обязано отвечать на три
вопроса без домысла: что изменилось, где теперь искать, что делать сейчас.

Файл производный: собирается прогоном из `inventory.json` и `rights.json`,
руками не правится. **Состояние переезда объявляется числом и на дату** —
уведомление, отставшее от действительности, хуже его отсутствия.

    python3 tools/notify_repos.py --workspace /home/user --dry-run
    python3 tools/notify_repos.py --workspace /home/user
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = "https://github.com/dtba3a-del/refedoc/blob/main"
RAW = "https://github.com/dtba3a-del/refedoc/raw/main"

TPL = """# Порядок изменился: справочный материал переезжает в `refedoc`

**Уведомление для исполнителя этого репозитория.** Прочитать до того, как
искать справочный PDF или DjVu на прежнем месте.

Дата уведомления: {date}. Состояние на эту дату — в §4; **перенос ещё не
выполнен**, если там не сказано иное.

## 1. Что изменилось

Крупные справочные документы (PDF, DjVu) выносятся из репозиториев профиля
в отдельный **публичный** репозиторий
[`refedoc`](https://github.com/dtba3a-del/refedoc). Причина: справочник
тяжёл, меняется редко, а тянулся при каждом клоне.

Правило автора от 2026-09-03: **что допустимо хранить публично — хранится
публично.** Обратная сторона: **недопустимое не уезжает никак** и остаётся
здесь, в приватной зоне. Поэтому переезжает не всё.

## 2. Где теперь искать

```
refedoc/{repo}/<тот же путь, что был здесь>
```

Структура каталогов сохраняется, имена файлов не меняются. Прямая ссылка на
файл: `{raw}/{repo}/<путь>`.

На прежнем месте остаётся указатель:

* `<имя файла>.где.md` — рядом с тем местом, где файл лежал: что это было,
  вес, sha256, куда переехало, чем скачать;
* `КУДА-ПЕРЕЕХАЛО.md` — один на каталог, со списком.

Указатели собираются `tools/make_pointer.py` в `refedoc` и руками не
правятся.

## 3. Что делать с большим документом

Читать целиком его не нужно и часто нельзя. В `refedoc` есть нарезка:

```bash
python3 tools/doc_slicer.py slice ФАЙЛ -o out --max-px 6000 --jobs 4
python3 tools/doc_slicer.py stats out/index.json
python3 tools/doc_slicer.py get out/index.json --page 7 --thumb     # обзор
python3 tools/doc_slicer.py get out/index.json --page 7 --tile 45   # деталь
python3 tools/doc_slicer.py get out/index.json --page 7             # текст
```

Замер на листе А2: обзор с деталью стоит **4 %** веса страницы, и надписи
читаются. Разрешение задавать не нужно — растровая страница рендерится в
собственной сетке исходника.

Полные наборы кусков и индексы остаются в **приватной** зоне: место кусков
безразлично для чтения и решающе для права
([`docs/ИНДЕКС-В-ПРИВАТЕ.md`]({web}/docs/%D0%98%D0%9D%D0%94%D0%95%D0%9A%D0%A1-%D0%92-%D0%9F%D0%A0%D0%98%D0%92%D0%90%D0%A2%D0%95.md)).

## 4. Состояние по этому репозиторию на {date}

| | |
|---|---|
| справочных PDF/DjVu найдено | {found} |
| отнесено к переносу | **{taken}** ({mib:.1f} МиБ) |
| остаётся на месте по правилам отбора | {skipped} |
| **перенесено фактически** | **{moved}** |
| указателей проставлено | {pointers} |

Разбор правового статуса (черновой, `refedoc/ПРАВА-ПОФАЙЛОВО.md`):

| решение | файлов этого репозитория |
|---|---:|
{rights_rows}

Разбор ведётся по уликам в самих файлах; **«не определён» означает «не
разобран», а не «свободен»**. Пока файл не получил решения «публично», в
публичную зону он не едет: это проверяет крючок `guard.py` в `refedoc` и
**останавливает коммит**, а не предупреждает.

## 5. Чего делать не нужно

* Не искать переехавший файл по сети вслепую — сначала указатель рядом с
  прежним местом, затем `refedoc/INVENTORY.md`.
* Не копировать материал из этого репозитория в публичный вручную: решение
  о допустимости принимается разбором, а не на глаз.
* Не класть в `refedoc` стенограммы, журналы сессий и содержимое лотков
  этого репозитория — там публичная зона, и крючок это запрещает.

## 6. Если уведомление разошлось с действительностью

Оно производное. Пересобрать:

```bash
python3 tools/refdoc_inventory.py --workspace .. --out . --hash --signature
python3 tools/rights_classify.py --workspace .. --out .
python3 tools/notify_repos.py --workspace ..
```

Расхождение уведомления с действительностью — ошибка прогона, а не повод
править файл руками.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="/home/user")
    ap.add_argument("--refedoc", default=str(HERE.parent))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = Path(a.refedoc)
    inv = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    rules = {r["repo"]: r for r in json.loads(
        (HERE / "refdoc_rules.json").read_text(encoding="utf-8"))["repos"]}
    rights_path = root / "rights.json"
    rights = json.loads(rights_path.read_text(encoding="utf-8")) if rights_path.is_file() else []
    ws = Path(a.workspace)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for r in inv["repos"]:
        repo = r["repo"]
        clone = ws / rules[repo]["clone"]
        if not clone.is_dir():
            print(f"[пропуск] нет клона {clone}")
            continue
        # факт, а не намерение: что уже лежит в публичной зоне и сколько указателей
        moved = sum(1 for x in r["taken"] if (root / repo / x["rel"]).is_file())
        pointers = sum(1 for x in r["taken"] if (clone / (x["rel"] + ".где.md")).is_file())
        cnt = Counter(x["verdict"] for x in rights if x["repo"] == repo)
        rows = "\n".join(f"| {v} | {cnt[v]} |" for v in
                         ("публично", "спорно", "непублично", "не определён") if cnt[v]) \
            or "| разбор не запускался | — |"
        body = TPL.format(date=date, repo=repo, raw=RAW, web=WEB,
                          found=r["total"], taken=len(r["taken"]),
                          mib=sum(x["bytes"] for x in r["taken"]) / 2**20,
                          skipped=len(r["skipped"]), moved=moved, pointers=pointers,
                          rights_rows=rows)
        box = clone / "inbox"
        dest = box / f"УВЕДОМЛЕНИЕ-refedoc-{date}.md"
        if a.dry_run:
            print(f"[план] {dest}  (перенесено {moved}/{len(r['taken'])}, "
                  f"указателей {pointers})")
            continue
        box.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
        print(f"записано: {dest}  (перенесено {moved}/{len(r['taken'])}, "
              f"указателей {pointers})")


if __name__ == "__main__":
    main()
