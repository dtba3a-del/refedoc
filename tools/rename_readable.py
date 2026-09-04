#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rename_readable.py — понятные имена вместо номеров и буквоцифровой каши.

Источник нередко отдаёт файл под номером (`3986108.pdf`, `r002h.pdf`,
`06-17.pdf`). Такое имя не сообщает ничего ни человеку, ни машине.

Имя берётся **из самого документа**, а не выдумывается: заголовок в
метаданных PDF, затем первая содержательная строка текстового слоя, затем
улика распознавания из кэша разбора прав. Если ничего не нашлось — файл
остаётся под прежним именем и попадает в список неразобранных: **выдуманное
имя хуже непонятного**, потому что выглядит осмысленным.

Прежнее имя не теряется: пара «было → стало» пишется в производный
`ИМЕНА.md` и `имена.json`.

    python3 tools/rename_readable.py --dry-run
    python3 tools/rename_readable.py --apply
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = None
MAXLEN = 50

# Имя считается «кашей», если в нём нет ни одного словарного куска:
# только цифры, версии, короткие буквенные хвосты.
MUSH = re.compile(r"^(?:[\d][\d._\-]*|[a-z]{1,3}\d{2,}[a-z]?|\d{4}\.\d{4,5}(?:v\d+)?|"
                  r"[a-z]{1,4}\d{4}|\d{2}-\d{2})$", re.I)

DROP = re.compile(r"^(microsoft word|untitled|document|scan|без имени|документ|"
                  r"print|pdf|arxiv|\s*)$", re.I)

# Мусор сайтов-агрегаторов в начале заголовка: имя документа он не образует.
SITE_CRUFT = re.compile(r"^(скачать|download|бесплатно|free)\s+", re.I)


# Обозначения, которые говорят сами: их не трогаем, сколько бы ни было цифр.
SPEAKS = re.compile(r"ГОСТ|ОСТ\s|ТУ\s|ISO|IEC|IEEE|ITU|EBU|AES|EN\s?\d|DIN|MIL-",
                    re.I)


def is_mush(stem: str) -> bool:
    """Имя-каша: ни одного слова длиннее четырёх букв и ни одного обозначения."""
    if SPEAKS.search(stem):
        return False
    if MUSH.match(stem):
        return True
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{5,}", stem)
    return not words


def clean(s: str) -> str:
    s = " ".join(s.split())
    s = re.sub(r"[\\/:*?\"<>|]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .-–—_")
    return s


def title_from_pdf(path: Path):
    """(имя, откуда) — или (None, причина). Ничего не выдумывает."""
    try:
        info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True,
                              errors="replace").stdout
    except OSError:
        return None, "pdfinfo недоступен"
    m = re.search(r"^Title:\s+(.+)$", info, re.M)
    if m:
        t = SITE_CRUFT.sub("", clean(m.group(1)))
        if t and not DROP.match(t) and not is_mush(t) and len(t) > 8:
            return t, "заголовок в метаданных"
    # «Первая содержательная строка» как источник имени ОТВЕРГНУТА замером
    # 2026-09-04. На статьях она давала колонтитул («188 В. А. Панчелюга,
    # С. Э. Шноль О.»), строку PACS-кодов, адрес электронной почты и шапку
    # «Draft version February 2, 2023» — всё это выглядит как имя и им не
    # является. Три настройки подряд её не выправили: неверен приём, а не
    # порог.
    #
    # Остаются источники, у которых имя размечено в самом документе:
    # заголовок метаданных, код ИНИД [54] у патентов, обозначение стандарта.
    # Прочее остаётся под прежним именем и ждёт прямого чтения — это
    # работа не механическая.
    return None, "заголовок в документе не размечен; нужно прямое чтение"


def from_evidence(cache_text: str, stem: str):
    """
    Улика распознавания у патентов США.

    Номер берётся ИЗ ИМЕНИ ФАЙЛА, а не из текста страницы. Замер 2026-09-04:
    первая редакция вылавливала первое число вида 1,234,567 со страницы и на
    `US5272449` дала «Патент США 3656053» — номер процитированного чужого
    патента. Имя с неверным номером хуже номера без имени, поэтому источник
    номера теперь один и проверяемый.

    Заголовок берётся по коду ИНИД [54], которым он размечен в самом
    документе; сам код в имя не попадает.
    """
    m = re.search(r"(\d{7,8})", stem.replace(",", ""))
    num = m.group(1) if m else None
    if not cache_text:
        return (f"Патент США {num}", "номер из имени файла") if num else (None, "улик нет")

    title = None
    # Распознавание отдаёт код ИНИД то как [54], то как (54) — принимаем оба.
    t = re.search(r"[\[(]\s*54\s*[\])]\s*(.{6,120}?)"
                  r"(?:[\[(]\s*\d{2}\s*[\])]|\n\s*\n|$)", cache_text, re.S)
    if t:
        cand = clean(re.sub(r"^[\[(]?\s*\d{2}\s*[\])]?\s*", "",
                            re.sub(r"\s+", " ", t.group(1))))
        if len(re.findall(r"[A-Za-z]{3,}", cand)) >= 2:
            title = cand.title()
    if not title:
        for line in cache_text.splitlines():
            c = clean(line)
            if len(c) < 14 or not c.isupper():
                continue
            if re.search(r"\d{3}", c) or re.search(r"^US\s?\d", c, re.I):
                continue                      # это идентификатор, а не заголовок
            if len(re.findall(r"[A-Z]{3,}", c)) < 2:
                continue
            title = c.title()
            break
    if num and title:
        return f"Патент США {num} — {title}", "номер из имени, заголовок по коду [54]"
    if num:
        return f"Патент США {num}", "номер из имени; заголовок не выведен"
    return None, "в улике ни номера, ни заголовка"



