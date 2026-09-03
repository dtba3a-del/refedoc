#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guard.py — досмотр на границе публичной зоны `refedoc`.

Запрещает, а не советует. Три режима:

    guard.py path ПУТЬ...        досмотр путей (крючок PreToolUse на Write/Edit)
    guard.py staged              досмотр git-индекса (крючок pre-commit)
    guard.py hook                досмотр по JSON от Claude Code на stdin

Код выхода: 0 — пропустить, 2 — задержать (для PreToolUse это блокировка).
Печатает ПОКРЫТИЕ: сколько файлов просмотрено и сколько пропущено, с
причиной. «Секретов не найдено» без покрытия есть утверждение о
досмотрщике, а не о грузе.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# --- запрещённые места: стенограммы и приватный лоток ------------------------
FORBIDDEN_PATH = [
    (re.compile(r"(^|/)chatlog(/|$)"), "стенограммы чатов"),
    (re.compile(r"(^|/)sessions(/|$)"), "журналы сессий — приватная зона"),
    (re.compile(r"(^|/)context-export(/|$)"), "выгрузка бесед другой среды"),
    (re.compile(r"(^|/)inbox(/|$)"), "входящий лоток автора"),
    (re.compile(r"(^|/)\.chatman(/|$)"), "канон и состояние chatman"),
    (re.compile(r"\.jsonl$"), "стенограмма профиля (*.jsonl)"),
    (re.compile(r"(^|/)\.env(\.|$)|(^|/)\.env$"), "файл окружения"),
    (re.compile(r"(^|/)(id_rsa|id_ed25519|id_ecdsa)(\.|$)"), "приватный ключ"),
    (re.compile(r"\.(pem|pfx|p12|keystore)$"), "контейнер ключей"),
]

# --- запрещённое содержимое --------------------------------------------------
FORBIDDEN_TEXT = [
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "приватный ключ в теле файла", False),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"), "ключ Anthropic API", False),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "токен GitHub", False),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "ключ AWS", False),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "токен Slack", False),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
     "пароль или ключ значением", False),
    (re.compile(r"^\s*(USER|ASSISTANT|HUMAN)\s*:", re.M), "разметка стенограммы (USER:/ASSISTANT:)", True),
    (re.compile(r'"role"\s*:\s*"(assistant|user)"'), "стенограмма в JSON (role: assistant/user)", True),
    (re.compile(r"(?m)^\s*<(user|assistant)_message>"), "разметка стенограммы в XML", True),
]

TEXT_EXT = {".md", ".txt", ".py", ".json", ".sh", ".yml", ".yaml", ".toml", ".cfg",
            ".ini", ".c", ".h", ".cpp", ".js", ".ts", ".html", ".csv", ".rst", ""}
MAX_SCAN = 4 << 20  # 4 МиБ: дальше не читаем и объявляем это числом

SELF = {"env/Librarer/hooks/guard.py", "env/Librarer/RULES.md",
        "env/Librarer/README.md", "env/Librarer/hooks/on-session-start.sh"}


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def check(paths):
    """Возвращает (нарушения, счётчики, пропущено[(путь, причина)])."""
    viol, skipped = [], []
    n_total, n_content = 0, 0
    for raw in paths:
        n_total += 1
        p = Path(raw)
        r = rel(p)
        # Файлы самого досмотрщика содержат образцы запрещённой разметки —
        # у них правила разметки не применяются. Правила о ключах применяются
        # ВСЕГДА: полное исключение было бы дырой ровно в том файле, который
        # чаще всех правят.
        self_file = r in SELF
        for rx, why in FORBIDDEN_PATH:
            if rx.search(r):
                viol.append((r, f"место запрещено: {why}"))
                break
        if not p.is_file():
            skipped.append((r, "файла нет на диске (удаление или ещё не записан)"))
            continue
        size = p.stat().st_size
        if p.suffix.lower() not in TEXT_EXT:
            skipped.append((r, f"двоичный ({p.suffix or 'без расширения'}), содержимое не читалось"))
            continue
        if size > MAX_SCAN:
            skipped.append((r, f"{size / 2**20:.1f} МиБ > {MAX_SCAN / 2**20:.0f} МиБ, содержимое не читалось"))
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            skipped.append((r, f"не прочитан: {e}"))
            continue
        n_content += 1
        for rx, why, is_markup in FORBIDDEN_TEXT:
            if is_markup and self_file:
                continue
            if rx.search(body):
                viol.append((r, f"содержимое запрещено: {why}"))
    return viol, {"всего": n_total, "содержимым": n_content}, skipped


def report(viol, cnt, skipped, where):
    print(f"[Librarer/пограничник] {where}: путей {cnt['всего']}, "
          f"просмотрено содержимым {cnt['содержимым']}, "
          f"пропущено {len(skipped)} "
          f"(покрытие {100 * cnt['содержимым'] / max(1, cnt['всего']):.0f} %)", file=sys.stderr)
    for r, why in skipped[:20]:
        print(f"  пропущен: {r} — {why}", file=sys.stderr)
    if len(skipped) > 20:
        print(f"  … и ещё {len(skipped) - 20}", file=sys.stderr)
    if viol:
        print("\nГРАНИЦА ЗАКРЫТА. refedoc — публичная зона.", file=sys.stderr)
        for r, why in viol:
            print(f"  ✗ {r}\n      {why}", file=sys.stderr)
        print("\nКанон: env/Librarer/RULES.md §1. Стенограммы и секреты сюда не едут;\n"
              "отчёт по чатлогу пишется в приватный репозиторий-источник.", file=sys.stderr)
        return 2
    print("[Librarer] нарушений в просмотренном нет "
          "(о непросмотренном утверждения не делается).", file=sys.stderr)
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "hook"
    if mode == "path":
        paths = sys.argv[2:]
        where = "досмотр путей"
    elif mode == "staged":
        # -z обязателен: без него git отдаёт не-ASCII имена в escape-виде
        # ("\320\227…"), путь не открывается, и досмотрщик молча считает файл
        # отсутствующим. Замер 2026-09-03: так мимо досмотра прошли бы 8 из 25
        # файлов — все с кириллицей в имени, то есть ровно русская часть груза.
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "-z",
                              "--diff-filter=ACMR"],
                             capture_output=True, cwd=REPO).stdout
        paths = [str(REPO / n.decode("utf-8", "surrogateescape"))
                 for n in out.split(b"\0") if n]
        where = "досмотр индекса git"
    else:
        try:
            payload = json.load(sys.stdin)
        except Exception:
            return 0
        ti = payload.get("tool_input", {}) or {}
        cand = [ti.get("file_path"), ti.get("path"), ti.get("notebook_path")]
        paths = [c for c in cand if c]
        if not paths:
            return 0
        where = "досмотр записи"
    if not paths:
        print("[Librarer] досматривать нечего: список пуст.", file=sys.stderr)
        return 0
    viol, cnt, skipped = check(paths)
    return report(viol, cnt, skipped, where)


if __name__ == "__main__":
    sys.exit(main())
