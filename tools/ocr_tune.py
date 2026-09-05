#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_tune.py — настройка распознавания под документ, а не «как есть».

Положение автора (2026-09-04): tesseract без настроек плодит мусор; если
взглянуть на страницу зрением, можно выбрать параметры, и слой перестанет
быть мусорным. Гарантии это не даёт — снижает выход мусора.

Устройство из трёх шагов:

1. **`profile`** — выбирает пробные страницы (не одну: у многостраничного
   документа параметры на разных страницах различаются), рендерит их и
   снимает механический профиль: режим, размер, плотность краски, оценка
   высоты строки, число колонок, наклон. Профили сравниваются между собой:
   похожи — одна настройка на весь документ, разошлись — группы.

   Одна настройка на 100 страниц или сто настроек — разница велика, и
   решает её именно это сравнение, а не догадка.

2. **зрение** — исполнитель СМОТРИТ пробные страницы и записывает выбор в
   `ocr_settings.json`: `--psm`, `--oem`, язык, предобработка. Машинный
   профиль сам по себе не отличит две колонки от таблицы; взгляд отличает.
   Разрешение пробы берётся достаточным лишь для этого выбора, не выше.

3. **`apply`** — распознаёт с выбранными настройками через сторож живости
   (`proc_watch`) и **меряет долю мусора** в выходе. Число печатается: без
   него «слой распознан» есть утверждение ни о чём.

    python3 tools/ocr_tune.py profile ФАЙЛ -o out
    python3 tools/ocr_tune.py apply   ФАЙЛ -o out --pages 1-20
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proc_watch import run_watched                      # noqa: E402

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("нужны Pillow и numpy")
    sys.exit(1)

Image.MAX_IMAGE_PIXELS = None
ENV = {**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
PROBE_PX = 1600          # достаточно для выбора настроек, не более


def page_count(path: Path) -> int:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True,
                         errors="replace", env=ENV).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 1