BOILER = re.compile(r"^(draft|preprint|submitted|accepted|typeset|to appear|"
                    r"copyright|©|proceedings of|arxiv|manuscript|"
                    r"version \w+|черновик|препринт)\b", re.I)


def looks_like_language(s: str) -> bool:
    """
    Годно ли имя как ИМЯ. Замер 2026-09-04: у трёх файлов (`r002h`, `r002i`,
    `r002j`) текстовый слой лежит в битой кодировке, и первая редакция
    произвела из неё «¶ÇÄÓÂÎß 2000 Å. ´ÑÏ 170, å 2» — уверенную кашу, которая
    хуже прежнего номера, потому что выглядит осмысленной.

    Проверяется три вещи: доля букв одного алфавита, отсутствие знаков,
    которых в русском и английском не бывает, и что это не служебная шапка.
    """
    if BOILER.match(s):
        return False
    if SPEAKS.search(s):
        return True                       # обозначение стандарта говорит само
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 8:
        return False
    cyr = sum(1 for c in letters if "А" <= c <= "я" or c in "Ёё")
    lat = sum(1 for c in letters if "A" <= c <= "z")
    share = max(cyr, lat) / len(letters)
    if share < 0.9:
        return False                      # алфавиты перемешаны — признак кодировки
    if re.search(r"[¶ÇÄÓÂÎßÑÏåª³¾®¡£¦¥¬¸À§µ¢©°±²´·¹º»¼½¿×Ø]", s):
        return False                      # знаки, которых в тексте не бывает
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", s)
    return len(words) >= 2


def shorten(name: str) -> str:
    if len(name) <= MAXLEN:
        return name
    cut = name[:MAXLEN]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > MAXLEN * 0.6 else cut).rstrip(" .-–—_")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(HERE.parent), help="где переименовывать")
    ap.add_argument("--out", default=str(HERE.parent))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = Path(a.root)
    out = Path(a.out)
    cache = {}
    cp = out / "rights_cache.json"
    if cp.is_file():
        try:
            cache = json.loads(cp.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    ev = {}
    for k, v in cache.items():
        parts = k.split("|")
        if len(parts) >= 2:
            ev[parts[1].split("/")[-1]] = v

    rows, skipped = [], []
    for f in sorted(root.rglob("*.pdf")) + sorted(root.rglob("*.djvu")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith((".git", "docs/", "tools/", "env/")):
            continue
        if not is_mush(f.stem):
            skipped.append((rel, "имя уже говорит"))
            continue
        name, why = title_from_pdf(f)
        if not name:
            name, why = from_evidence(ev.get(f.name, ""), f.stem)
        if not name:
            skipped.append((rel, f"имя не выведено: {why}"))
            continue
        new = shorten(clean(name)) + f.suffix.lower()
        if not looks_like_language(Path(new).stem):
            skipped.append((rel, "выведенное имя не похоже на язык — оставлено прежнее"))
            continue
        if new == f.name:
            skipped.append((rel, "совпало с прежним"))
            continue
        rows.append({"путь": rel, "было": f.name, "стало": new, "основание": why})

    for r in rows:
        print(f"  {r['было']}\n    → {r['стало']}   ({r['основание']})")
    print(f"\nпереименовать: {len(rows)}; оставить как есть: {len(skipped)}")
    if a.apply:
        done = 0
        for r in rows:
            src = root / r["путь"]
            dst = src.with_name(r["стало"])
            if dst.exists():
                continue
            shutil.move(str(src), str(dst))
            r["стало_путь"] = dst.relative_to(root).as_posix()
            done += 1
        (out / "имена.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        lines = ["# Указатель имён: было → стало", "",
                 "**Файл производный.** Собран `tools/rename_readable.py`.",
                 "Прежнее имя здесь сохраняется навсегда: ссылка из старой переписки",
                 "должна находиться и после переименования.", "",
                 f"Переименовано: **{done}**. Имя берётся из самого документа; где вывести",
                 "не удалось — файл оставлен под прежним именем, потому что **выдуманное",
                 "имя хуже непонятного**.", "",
                 "| было | стало | основание |", "|---|---|---|"]
        lines += [f"| `{r['было']}` | `{r['стало']}` | {r['основание']} |" for r in rows]
        (out / "ИМЕНА.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"переименовано: {done}; указатель имён записан")


if __name__ == "__main__":
    main()
