@echo off
REM backup-inversepolar.bat - Бэкап InvesePolar для Windows
REM Версия: 1.0
REM Дата: 2026-09-13
REM Назначение: Клонирование и обновление приватного репо с обработкой таймаутов

setlocal enabledelayedexpansion

set REPO_URL=https://github.com/dtba3a-del/InvesePolar.git
set BACKUP_DIR=InvesePolar_backup
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/" %%a in ('time /t') do (set mytime=%%a%%b)
set LOG_FILE=backup_%mydate%_%mytime%.log

echo.
echo ====================================
echo InvesePolar Backup Script
echo Started: %date% %time%
echo ====================================
echo.

REM Перенаправляем весь вывод в лог-файл
(
  echo [%date% %time%] Начало бэкапа InvesePolar
  echo [INFO] Размер репо: 1.69 GB ^(Python^)
  echo [INFO] Конфигурирование Git...
  
  REM Настройка git для больших репо
  git config --global http.postBuffer 524288000
  git config --global http.lowSpeedLimit 0
  git config --global http.lowSpeedTime 999999
  git config --global core.compression 9
  
  echo [INFO] Git параметры установлены
  
  REM Проверка существования репо
  if exist "%BACKUP_DIR%\.git" (
    echo [INFO] Репо существует. Обновляем...
    cd /d "%BACKUP_DIR%"
    git fetch --all --prune --tags
    if !errorlevel! equ 0 (
      echo [SUCCESS] Fetch завершен
    ) else (
      echo [WARNING] Fetch код: !errorlevel!
    )
    cd ..
  ) else (
    echo [INFO] Первое клонирование --depth 100
    gh repo clone dtba3a-del/InvesePolar "%BACKUP_DIR%" -- --depth 100 --single-branch --branch main
    
    if !errorlevel! equ 0 (
      echo [SUCCESS] gh clone завершен
      cd /d "%BACKUP_DIR%"
      git fetch --unshallow
      cd ..
    ) else (
      echo [INFO] gh не удалось, пробу��м git clone
      git clone --depth 50 "%REPO_URL%" "%BACKUP_DIR%"
      
      if !errorlevel! neq 0 (
        echo [ERROR] Оба способа не удались
        exit /b 1
      )
    )
  )
  
  REM Проверка целостности
  if exist "%BACKUP_DIR%\.git" (
    cd /d "%BACKUP_DIR%"
    git status > nul 2>&1
    if !errorlevel! equ 0 (
      echo [SUCCESS] Репо в порядке
      for /f %%A in ('git rev-parse --short HEAD') do set COMMIT=%%A
      echo [INFO] HEAD: !COMMIT!
    ) else (
      echo [ERROR] Репо поврежден
      cd ..
      exit /b 1
    )
    cd ..
    echo [SUCCESS] ========================================
    echo [SUCCESS] Бэкап успешен: %BACKUP_DIR%
    echo [SUCCESS] ========================================
  ) else (
    echo [ERROR] Папка %BACKUP_DIR%\.git не найдена
    exit /b 1
  )
  
) > "%LOG_FILE%" 2>&1

type "%LOG_FILE%"
echo.
echo Лог сохранен: %LOG_FILE%
pause
