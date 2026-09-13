# Уведомление: Баг в bootstrap.ps1 и kit-windows.yml

**Дата:** 2026-09-13 22:00 UTC  
**Статус:** Выявлено, требует исправления  
**Источник:** GitHub Actions workflow runs (6 фейлов подряд)

---

## Проблема

Workflow `.github/workflows/kit-windows.yml` падает на job `bootstrap-windows` с множественными ошибками при запуске PowerShell скрипта `bootstrap.ps1`.

**Ошибки в логах:**
- Line 47 в `kit-windows.yml`: `irm ... | iex` не обрабатывает ошибки загрузки файлов
- Line 25-26 в `bootstrap.ps1`: при недостаче файла скрипт вызывает `return` вместо `throw`, продолжая выполнение
- Line 57 в `bootstrap.ps1`: `$pyargs` как массив передаётся неправильно в команду
- Line 63 в `bootstrap.ps1`: Single Quote блокирует интерполяцию переменных

**Следствие:** 28 ошибок в 6 workflow runs (1 days назад до now).

---

## Почему это критично

- Workflow должен проверять комплект Aletheia 0.0.5 на Windows и Linux
- Сейчас проверка не запускается, комплект не тестируется перед релизом
- Нарушена CI/CD дисциплина

---

## Решение

### 1. bootstrap.ps1 (Line 25-26)
```powershell
# Было:
if (-not (Test-Path $target)) { Write-Host "!! не скачался $f"; return }

# Стало:
if (-not (Test-Path $target)) { throw "не скачался $f — прерывание скрипта" }
```

### 2. bootstrap.ps1 (Line 56-57)
```powershell
# Было:
$exe = $py[0]; $pyargs = @(); if ($py.Count -gt 1) { $pyargs = @($py[1..($py.Count - 1)]) }
Write-Host "python: $exe $pyargs"

# Стало:
$exe = $py[0]
$pyargs = @()
if ($py.Count -gt 1) { $pyargs = @($py[1..($py.Count - 1)]) }
Write-Host "python: $exe $(@($pyargs) -join ' ')"
```

### 3. bootstrap.ps1 (Line 60)
```powershell
# Было:
& $exe @pyargs (Join-Path $dir "run_local.py") --only probe

# Стало:
& $exe @pyargs @((Join-Path $dir "run_local.py"), "--only", "probe")
```

### 4. bootstrap.ps1 (Line 63)
```powershell
# Было:
Write-Host "Дальше (из любой папки): & '$exe' $pyargs '$(Join-Path $dir 'run_local.py')'"

# Стало:
Write-Host "Дальше (из любой папки): & '$exe' $(if ($pyargs) { $pyargs -join ' ' }) '$(Join-Path $dir 'run_local.py')'"
```

---

## Что делать

1. Применить патч к `bootstrap.ps1`
2. Применить валидацию к `kit-windows.yml` (добавить error handling в строку 47)
3. Запустить workflow заново
4. Проверить логи job `bootstrap-windows`

---

## Файлы затронуты

- `.github/workflows/kit-windows.yml` (Line 47)
- `models/Aletheia/0.0.5/bootstrap.ps1` (Line 25, 56-57, 60, 63)

---

*Написано: Copilot @ GitHub  
Требует действия: YES  
PR готов: Жду подтверждения*
