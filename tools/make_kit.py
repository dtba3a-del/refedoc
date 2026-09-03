#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_kit.py — из полного набора собрать НЕПОЛНЫЙ комплект для публичной зоны.

Полный набор (нахлёст, координаты, соседи, полный текст) остаётся в
приватной зоне. Наружу уходит комплект, из которого выведен **механизм
сборки**, а не только инструкция:

  * нахлёст не просто убран — между кусками вырезан ЗАЗОР. Соседние куски
    не имеют общих пикселей, и вырезанные полосы не лежат нигде в
    комплекте: этой части произведения в публичной зоне нет;
  * часть кусков удержана (доля задаётся), вразброс, как blacklisting у
    Google Books;
  * имена по хешу содержимого: координат в них нет;
  * публичный указатель перечисляет только опознаватели кусков — ни x, ни
    y, ни соседей;
  * текстовый слой наружу не идёт вовсе: там собирать нечего, копия готова.

    python3 tools/make_kit.py ПОЛНЫЙ_НАБОР/index.json -o kit \\
            --gap 96 --withhold 0.25 --scale 0.5

Печатает **долю площади произведения, оставшуюся в комплекте** — число, по
которому только и можно судить, комплект это или изделие в разобранном виде.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

NOTICE = """# Неполный комплект

**Здесь лежит заведомо неполный набор фрагментов.** Он получен из полного
набора прогоном `tools/make_kit.py` и предназначен только для машинного
разбора.

Что выведено из комплекта:

| | |
|---|---|
| исходный документ | `{name}` |
| страниц в комплекте | {pages} |
| фрагментов оставлено | {kept} из {total} ({kept_pct:.0f} %) |
| зазор между фрагментами | {gap} px — вырезанные полосы отсутствуют |
| масштаб | {scale} от разрешения полного набора |
| **площадь произведения в комплекте** | **{area_pct:.1f} %** |
| текстовый слой | не включён |
| координаты, соседи, порядок | не включены |

Соседние фрагменты **не имеют общих пикселей**, и вырезанные между ними
полосы не содержатся в комплекте ни в каком виде. Полный набор, координаты
и текстовый слой находятся в приватной зоне и сюда не выкладывались.

Объявление о неполноте статуса само по себе не меняет — разбор и источники
в `docs/МАШИНОКОМПЛЕКТ.md` и `docs/ИНДЕКС-В-ПРИВАТЕ.md`. Числа выше
приведены для того, чтобы неполноту можно было **проверить**, а не принять
на слово.

Файл производный: пишется прогоном, руками не правится.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("index", help="index.json полного набора")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--gap", type=int, default=96,
                    help="зазор между кусками в пикселях исходного набора (default: 96)")
    ap.add_argument("--withhold", type=float, default=0.25,
                    help="доля кусков, не попадающих в комплект (default: 0.25)")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="масштаб публикуемых кусков (default: 1.0)")
    ap.add_argument("--seed", type=int, default=20260903)
    a = ap.parse_args()

    ip = Path(a.index)
    index = json.loads(ip.read_text(encoding="utf-8"))
    out_root = Path(a.output)
    out_root.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(a.seed)
    public = {"note": "публичный комплект: неполон намеренно; координат и соседей нет",
              "params": {k: getattr(a, k) for k in ("gap", "withhold", "scale")},
              "docs": []}

    for d in index["docs"]:
        if "error" in d:
            continue
        src_root = ip.parent / d["doc_id"]
        dst_root = out_root / d["doc_id"]
        (dst_root / "tiles").mkdir(parents=True, exist_ok=True)
        kept = total = 0
        area_work = area_kept = 0
        ids = []
        for pg in d["pages"]:
            if not pg["tiles"]:
                continue
            area_work += pg["width"] * pg["height"]
            for t in pg["tiles"]:
                total += 1
                if rnd.random() < a.withhold:
                    continue
                f = src_root / t["file"]
                if not f.exists():
                    continue
                with Image.open(f) as im:
                    w, h = im.size
                    g = a.gap
                    if w - 2 * g < 16 or h - 2 * g < 16:
                        continue                     # кусок вырождается — не берём
                    im = im.crop((g, g, w - g, h - g))
                    if a.scale != 1.0:
                        im = im.resize((max(1, int(im.width * a.scale)),
                                        max(1, int(im.height * a.scale))),
                                       Image.Resampling.LANCZOS)
                    body = im.tobytes()
                    tid = hashlib.sha256(body).hexdigest()[:16]
                    im.save(dst_root / "tiles" / f"{tid}.png", optimize=True)
                # площадь считается по исходной сетке, до масштабирования
                area_kept += (w - 2 * g) * (h - 2 * g)
                kept += 1
                ids.append(tid)

        pages_with_tiles = sum(1 for pg in d["pages"] if pg["tiles"])
        area_pct = 100.0 * area_kept / area_work if area_work else 0.0
        (dst_root / "КОМПЛЕКТ-НЕПОЛОН.md").write_text(NOTICE.format(
            name=Path(d["source"]).name, pages=pages_with_tiles, kept=kept, total=total,
            kept_pct=100.0 * kept / total if total else 0.0, gap=a.gap, scale=a.scale,
            area_pct=area_pct), encoding="utf-8")
        public["docs"].append({"doc_id": d["doc_id"], "tiles": sorted(ids),
                               "kept": kept, "of": total, "area_pct": round(area_pct, 1)})
        print(f"{d['doc_id'][:44]:44s} кусков {kept}/{total}, "
              f"площадь произведения в комплекте {area_pct:.1f} %")

    (out_root / "index-kit.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    tot = sum(x["kept"] for x in public["docs"]); of = sum(x["of"] for x in public["docs"])
    if public["docs"]:
        avg = sum(x["area_pct"] for x in public["docs"]) / len(public["docs"])
        print(f"\nитого кусков {tot} из {of}; площадь произведения в комплекте "
              f"в среднем {avg:.1f} %")
    print(f"публичный указатель без координат: {out_root / 'index-kit.json'}")


if __name__ == "__main__":
    main()
