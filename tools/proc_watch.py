#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proc_watch.py — запуск внешней программы по признаку ПРОГРЕССА, а не по секундомеру.

Предел по общему времени неверен по построению: он не отличает долгую
работу от зависшей. Крупный документ распознаётся долго ЗАКОННО, и убивать
его за это — терять работу; при этом сбой среды может оставить процесс,
который не вернёт ничего и никогда.

Различает их одно: **растёт ли выход**. Наблюдается размер выходного файла
(или объём, прочитанный со stdout). Пока он растёт — процесс работает,
сколько бы это ни длилось. Не растёт дольше `stall` — процесс стоит, и
только тогда он снимается.

Замер 2026-09-04, из-за которого правило и написано: `tesseract` без
предела проработал 24 минуты на одной странице и заморозил прогон по всему
корпусу; поставленный вместо этого предел в 90 с был бы ровно той же
ошибкой с другой стороны — он убил бы законно долгую страницу.

    from proc_watch import run_watched
    code, out = run_watched(["tesseract", png, "stdout", "-l", "rus"], stall=45)
"""
import subprocess
import threading
import time
from pathlib import Path


def run_watched(cmd, stall: float = 45.0, out_file=None, env=None, poll: float = 3.0,
                hard_cap: float = 0.0):
    """
    Возвращает (код возврата, собранный stdout).

    stall     — сколько секунд отсутствия прогресса считать остановкой;
    out_file  — если программа пишет в файл, следим за ним; иначе за stdout;
    hard_cap  — предел общего времени; 0 означает «не ограничивать»,
                и это НОРМА: ограничивать общее время — снова путать
                долгую работу с зависшей.
    """
    chunks = []
    lock = threading.Lock()
    progress = {"bytes": 0, "at": time.time()}

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)

    def reader():
        for block in iter(lambda: p.stdout.read(65536), b""):
            with lock:
                chunks.append(block)
                progress["bytes"] += len(block)
                progress["at"] = time.time()
        try:
            p.stdout.close()
        except OSError:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    started = time.time()
    of = Path(out_file) if out_file else None
    last_size = -1
    while p.poll() is None:
        time.sleep(poll)
        now = time.time()
        if of is not None and of.exists():
            size = of.stat().st_size
            if size != last_size:
                last_size = size
                with lock:
                    progress["at"] = now
        with lock:
            idle = now - progress["at"]
        if idle > stall:
            p.kill()
            t.join(timeout=5)
            return -1, b"".join(chunks).decode("utf-8", "replace")
        if hard_cap and (now - started) > hard_cap:
            p.kill()
            t.join(timeout=5)
            return -2, b"".join(chunks).decode("utf-8", "replace")

    t.join(timeout=10)
    return p.returncode, b"".join(chunks).decode("utf-8", "replace")


if __name__ == "__main__":
    import sys
    code, out = run_watched(sys.argv[1:])
    print(out, end="")
    sys.exit(0 if code == 0 else 1)
