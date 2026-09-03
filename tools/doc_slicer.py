#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc_slicer.py — PDF/DjVu → куски, пригодные к чтению по индексу.

Развитие шаблона `scheme_slicer.py` (нарезка растра с нахлёстом) на документы:
перед нарезкой добавлены определитель типа и разные извлекатели, после —
индекс, по которому кусок достаётся адресно, без чтения целого документа.

Слои на выходе:
  text/     — текстовый слой постранично (если он в документе есть);
  chunks/   — тот же текст, нарезанный на куски ~N символов с нахлёстом;
  thumbs/   — превью страницы целиком (обзор);
  tiles/    — фрагменты страницы с нахлёстом (чтение мелких надписей);
  index.json — дерево: документ → страницы → куски и фрагменты.

Страницы рендерятся в растр только там, где текстового слоя нет или он
беден (сканы, схемы). Порог задаётся --min-chars.

    python3 tools/doc_slicer.py slice ФАЙЛ... -o out [--dpi 300] [--tile-size 1024]
    python3 tools/doc_slicer.py get out/index.json --doc ИМЯ --page 12
    python3 tools/doc_slicer.py get out/index.json --doc ИМЯ --page 12 --tile 3
    python3 tools/doc_slicer.py stats out/index.json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from math import ceil
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Ошибка: требуется Pillow. Установите: pip install Pillow")
    sys.exit(1)

Image.MAX_IMAGE_PIXELS = None

# djvulibre в локали POSIX не открывает файлы с не-ASCII именами: имя приходит
# в программу пустой строкой. Замер 2026-09-03: `djvused` на «Шноль ....djvu»
# печатал справку вместо числа страниц, с LC_ALL=C.UTF-8 — «133».
ENV = {**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}

PDF_EXT = {".pdf"}
DJVU_EXT = {".djvu", ".djv"}


# ---------------------------------------------------------------- определитель

def detect(path: Path) -> str:
    """Тип документа по сигнатуре, а не по расширению: расширение лжёт."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"%PDF"):
        return "pdf"
    if head[:4] == b"AT&T":
        return "djvu"
    ext = path.suffix.lower()
    if ext in PDF_EXT:
        return "pdf"
    if ext in DJVU_EXT:
        return "djvu"
    return "unknown"


def need(binary: str):
    if shutil.which(binary) is None:
        raise RuntimeError(f"нет внешней программы {binary!r} "
                           f"(pdf: poppler-utils, djvu: djvulibre-bin)")


def page_count(path: Path, kind: str) -> int:
    if kind == "pdf":
        need("pdfinfo")
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True,
                             errors="replace", env=ENV).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        if not m:
            raise RuntimeError(f"pdfinfo не назвал число страниц: {path.name}")
        return int(m.group(1))
    if kind == "djvu":
        need("djvused")
        out = subprocess.run(["djvused", str(path), "-e", "n"], capture_output=True,
                             text=True, errors="replace", env=ENV).stdout
        return int(out.strip().splitlines()[0])
    raise RuntimeError(f"неизвестный тип: {path}")


# ---------------------------------------------------------------- извлекатели

def page_text(path: Path, kind: str, page: int) -> str:
    """Текстовый слой одной страницы. Пусто — не ошибка, а факт о документе."""
    try:
        if kind == "pdf":
            need("pdftotext")
            r = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page),
                                str(path), "-"], capture_output=True, text=True, errors="replace", env=ENV)
            return r.stdout
        if kind == "djvu":
            if shutil.which("djvutxt") is None:
                return ""
            r = subprocess.run(["djvutxt", f"--page={page}", str(path)],
                               capture_output=True, text=True, errors="replace", env=ENV)
            return r.stdout
    except Exception:
        return ""
    return ""


def render_page(path: Path, kind: str, page: int, dpi: int, dest: Path) -> Path:
    """Растр одной страницы в PNG. Возвращает путь к файлу."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if kind == "pdf":
        need("pdftoppm")
        prefix = dest.with_suffix("")
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
                        "-singlefile", str(path), str(prefix)], check=True,
                       capture_output=True, env=ENV)
        produced = prefix.with_suffix(".png")
    else:
        need("ddjvu")
        produced = dest.with_suffix(".png")
        subprocess.run(["ddjvu", "-format=pnm", f"-page={page}", f"-scale={dpi}",
                        str(path), str(produced.with_suffix(".pnm"))], check=True,
                       capture_output=True, env=ENV)
        with Image.open(produced.with_suffix(".pnm")) as im:
            im.save(produced)
        produced.with_suffix(".pnm").unlink(missing_ok=True)
    return produced


# ---------------------------------------------------------------- сетки (шаблон)

