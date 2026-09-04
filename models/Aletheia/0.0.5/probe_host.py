#!/usr/bin/env python3
"""Замер хоста для обучения модели (слово автора 04.09, п. 4: «если нужны
доп. данные локального хоста — скрипт на питоне — лог в ответ»).

Ничего не меняет, ничего не отправляет: собирает GPU (nvidia-smi и/или
torch), CPU, ОЗУ, диск, версии Python/torch/CUDA, каталог моделей LM
Studio — и пишет host_log.json рядом с собой плюс печатает то же в чат.
Ключей, паролей, содержимого файлов не читает.

    python probe_host.py            # Windows 11 / Linux / macOS
"""
from __future__ import annotations

import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys


def sh(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"нет: {type(e).__name__}"


def main() -> int:
    log: dict = {"os": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
                 "cpu": platform.processor() or sh(["uname", "-p"]), "cpu_count": os.cpu_count()}
    log["nvidia-smi"] = sh(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version,compute_cap",
                            "--format=csv,noheader"]) if shutil.which("nvidia-smi") else "nvidia-smi не найден"
    log["cuda_driver"] = "есть (nvidia-smi отвечает)" if shutil.which("nvidia-smi") and "не найден" not in log["nvidia-smi"] else "нет"
    # ВСЕ видеоадаптеры (04.09: у хоста две карты — одна для экрана, другая для ИИ;
    # nvidia-smi показывает только NVIDIA, а вопрос «что грузится» требует обеих)
    if os.name == "nt":
        log["gpus_all"] = sh(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + ' | VRAM ' + [math]::Round($_.AdapterRAM/1GB,1) + ' GiB | драйвер ' + $_.DriverVersion }"])
    else:
        log["gpus_all"] = sh(["sh", "-c", "lspci | grep -i 'vga\\|3d\\|display'"])
    try:
        import torch  # noqa: WPS433
        log["torch"] = torch.__version__
        log["torch_build"] = "CUDA" if torch.version.cuda else "CPU (+cpu) — карту не видит, даже если CUDA-драйвер есть"
        log["cuda"] = {"available": torch.cuda.is_available(), "version": torch.version.cuda,
                       "devices": [{"name": torch.cuda.get_device_name(i),
                                    "vram_GiB": round(torch.cuda.get_device_properties(i).total_memory / 2 ** 30, 1)}
                                   for i in range(torch.cuda.device_count())] if torch.cuda.is_available() else []}
        log["bf16"] = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
    except ImportError:
        log["torch"] = "не установлен"
    try:
        import psutil  # noqa: WPS433
        log["ram_GiB"] = round(psutil.virtual_memory().total / 2 ** 30, 1)
    except ImportError:
        log["ram_GiB"] = "psutil нет — " + (sh(["wmic", "OS", "get", "TotalVisibleMemorySize"]) if os.name == "nt" else sh(["free", "-g"]))
    du = shutil.disk_usage(pathlib.Path.home())
    log["disk_home_free_GiB"] = round(du.free / 2 ** 30, 1)
    home = pathlib.Path.home()
    cands = [home / ".lmstudio", home / ".cache" / "lm-studio", home / "AppData" / "Local" / "LM-Studio",
             pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "LM-Studio"]
    log["lmstudio_dirs"] = [str(p) for p in cands if p.exists()]
    for p in log["lmstudio_dirs"]:
        models = pathlib.Path(p) / "models"
        if models.exists():
            log["lmstudio_models"] = sorted(str(q.relative_to(models)) for q in models.rglob("*.gguf"))[:50]
    for mod in ("transformers", "peft", "bitsandbytes", "accelerate", "datasets"):
        try:
            log[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001
            log[mod] = "нет"
    out = pathlib.Path(__file__).resolve().parent / "host_log.json"
    out.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=1))
    print(f"\nзаписано: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
