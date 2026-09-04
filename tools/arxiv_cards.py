#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arxiv_cards.py — карточки препринтов arXiv: метаданные наружу, копия внутри.

Задача, которую это решает, — не правовая, а рабочая. Ссылка на arXiv
правильна юридически и негодна практически: обращение к `arxiv.org` из
программы отдаёт 403, токены горят, вопрос остаётся незакрытым.

Условия самого arXiv (прочитаны 2026-09-04, info.arxiv.org/help/api/tou.html
и /help/bulk_data.html) разводят это по трём каналам:

* «Retrieve, store, and use the content of arXiv e-prints **for your own
  personal use, or for research purposes**» — локальная копия разрешена;
* «**Store and serve** arXiv e-prints (PDFs, source files, or other content)
  **from your servers**» — запрещено без разрешения правообладателя;
* описательные **метаданные — CC0 1.0**, ими можно делиться свободно;
* программный доступ идёт на **export.arxiv.org**, а не на arxiv.org;
  темп — не чаще одного запроса в три секунды.

Отсюда устройство: карточка с метаданными (CC0) кладётся в публичную зону,
PDF остаётся в приватной, и модель читает карточку локально — ни 403, ни
лишнего обращения в сеть.

    python3 tools/arxiv_cards.py --workspace /home/user --out .
"""
import argparse
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "http://export.arxiv.org/api/query?id_list={}"
DELAY = 3.0          # условия arXiv: не чаще одного запроса в три секунды
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

CARD = """# {title}

**Карточка препринта arXiv.** Метаданные — CC0 1.0, выложены свободно.
**Самого PDF здесь нет и не будет:** условия arXiv запрещают «store and
serve arXiv e-prints from your servers», но прямо разрешают хранить копию
для собственного чтения и исследования. Копия лежит в приватной зоне.

| | |
|---|---|
| arXiv | [`{aid}`](https://arxiv.org/abs/{aid}) |
| авторы | {authors} |
| опубликовано | {published} |
| обновлено | {updated} |
| разделы | {cats} |
| лицензия препринта | {lic} |
| DOI | {doi} |
| PDF (для человека) | https://arxiv.org/pdf/{aid} |
| программный доступ | `http://export.arxiv.org/api/query?id_list={aid}` |
| копия в приватной зоне | `{repo}/{rel}` |

## Аннотация

{summary}

---

**Почему карточка, а не ссылка.** Обращение к `arxiv.org` из программы
отдаёт 403: для программного доступа arXiv держит отдельный узел
`export.arxiv.org` с темпом не чаще одного запроса в три секунды. Карточка
собрана оттуда один раз и читается локально — вопрос закрывается без
обращения в сеть.

Файл производный: собран `tools/arxiv_cards.py`, руками не правится.
"""


def find_ids(rows):
    """{(repo, rel): arXiv id} — по имени файла и по кэшу улик."""
    rx = re.compile(r"(?<![\w.])(\d{4}\.\d{4,5})(v\d+)?(?![\w])")
    out = {}
    for r in rows:
        m = rx.search(Path(r["rel"]).name)
        if m:
            out[(r["repo"], r["rel"])] = m.group(1)
    return out


def fetch(aid: str):
    with urllib.request.urlopen(API.format(aid), timeout=30) as f:
        root = ET.fromstring(f.read())
    e = root.find("a:entry", NS)
    if e is None:
        return None
    def txt(tag, default="—"):
        n = e.find(tag, NS)
        return (n.text or default).strip() if n is not None else default
    authors = ", ".join((a.find("a:name", NS).text or "").strip()
                        for a in e.findall("a:author", NS)) or "—"
    cats = ", ".join(c.get("term") for c in e.findall("a:category", NS)) or "—"
    return {
        "aid": aid,
        "title": " ".join(txt("a:title").split()),
        "authors": authors,
        "published": txt("a:published"),
        "updated": txt("a:updated"),
        "summary": " ".join(txt("a:summary").split()),
        "cats": cats,
        "doi": txt("arxiv:doi"),
        "lic": "arXiv.org perpetual non-exclusive (если на странице не указано иное)",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="/home/user")
    ap.add_argument("--out", default=str(HERE.parent))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    out = Path(a.out)
    rows = json.loads((out / "rights.json").read_text(encoding="utf-8"))
    ids = find_ids(rows)
    if not ids:
        print("препринтов arXiv в переписи не опознано "
              "(это факт об опознавателе — он смотрит только имя файла)")
        return

    seen = {}
    for (repo, rel), aid in sorted(ids.items()):
        if a.dry_run:
            print(f"[план] карточки/{repo}/{rel}.md ← arXiv {aid}")
            continue
        if aid not in seen:
            seen[aid] = fetch(aid)
            time.sleep(DELAY)
        meta = seen[aid]
        if not meta:
            print(f"[нет данных] {aid} — карточка не собрана")
            continue
        dest = out / "карточки" / repo / (rel + ".md")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(CARD.format(repo=repo, rel=rel, **meta), encoding="utf-8")
        print(f"записано: {dest.relative_to(out)}")


if __name__ == "__main__":
    main()