def compute_overlap_grid(width: int, height: int, tile_size: int, overlap: int):
    """Из scheme_slicer.py: крайние тайлы сдвигаются к границе, ничего не теряется."""
    step = tile_size - overlap

    def positions(total: int):
        if total <= tile_size:
            return [(0, total)]
        res, pos = [], 0
        while pos + tile_size < total:
            res.append((pos, tile_size))
            pos += step
        last = total - tile_size
        if not res or last > res[-1][0]:
            res.append((last, tile_size))
        return res

    xs, ys = positions(width), positions(height)
    return [[(x, y, w, h) for x, w in xs] for y, h in ys]


def chunk_text(text: str, size: int, overlap: int):
    """Нарезка текста по границам строк, с нахлёстом: фраза не рвётся между кусками."""
    if not text.strip():
        return []
    lines = text.splitlines(keepends=True)
    chunks, cur, cur_len, start_line = [], [], 0, 0
    for i, ln in enumerate(lines):
        cur.append(ln)
        cur_len += len(ln)
        if cur_len >= size:
            chunks.append({"text": "".join(cur), "line_from": start_line, "line_to": i})
            back, j = 0, len(cur)
            while j > 0 and back < overlap:
                j -= 1
                back += len(cur[j])
            cur = cur[j:]
            cur_len = sum(len(x) for x in cur)
            start_line = i - (len(cur) - 1)
    if cur and "".join(cur).strip():
        chunks.append({"text": "".join(cur), "line_from": start_line, "line_to": len(lines) - 1})
    return chunks


# ---------------------------------------------------------------- один документ

def save_thumb(img: Image.Image, max_size: int, stem: Path):
    """
    Превью — обзор, а не документ, поэтому кодировка выбирается замером, а не
    догадкой: пробуем несколько и оставляем самое лёгкое.

    Замер 2026-09-03 на битональной странице DjVu (3185×2538, страница целиком
    187 КиБ): PNG «L» — 321 КиБ (превью тяжелее страницы!), PNG P16 — 187 КиБ,
    JPEG q75 — 253 КиБ, PNG 1 бит — 38 КиБ. Разница пятикратная, и знак у неё
    меняется: без выбора превью перестаёт быть дешевле целого.
    """
    base = img.convert("L") if img.mode == "1" else (
        img if img.mode in ("RGB", "L") else img.convert("RGB"))
    th = base.copy()
    th.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    cands = [("png", lambda p: th.save(p, optimize=True), th.mode)]
    if img.mode == "1":
        cands.append(("png", lambda p: th.convert("1").save(p, optimize=True), "1"))
        cands.append(("png", lambda p: th.convert("P", palette=Image.ADAPTIVE,
                                                 colors=16).save(p, optimize=True), "P16"))
    else:
        cands.append(("jpg", lambda p: th.convert("RGB").save(p, quality=85,
                                                              optimize=True), "JPEG85"))
    best = None
    tmp = []
    for i, (ext, save, mode) in enumerate(cands):
        cand = stem.with_name(f"{stem.name}__c{i}.{ext}")
        try:
            save(cand)
        except OSError:
            continue
        tmp.append(cand)
        size = cand.stat().st_size
        if best is None or size < best[0]:
            best = (size, cand, ext, mode)
    _, cand, ext, mode = best
    final = stem.with_suffix(f".{ext}")
    if final.exists():
        final.unlink()
    cand.rename(final)
    for t in tmp:
        if t != cand and t.exists():
            t.unlink()
    return final, mode


