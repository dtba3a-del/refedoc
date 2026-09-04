# Aletheia 0.0.5 — замер хоста одной вставкой (Windows PowerShell).
# Создаёт C:\0.0.5, скачивает probe_host.py отсюда же (GitHub raw) и запускает его.
# Ничего не отправляет: лог остаётся в C:\0.0.5\host_log.json.
$ErrorActionPreference = "Stop"
$dir = if ($args.Count -gt 0) { $args[0] } else { "C:\0.0.5" }
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Set-Location $dir
$base = "https://raw.githubusercontent.com/dtba3a-del/refedoc/main/models/Aletheia/0.0.5"
foreach ($f in @("probe_host.py", "train_config.json")) {
    Invoke-WebRequest -Uri "$base/$f" -OutFile (Join-Path $dir $f)
}
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host "Python не найден: установить с python.org (галочка Add to PATH) и повторить"; exit 2 }
& $py.Source (Join-Path $dir "probe_host.py")
Write-Host ""
Write-Host "лог: $(Join-Path $dir 'host_log.json') — прислать этот файл."
