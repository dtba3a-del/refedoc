#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scheme_slicer.py
Нарезка больших схем/чертёжей с overlap, создание превью и индексного дерева.

Использование:
    python scheme_slicer.py /path/to/images --output ./out --tile-size 1024 --overlap 64 --clean
"""

import os
import sys
import json
import argparse
from pathlib import Path
from math import ceil

try:
    from PIL import Image
except ImportError:
    print("Ошибка: требуется Pillow. Установите: pip install Pillow")
    sys.exit(1)

Image.MAX_IMAGE_PIXELS = None  # снять лимит на огромные изображения


def make_thumb(img: Image.Image, max_size: int) -> Image.Image:
    """Пропорциональное уменьшение до max_size по длинной стороне."""
    thumb = img.copy()
    thumb.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return thumb


def compute_overlap_grid(width: int, height: int, tile_size: int, overlap: int):
    """
    Возвращает двумерный список [row][col] = (x, y, w, h).
    Крайние тайлы сдвигаются к границе изображения, чтобы покрыть его полностью.
    """
    step = tile_size - overlap

    def positions(total: int):
        if total <= tile_size:
            return [(0, total)]
        res = []
        pos = 0
        while pos + tile_size < total:
            res.append((pos, tile_size))
            pos += step
        # финальный тайл должен дойти до конца
        last_pos = total - tile_size
        if not res or last_pos > res[-1][0]:
            res.append((last_pos, tile_size))
        return res

    xs = positions(width)
    ys = positions(height)
    grid = []
    for y, h in ys:
        row = []
        for x, w in xs:
            row.append((x, y, w, h))
        grid.append(row)
    return grid


def compute_clean_grid(width: int, height: int, tile_size: int):
    """Ровная сетка без overlap. Последний ряд/столбец может быть меньше tile_size."""
    cols = ceil(width / tile_size)
    rows = ceil(height / tile_size)
    grid = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x = c * tile_size
            y = r * tile_size
            w = min(tile_size, width - x)
            h = min(tile_size, height - y)
            row.append((x, y, w, h))
        grid.append(row)
    return grid


def process_image(image_path: Path, out_dir: Path, args):
    rel_name = image_path.stem
    img = Image.open(image_path)
    orig_w, orig_h = img.size
    fmt = args.format.lower()
    ext = "png" if fmt == "png" else "jpg"

    entry = {
        "original": str(image_path.resolve()),
        "name": rel_name,
        "width": orig_w,
        "height": orig_h,
        "thumb": None,
        "tiles_overlap": [],
        "tiles_clean": []
    }

    # --- 1. Превью ---
    if args.thumb_size > 0:
        thumb = make_thumb(img, args.thumb_size)
        thumb_dir = out_dir / "thumbs"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{rel_name}_thumb.{ext}"
        if fmt == "png":
            thumb.save(thumb_path)
        else:
            thumb.save(thumb_path, quality=92)
        entry["thumb"] = str(thumb_path.resolve())

    # --- 2. Фрагменты с overlap ---
    ov_dir = out_dir / "tiles_overlap" / rel_name
    ov_dir.mkdir(parents=True, exist_ok=True)
    ov_grid = compute_overlap_grid(orig_w, orig_h, args.tile_size, args.overlap)
    rows = len(ov_grid)
    cols = len(ov_grid[0]) if rows else 0

    for r in range(rows):
        for c in range(cols):
            x, y, w, h = ov_grid[r][c]
            idx = r * cols + c
            tile_img = img.crop((x, y, x + w, y + h))
            tile_name = f"{rel_name}_ov_{idx:04d}_x{x}_y{y}.{ext}"
            tile_path = ov_dir / tile_name
            if fmt == "png":
                tile_img.save(tile_path)
            else:
                tile_img.save(tile_path, quality=95)

            # соседи для точного совмещения
            neighbors = {}
            if r > 0:
                neighbors["top"] = (r - 1) * cols + c
            if r < rows - 1:
                neighbors["bottom"] = (r + 1) * cols + c
            if c > 0:
                neighbors["left"] = r * cols + (c - 1)
            if c < cols - 1:
                neighbors["right"] = r * cols + (c + 1)

            entry["tiles_overlap"].append({
                "file": str(tile_path.resolve()),
                "index": idx,
                "row": r,
                "col": c,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "overlap_pixels": {
                    "left": args.overlap if x > 0 else 0,
                    "top": args.overlap if y > 0 else 0,
                    "right": args.overlap if (x + w) < orig_w else 0,
                    "bottom": args.overlap if (y + h) < orig_h else 0,
                },
                "neighbors": neighbors
            })

    # --- 3. Чистые фрагменты (без overlap) ---
    if args.clean:
        cl_dir = out_dir / "tiles_clean" / rel_name
        cl_dir.mkdir(parents=True, exist_ok=True)
        cl_grid = compute_clean_grid(orig_w, orig_h, args.tile_size)
        for r, row in enumerate(cl_grid):
            for c, (x, y, w, h) in enumerate(row):
                idx = r * len(row) + c
                tile_img = img.crop((x, y, x + w, y + h))
                tile_name = f"{rel_name}_cl_{idx:04d}_x{x}_y{y}.{ext}"
                tile_path = cl_dir / tile_name
                if fmt == "png":
                    tile_img.save(tile_path)
                else:
                    tile_img.save(tile_path, quality=95)
                entry["tiles_clean"].append({
                    "file": str(tile_path.resolve()),
                    "index": idx,
                    "row": r,
                    "col": c,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h
                })

    return entry


def main():
    parser = argparse.ArgumentParser(
        description="Нарезка схем: превью, фрагменты с overlap, чистые фрагменты, индекс."
    )
    parser.add_argument("input", help="Директория с исходными изображениями")
    parser.add_argument("-o", "--output", default="./sliced_output",
                        help="Выходная директория (по умолчанию ./sliced_output)")
    parser.add_argument("--thumb-size", type=int, default=1024,
                        help="Макс. размер превью по длинной стороне, 0=пропустить (default: 1024)")
    parser.add_argument("--tile-size", type=int, default=1024,
                        help="Размер фрагмента в пикселях (default: 1024)")
    parser.add_argument("--overlap", type=int, default=64,
                        help="Нахлёст в пикселях (default: 64, можно задать 2-3)")
    parser.add_argument("--clean", action="store_true",
                        help="Сгенерировать также чистые фрагменты без overlap")
    parser.add_argument("--format", choices=["png", "jpg"], default="png",
                        help="Формат сохранения фрагментов (default: png)")
    parser.add_argument("--ext", default="jpg,png,tif,tiff,bmp",
                        help="Обрабатываемые расширения через запятую (default: jpg,png,tif,tiff,bmp)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать план нарезки, не сохранять файлы")
    args = parser.parse_args()

    in_dir = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not in_dir.is_dir():
        print(f"Ошибка: {in_dir} не является директорией")
        sys.exit(1)

    exts = tuple(e.strip().lower() for e in args.ext.split(","))
    image_files = sorted([
        f for f in in_dir.iterdir()
        if f.is_file() and f.suffix.lower().lstrip(".") in exts
    ])

    if not image_files:
        print(f"Изображения с расширениями {exts} не найдены в {in_dir}")
        sys.exit(1)

    print(f"Найдено изображений: {len(image_files)}")
    if args.dry_run:
        print("РЕЖИМ ПРОВЕРКИ (dry-run): файлы не записываются\n")

    index = {
        "meta": {
            "source_dir": str(in_dir.resolve()),
            "output_dir": str(out_dir.resolve()),
            "params": vars(args)
        },
        "images": []
    }

    for img_path in image_files:
        print(f"  → {img_path.name} ({img_path.stat().st_size // 1024} KiB)")
        if args.dry_run:
            # быстрая проверка размеров
            with Image.open(img_path) as im:
                w, h = im.size
            grid = compute_overlap_grid(w, h, args.tile_size, args.overlap)
            total = sum(len(r) for r in grid)
            print(f"      размер {w}x{h}, фрагментов с overlap: {total}")
            continue

        entry = process_image(img_path, out_dir, args)
        index["images"].append(entry)
        print(f"      thumb: {'да' if entry['thumb'] else 'нет'}, "
              f"overlap: {len(entry['tiles_overlap'])}, clean: {len(entry['tiles_clean'])}")

    if not args.dry_run:
        index_path = out_dir / "index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print(f"\nИндекс сохранён: {index_path}")
        print(f"Структура выхода:\n"
              f"  {out_dir}/thumbs/          — превью\n"
              f"  {out_dir}/tiles_overlap/   — фрагменты с overlap\n"
              f"  {out_dir}/tiles_clean/     — фрагменты без overlap (если --clean)\n"
              f"  {out_dir}/index.json       — дерево индекса")


if __name__ == "__main__":
    main()