def slice_page(job):
    """Обработка одной страницы. Выполняется в отдельном процессе."""
    (src, kind, page, out_doc, dpi, tile_size, overlap, thumb_size,
     min_chars, chunk_size, chunk_overlap, force_render) = job
    src, out_doc = Path(src), Path(out_doc)
    rec = {"page": page, "chars": 0, "text": None, "chunks": [], "thumb": None,
           "tiles": [], "rendered": False, "width": None, "height": None}

    txt = page_text(src, kind, page)
    rec["chars"] = len(txt.strip())
    if rec["chars"] > 0:
        tdir = out_doc / "text"
        tdir.mkdir(parents=True, exist_ok=True)
        tp = tdir / f"p{page:04d}.txt"
        tp.write_text(txt, encoding="utf-8")
        rec["text"] = tp.name
        cdir = out_doc / "chunks" / f"p{page:04d}"
        for i, ch in enumerate(chunk_text(txt, chunk_size, chunk_overlap)):
            cdir.mkdir(parents=True, exist_ok=True)
            cp = cdir / f"c{i:03d}.txt"
            cp.write_text(ch["text"], encoding="utf-8")
            rec["chunks"].append({"index": i, "file": f"chunks/p{page:04d}/{cp.name}",
                                 "chars": len(ch["text"]),
                                 "line_from": ch["line_from"], "line_to": ch["line_to"]})

    if not (force_render or rec["chars"] < min_chars):
        return rec

    with tempfile.TemporaryDirectory() as td:
        img_path = render_page(src, kind, page, dpi, Path(td) / f"p{page:04d}.png")
        with Image.open(img_path) as img:
            # Режим страницы НЕ трогаем: битональный скан режется и хранится
            # битональным. Замер 2026-09-03 (DjVu, стр. 22, 300 dpi):
            # принудительный convert("RGB") раздувал превью до 392 % от веса
            # страницы целиком — «кусок» выходил дороже оригинала.
            img.load()
            w, h = img.size
            rec.update(rendered=True, width=w, height=h)

            thd = out_doc / "thumbs"
            thd.mkdir(parents=True, exist_ok=True)
            tp, tmode = save_thumb(img, thumb_size, thd / f"p{page:04d}")
            rec["thumb"] = f"thumbs/{tp.name}"
            rec["thumb_mode"] = tmode
            rec["thumb_bytes"] = tp.stat().st_size

            grid = compute_overlap_grid(w, h, tile_size, overlap)
            rows, cols = len(grid), len(grid[0]) if grid else 0
            tdir = out_doc / "tiles" / f"p{page:04d}"
            tdir.mkdir(parents=True, exist_ok=True)
            for r in range(rows):
                for c in range(cols):
                    x, y, tw, thh = grid[r][c]
                    idx = r * cols + c
                    name = f"t{idx:03d}_x{x}_y{y}.png"
                    img.crop((x, y, x + tw, y + thh)).save(tdir / name, optimize=True)
                    neigh = {}
                    if r > 0:
                        neigh["top"] = (r - 1) * cols + c
                    if r < rows - 1:
                        neigh["bottom"] = (r + 1) * cols + c
                    if c > 0:
                        neigh["left"] = r * cols + (c - 1)
                    if c < cols - 1:
                        neigh["right"] = r * cols + (c + 1)
                    rec["tiles"].append({
                        "index": idx, "row": r, "col": c,
                        "file": f"tiles/p{page:04d}/{name}",
                        "x": x, "y": y, "w": tw, "h": thh,
                        "overlap_pixels": {
                            "left": overlap if x > 0 else 0, "top": overlap if y > 0 else 0,
                            "right": overlap if (x + tw) < w else 0,
                            "bottom": overlap if (y + thh) < h else 0},
                        "neighbors": neigh})
    return rec


def slice_doc(src: Path, out_root: Path, a) -> dict:
    kind = detect(src)
    if kind == "unknown":
        return {"source": str(src), "error": "тип не определён"}
    t0 = time.time()
    n = page_count(src, kind)
    pages = range(1, n + 1) if not a.pages else parse_pages(a.pages, n)
    doc_id = re.sub(r"[^\w.\-()Ѐ-ӿ ]+", "_", src.stem)[:120]
    out_doc = out_root / doc_id
    out_doc.mkdir(parents=True, exist_ok=True)

    jobs = [(str(src), kind, p, str(out_doc), a.dpi, a.tile_size, a.overlap, a.thumb_size,
             a.min_chars, a.chunk_size, a.chunk_overlap, a.render_all) for p in pages]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        recs = list(ex.map(slice_page, jobs))

    dt = time.time() - t0
    rendered = sum(1 for r in recs if r["rendered"])
    return {
        "doc_id": doc_id,
        "source": str(src),
        "source_bytes": src.stat().st_size,
        "kind": kind,
        "pages_total": n,
        "pages_processed": len(recs),
        "pages_with_text": sum(1 for r in recs if r["chars"] > 0),
        "pages_rendered": rendered,
        "chars_total": sum(r["chars"] for r in recs),
        "tiles_total": sum(len(r["tiles"]) for r in recs),
        "chunks_total": sum(len(r["chunks"]) for r in recs),
        "seconds": round(dt, 1),
        "pages": recs,
    }


def parse_pages(spec: str, n: int):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a_, b_ = part.split("-", 1)
            out.extend(range(max(1, int(a_)), min(n, int(b_)) + 1))
        elif part:
            v = int(part)
            if 1 <= v <= n:
                out.append(v)
    return sorted(set(out))


# ---------------------------------------------------------------- команды

def cmd_slice(a):
    out_root = Path(a.output)
    out_root.mkdir(parents=True, exist_ok=True)
    docs = []
    for f in a.files:
        p = Path(f)
        print(f"→ {p.name} ({p.stat().st_size / 2**20:.1f} МиБ)")
        d = slice_doc(p, out_root, a)
        docs.append(d)
        if "error" in d:
            print(f"   ОШИБКА: {d['error']}")
            continue
        print(f"   страниц {d['pages_processed']}/{d['pages_total']}, "
              f"с текстом {d['pages_with_text']}, растром {d['pages_rendered']}, "
              f"фрагментов {d['tiles_total']}, кусков текста {d['chunks_total']}, "
              f"{d['seconds']} с")
    index = {"params": {k: v for k, v in vars(a).items() if k not in ("func", "files")},
             "docs": docs}
    ip = out_root / "index.json"
    ip.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nиндекс: {ip}")


