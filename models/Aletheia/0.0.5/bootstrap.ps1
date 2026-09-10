# Aletheia 0.0.5 — комплект одной вставкой (Windows PowerShell 5.1 и 7).
# Создаёт папку комплекта (по умолчанию C:\0.0.5), скачивает сюда весь комплект
# из папки модели (GitHub raw) и запускает замер хоста. Ничего не отправляет:
# лог остаётся в <папка>\host_log.json.
#   irm https://raw.githubusercontent.com/dtba3a-del/refedoc/main/models/Aletheia/0.0.5/bootstrap.ps1 | iex
# Другая папка: перед вставкой  $env:ALETHEIA_DIR = "D:\aletheia"  (под `irm | iex`
# аргументов у скрипта нет — только переменная среды); при запуске файлом —
# .\bootstrap.ps1 D:\aletheia
# Скрипт не пользуется `exit`: под `irm | iex` это закрыло бы окно консоли.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

$dir = "C:\0.0.5"
if ($env:ALETHEIA_DIR) { $dir = $env:ALETHEIA_DIR }
if ($args -and $args.Count -gt 0) { $dir = $args[0] }
$dir = [System.IO.Path]::GetFullPath($dir)
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$base = "https://raw.githubusercontent.com/dtba3a-del/refedoc/main/models/Aletheia/0.0.5"
$files = @("run_local.py", "run_local_0_0_5.py", "probe_host.py", "train_lora.py", "leak_test.py", "export_gguf.py", "train_config.json", "README.md")
foreach ($f in $files) {
    $target = Join-Path $dir $f
    Invoke-WebRequest -Uri "$base/$f" -OutFile $target -UseBasicParsing
    if (-not (Test-Path $target)) { Write-Host "!! не скачался $f"; return }
}
Write-Host "комплект скачан в $dir ($($files.Count) файлов)"

# Python: сначала пускач py (ставится с python.org), затем python/python3;
# псевдоним Магазина Windows (…\WindowsApps\python.exe) открывает Магазин и
# ничего не запускает — он отводится; каждый кандидат проверяется запуском.
function Find-Python {
    # Срез $a[1..($a.Count-1)] при одном элементе даёт $a[1..0] = сам элемент — потому остаток берётся явно.
    $ErrorActionPreference = "Continue"
    $cands = @(@("py", "-3"), @("python"), @("python3"))
    foreach ($c in $cands) {
        $cmd = Get-Command $c[0] -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($cmd.Source -like "*\WindowsApps\*") { continue }
        $rest = @(); if ($c.Count -gt 1) { $rest = @($c[1..($c.Count - 1)]) }
        try {
            $v = & $cmd.Source @rest --version 2>&1
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3\.") {
            $found = @($cmd.Source) + $rest
            return ,$found
        }
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    Write-Host "Python 3 не найден (псевдоним Магазина не считается): установить с python.org (галочка Add to PATH), открыть новое окно и повторить вставку"
    return
}
$exe = $py[0]; $pyargs = @(); if ($py.Count -gt 1) { $pyargs = @($py[1..($py.Count - 1)]) }
Write-Host "python: $exe $pyargs"

# Запуск из ЛЮБОЙ текущей папки: пути комплекта считаются от его папки, не от текущей.
& $exe @pyargs (Join-Path $dir "run_local.py") --only probe
Write-Host ""
Write-Host "комплект в $dir; лог: $(Join-Path $dir 'host_log.json')."
Write-Host "Дальше (из любой папки): & '$exe' $pyargs '$(Join-Path $dir 'run_local.py')'"
