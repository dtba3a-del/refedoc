#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kit_assembly_test.py — проверка: собирается ли набор БЕЗ индекса и БЕЗ имён.

Замер, а не мнение. Куски копируются под обезличенными именами, координаты
из имён убираются, индекс не читается вовсе. Стыки ищутся только по
нахлёсту — так работает любой сшиватель панорам.

    python3 tools/kit_assembly_test.py КАТАЛОГ_С_ФРАГМЕНТАМИ [--overlap 64]

Печатает: сколько стыков найдено, с какой невязкой и сколько из них верных
(верность сверяется по исходным именам, которые сам подбор не видел).
"""
import argparse
import random
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def edge_cost(a, b, axis, ov):
    if axis == 0:
        if a.shape[0] != b.shape[0]:
            return 1e9
        return float(np.abs(a[:, -ov:] - b[:, :ov]).mean())
    if a.shape[1] != b.shape[1]:
        return 1e9
    return float(np.abs(a[-ov:, :] - b[:ov, :]).mean())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tiles_dir")
    ap.add_argument("--overlap", type=int, default=64)
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="порог невязки на нахлёсте (средняя разность яркости)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    src = Path(a.tiles_dir)
    files = sorted(src.glob("*.png")) + sorted(src.glob("*.jpg"))
    if len(files) < 2:
        raise SystemExit(f"в {src} меньше двух фрагментов — проверять нечего")

    order = files[:]
    random.Random(a.seed).shuffle(order)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for i, f in enumerate(order):                 # имена обезличены
            shutil.copy(f, work / f"{i:04d}{f.suffix}")
        anon = sorted(work.iterdir())
        arr = [np.asarray(Image.open(p).convert("L"), dtype=np.int32) for p in anon]

        n = len(arr)
        t0 = time.time()
        best = ({}, {})
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                for axis in (0, 1):
                    c = edge_cost(arr[i], arr[j], axis, a.overlap)
                    if c < best[axis].get(i, (1e9,))[0]:
                        best[axis][i] = (c, j)
        dt = time.time() - t0

    truth = {}
    for i, f in enumerate(order):
        p = f.stem.split("_")
        xs = [q for q in p if q.startswith("x")]
        ys = [q for q in p if q.startswith("y")]
        truth[i] = (int(xs[-1][1:]), int(ys[-1][1:])) if xs and ys else None

    print(f"фрагментов {n}, сравнений {2 * n * (n - 1)}, подбор {dt:.1f} с")
    for axis, name in ((0, "справа"), (1, "снизу")):
        found = [(i, s, j) for i, (s, j) in best[axis].items() if s < a.threshold]
        exact = sum(1 for i, (s, j) in best[axis].items() if s == 0.0)
        ok = 0
        for i, s, j in found:
            ti, tj = truth[i], truth[j]
            if not ti or not tj:
                continue
            ok += (tj[1] == ti[1] and tj[0] > ti[0]) if axis == 0 else \
                  (tj[0] == ti[0] and tj[1] > ti[1])
        print(f"  стык «{name}»: найдено {len(found)} с невязкой < {a.threshold}, "
              f"из них верных {ok}; с невязкой РОВНО 0 — {exact}")
    print("\nНевязка 0 означает, что нахлёст совпал побайтно: стык доказан самим\n"
          "материалом. Изъятие индекса такой стык не убирает — нахлёст есть\n"
          "сборочная инструкция, встроенная в детали.")


if __name__ == "__main__":
    main()
