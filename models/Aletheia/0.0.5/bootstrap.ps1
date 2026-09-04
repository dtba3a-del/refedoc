# Aletheia 0.0.5 — комплект одной вставкой (Windows PowerShell).
# Создаёт C:\0.0.5, скачивает сюда весь комплект из папки модели (GitHub raw)
# и запускает замер хоста. Ничего не отправляет: лог остаётся в C:\0.0.5\host_log.json.
#   irm https://raw.githubusercontent.com/dtba3a-del/refedoc/main/models/Aletheia/0.0.5/bootstrap.ps1 | iex
$ErrorActionPreference = "Stop"
$dir = if ($args.Count -gt 0) { $args[0] } else { "C:\0.0.5" }
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Set-Location $dir
$base = "https://raw.githubusercontent.com/dtba3a-del/refedoc/main/models/Aletheia/0.0.5"
$files = @("run_local.py", "run_local_0_0_5.py", "probe_host.py", "train_lora.py", "leak_test.py", "export_gguf.py", "train_config.json", "README.md")
foreach ($f in $files) {
    Invoke-WebRequest -Uri "$base/$f" -OutFile (Join-Path $dir $f)
}
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host "Python не найден: установить с python.org (галочка Add to PATH) и повторить"; exit 2 }
& $py.Source (Join-Path $dir "run_local.py") --only probe
Write-Host ""
Write-Host "комплект в $dir; лог: $(Join-Path $dir 'host_log.json'). Дальше: python $dir\run_local.py"