def sample_pages(n: int) -> list:
    """
    Пробные страницы. Одна страница о документе не свидетельствует: обложка
    не похожа ни на что. Берём не меньше двух, для длинных — пять.
    """
    if n <= 1:
        return [1]
    if n <= 4:
        return sorted({1, n})
    if n <= 40:
        return sorted({1, n // 3, 2 * n // 3, n})
    return sorted({1, n // 5, 2 * n // 5, 3 * n // 5, 4 * n // 5, n})


def render(path: Path, page: int, dest: Path) -> Path:
    pref = dest / f"p{page:04d}"
    subprocess.run(["pdftoppm", "-png", "-scale-to", str(PROBE_PX),
                    "-f", str(page), "-l", str(page), "-singlefile",
                    str(path), str(pref)], check=True, capture_output=True, env=ENV)
    return pref.with_suffix(".png")


def traits(png: Path) -> dict:
    """Механический профиль страницы: то, что видно без понимания смысла."""
    with Image.open(png) as im:
        g = np.asarray(im.convert("L"), dtype=np.uint8)
    h, w = g.shape
    ink = (g < 128)
    density = float(ink.mean())
    rows = ink.mean(axis=1)
    thr = max(0.002, rows.mean() * 0.35)
    lines, run = [], 0
    for v in rows:
        if v > thr:
            run += 1
        elif run:
            lines.append(run); run = 0
    if run:
        lines.append(run)
    line_h = float(np.median(lines)) if lines else 0.0
    cols = ink.mean(axis=0)
    gap = cols < max(0.001, cols.mean() * 0.15)
    gaps, run = [], 0
    for v in gap:
        if v:
            run += 1
        elif run:
            gaps.append(run); run = 0
    wide = [x for x in gaps if x > w * 0.04]
    return {"w": w, "h": h, "плотность краски": round(density, 4),
            "высота строки": round(line_h, 1), "строк": len(lines),
            "широких пробелов по вертикали": len(wide),
            "колонок (оценка)": 1 + sum(1 for x in wide if x > w * 0.06)}


def similar(a: dict, b: dict) -> bool:
    """Похожи ли параметры двух страниц настолько, что настройка одна."""
    if a["колонок (оценка)"] != b["колонок (оценка)"]:
        return False
    if abs(a["плотность краски"] - b["плотность краски"]) > 0.05:
        return False
    ha, hb = a["высота строки"], b["высота строки"]
    if max(ha, hb) > 0 and abs(ha - hb) / max(ha, hb) > 0.4:
        return False
    return True


GARBAGE_TOKEN = re.compile(r"[^\W\d_]{2,}", re.U)


def garbage_share(text: str) -> dict:
    """
    Доля мусора в распознанном. Меряется, а не предполагается: слова из
    одного алфавита длиной 3+, доля знаков вне алфавита и цифр, доля
    одиночных букв. Число не доказывает годность, но показывает провал.
    """
    if not text.strip():
        return {"знаков": 0, "мусор": None, "почему": "пусто"}
    toks = GARBAGE_TOKEN.findall(text)
    if not toks:
        return {"знаков": len(text), "мусор": 1.0, "почему": "нет ни одного слова"}
    def coherent(t):
        cyr = sum(1 for c in t if "А" <= c <= "я" or c in "Ёё")
        lat = sum(1 for c in t if "A" <= c <= "z")
        return max(cyr, lat) / len(t) > 0.9
    good = [t for t in toks if len(t) >= 3 and coherent(t)]
    junk_chars = sum(1 for c in text if not (c.isalnum() or c.isspace() or c in ".,:;()[]{}«»\"'—–-+±°%/=*№#"))
    return {"знаков": len(text), "слов": len(toks),
            "мусор": round(1 - len(good) / len(toks), 3),
            "знаков вне алфавита, доля": round(junk_chars / max(1, len(text)), 3)}




def split_spread(png: Path):
    """
    Разворот делится по корешку ДО распознавания.

    Замер 2026-09-04 (Е7-12, альбом ТО): страница есть разворот двух книжных
    страниц с корешком посередине. Механический профиль видит «две колонки»,
    и никакой `--psm` тут не помогает: распознаватель тянет строку через
    корешок и склеивает текст двух страниц. Взгляд отличает разворот от
    колонок — механика нет.

    Корешок ищется как самый светлый вертикальный столбец в средней трети.
    """
    with Image.open(png) as im:
        g = np.asarray(im.convert("L"), dtype=np.uint8)
        w = g.shape[1]
        band = slice(int(w * 0.4), int(w * 0.6))
        ink = (g < 128).mean(axis=0)
        mid = int(w * 0.4) + int(np.argmin(ink[band]))
        left = im.crop((0, 0, mid, im.height))
        right = im.crop((mid, 0, im.width, im.height))
        a = png.with_name(png.stem + "_л.png"); b = png.with_name(png.stem + "_п.png")
        left.save(a); right.save(b)
    return [a, b]

def cmd_profile(a):
    src = Path(a.file)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    n = page_count(src)
    pages = sample_pages(n)
    prof = {"файл": str(src), "страниц": n, "пробные страницы": pages, "профили": {}}
    with tempfile.TemporaryDirectory() as td:
        for p in pages:
            png = render(src, p, Path(td))
            dest = out / f"проба-{p:04d}.png"
            Image.open(png).save(dest)
            prof["профили"][str(p)] = traits(dest)
            prof["профили"][str(p)]["проба"] = dest.name
    ps = list(prof["профили"].values())
    groups = []
    for i, t in enumerate(ps):
        for g in groups:
            if similar(ps[g[0]], t):
                g.append(i); break
        else:
            groups.append([i])
    prof["групп настроек"] = len(groups)
    prof["вывод"] = ("страницы однородны — настройка одна на весь документ"
                     if len(groups) == 1 else
                     f"страницы разошлись на {len(groups)} группы — настроек столько же")
    (out / "ocr_profile.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps({k: v for k, v in prof.items() if k != "профили"},
                     ensure_ascii=False, indent=2))
    for p, t in prof["профили"].items():
        print(f"  стр.{p}: {t['w']}×{t['h']}, краска {t['плотность краски']}, "
              f"строк {t['строк']}, высота строки {t['высота строки']}, "
              f"колонок {t['колонок (оценка)']} → {t['проба']}")


def cmd_apply(a):
    src = Path(a.file)
    out = Path(a.output)
    sp = out / "ocr_settings.json"
    if not sp.is_file():
        raise SystemExit(f"нет {sp}: настройки выбираются ВЗГЛЯДОМ по пробам "
                         f"(`profile`), а не подставляются по умолчанию")
    st = json.loads(sp.read_text(encoding="utf-8"))
    pages = range(1, page_count(src) + 1)
    if a.pages:
        lo, _, hi = a.pages.partition("-")
        pages = range(int(lo), int(hi or lo) + 1)
    total, res = "", []
    with tempfile.TemporaryDirectory() as td:
        for p in pages:
            pref = Path(td) / f"p{p}"
            subprocess.run(["pdftoppm", "-png", "-r", str(st.get("dpi", 300)),
                            "-f", str(p), "-l", str(p), "-singlefile",
                            str(src), str(pref)], check=True, capture_output=True, env=ENV)
            imgs = (split_spread(pref.with_suffix(".png"))
                    if st.get("разворот") else [pref.with_suffix(".png")])
            text = ""
            for img in imgs:
                cmd = ["tesseract", str(img), "stdout",
                       "-l", st.get("lang", "rus+eng"),
                       "--psm", str(st.get("psm", 3)), "--oem", str(st.get("oem", 1))]
                for k, v in (st.get("config") or {}).items():
                    cmd += ["-c", f"{k}={v}"]
                code, part = run_watched(cmd, stall=st.get("stall", 60), env=ENV)
                text += part + "\n"
            res.append({"стр": p, "код": code, **garbage_share(text)})
            total += text + "\n"
    (out / "ocr.txt").write_text(total, encoding="utf-8")
    ok = [r for r in res if r.get("мусор") is not None]
    avg = sum(r["мусор"] for r in ok) / len(ok) if ok else None
    print(f"страниц {len(res)}, знаков {len(total)}, "
          f"средняя доля мусора {avg if avg is None else round(avg, 3)}")
    for r in res[:10]:
        print(f"  стр.{r['стр']}: код {r['код']}, знаков {r['знаков']}, мусор {r.get('мусор')}")




SWEEP = [
    ("psm3, без резки", dict(psm=3, split=False, lang="rus+eng", cfg={})),
    ("psm6, резка", dict(psm=6, split=True, lang="rus+eng", cfg={})),
    ("psm4, резка", dict(psm=4, split=True, lang="rus+eng", cfg={})),
    ("psm6, резка, один язык", dict(psm=6, split=True, lang="rus", cfg={})),
    ("psm4, резка, один язык", dict(psm=4, split=True, lang="rus", cfg={})),
    ("psm6, резка, один язык, пробелы", dict(psm=6, split=True, lang="rus",
                                            cfg={"preserve_interword_spaces": "1"})),
]


def cmd_sweep(a):
    """
    Перебор настроек с замером доли мусора на одной пробной странице.

    Выбор настроек НЕ объявляется, а меряется. Замер 2026-09-05 на альбоме
    ТО Е7-12, стр. 51: разброс 0.209…0.271 при шести настройках — то есть
    настройка меняет выход мусора в полтора раза. И он поправил вывод,
    сделанный зрением: `rus+eng` казался верным (в тексте есть Cx, kHz, pF),
    а на деле движок подставляет латинские двойники кириллицы, и один язык
    даёт меньше мусора.
    """
    src = Path(a.file)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    page = a.page or (page_count(src) // 2 or 1)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        pref = Path(td) / "p"
        subprocess.run(["pdftoppm", "-png", "-r", str(a.dpi), "-f", str(page), "-l", str(page),
                        "-singlefile", str(src), str(pref)], check=True,
                       capture_output=True, env=ENV)
        png = pref.with_suffix(".png")
        halves = split_spread(png)
        for name, v in SWEEP:
            imgs = halves if v["split"] else [png]
            text = ""
            for im in imgs:
                cmd = ["tesseract", str(im), "stdout", "-l", v["lang"],
                       "--psm", str(v["psm"]), "--oem", "1"]
                for k, val in v["cfg"].items():
                    cmd += ["-c", f"{k}={val}"]
                _, t = run_watched(cmd, stall=a.stall, env=ENV)
                text += t + "\n"
            g = garbage_share(text)
            rows.append({"настройка": name, **v, "cfg": v["cfg"], **g})
            print(f"  {name:36s} знаков {g['знаков']:6d}  мусор {g['мусор']}")
    rows.sort(key=lambda r: (r["мусор"], -r["знаков"]))
    (out / "ocr_sweep.json").write_text(json.dumps(
        {"файл": str(src), "страница": page, "замеры": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    b = rows[0]
    print(f"\nнаименьший мусор: {b['настройка']} — {b['мусор']} при {b['знаков']} знаках")
    print("Выбор за исполнителем: меньше мусора против больше текста — цель решает, "
          "а не число само по себе.")

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("profile"); p1.add_argument("file"); p1.add_argument("-o", "--output", required=True)
    p1.set_defaults(func=cmd_profile)
    p3 = sub.add_parser("sweep", help="перебор настроек с замером доли мусора")
    p3.add_argument("file"); p3.add_argument("-o", "--output", required=True)
    p3.add_argument("--page", type=int, default=None); p3.add_argument("--dpi", type=int, default=300)
    p3.add_argument("--stall", type=float, default=90.0); p3.set_defaults(func=cmd_sweep)

    p2 = sub.add_parser("apply"); p2.add_argument("file"); p2.add_argument("-o", "--output", required=True)
    p2.add_argument("--pages", default=None); p2.set_defaults(func=cmd_apply)
    a = ap.parse_args(); a.func(a)


if __name__ == "__main__":
    main()