def _find_doc(index, name):
    docs = index["docs"]
    if name is None:
        if len(docs) == 1:
            return docs[0]
        raise SystemExit("в индексе несколько документов — укажите --doc")
    for d in docs:
        if d["doc_id"] == name or name.lower() in d["doc_id"].lower():
            return d
    raise SystemExit(f"документ {name!r} в индексе не найден")


def cmd_get(a):
    ip = Path(a.index)
    index = json.loads(ip.read_text(encoding="utf-8"))
    d = _find_doc(index, a.doc)
    root = ip.parent / d["doc_id"]
    page = next((p for p in d["pages"] if p["page"] == a.page), None)
    if page is None:
        raise SystemExit(f"страницы {a.page} в индексе нет")
    if a.tile is not None:
        t = next((t for t in page["tiles"] if t["index"] == a.tile), None)
        if t is None:
            raise SystemExit(f"фрагмента {a.tile} на странице {a.page} нет "
                             f"(всего {len(page['tiles'])})")
        print(root / t["file"])
        return
    if a.thumb:
        if not page["thumb"]:
            raise SystemExit("превью этой страницы нет: страница не рендерилась")
        print(root / page["thumb"])
        return
    if a.chunk is not None:
        c = next((c for c in page["chunks"] if c["index"] == a.chunk), None)
        if c is None:
            raise SystemExit(f"куска {a.chunk} на странице {a.page} нет "
                             f"(всего {len(page['chunks'])})")
        sys.stdout.write((root / c["file"]).read_text(encoding="utf-8"))
        return
    if page["text"]:
        sys.stdout.write((root / "text" / page["text"]).read_text(encoding="utf-8"))
    else:
        print(f"[текстового слоя нет; страница в растре: "
              f"{len(page['tiles'])} фрагментов, превью {page['thumb']}]")


def cmd_stats(a):
    ip = Path(a.index)
    index = json.loads(ip.read_text(encoding="utf-8"))
    for d in index["docs"]:
        if "error" in d:
            print(f"{d['source']}: ОШИБКА {d['error']}")
            continue
        root = ip.parent / d["doc_id"]
        out_bytes = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
        cov = 100.0 * d["pages_with_text"] / max(1, d["pages_processed"])
        print(f"{d['doc_id']}")
        print(f"  источник     : {d['source_bytes'] / 2**20:.2f} МиБ, {d['kind']}, "
              f"{d['pages_total']} страниц")
        print(f"  разобрано    : {d['pages_processed']} страниц за {d['seconds']} с")
        print(f"  текстовый слой: {d['pages_with_text']} страниц ({cov:.0f} %), "
              f"{d['chars_total']} символов")
        print(f"  растр        : {d['pages_rendered']} страниц, {d['tiles_total']} фрагментов")
        print(f"  куски текста : {d['chunks_total']}")
        print(f"  на диске     : {out_bytes / 2**20:.2f} МиБ "
              f"(×{out_bytes / max(1, d['source_bytes']):.1f} к источнику)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("slice", help="нарезать документы")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output", default="./sliced_output")
    s.add_argument("--pages", default=None, help="страницы: 1-10,15 (по умолчанию все)")
    s.add_argument("--dpi", type=int, default=300)
    s.add_argument("--tile-size", type=int, default=1024)
    s.add_argument("--overlap", type=int, default=64)
    s.add_argument("--thumb-size", type=int, default=1024)
    s.add_argument("--min-chars", type=int, default=200,
                   help="меньше символов на странице — считать страницу картинкой (default: 200)")
    s.add_argument("--render-all", action="store_true", help="рендерить растр даже при богатом тексте")
    s.add_argument("--chunk-size", type=int, default=4000)
    s.add_argument("--chunk-overlap", type=int, default=400)
    s.add_argument("--jobs", type=int, default=8)
    s.set_defaults(func=cmd_slice)

    g = sub.add_parser("get", help="достать кусок по индексу")
    g.add_argument("index")
    g.add_argument("--doc", default=None)
    g.add_argument("--page", type=int, required=True)
    g.add_argument("--tile", type=int, default=None)
    g.add_argument("--chunk", type=int, default=None)
    g.add_argument("--thumb", action="store_true")
    g.set_defaults(func=cmd_get)

    t = sub.add_parser("stats", help="замер по индексу")
    t.add_argument("index")
    t.set_defaults(func=cmd_stats)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
