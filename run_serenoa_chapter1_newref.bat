@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist ".venv-new\Scripts\python.exe" set "PY=.venv-new\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY set "PY=python"

echo ============================================================
echo Serenoa Chapter 1 - canonical male14 reference

echo Reference: assets\triangle-strategy\approved_voice_references\runtime_24k\serenoa_male14.wav
echo CSV:       imports\chapter1_serenoa_regen.csv
echo Output:    output\chapter1_serenoa_male14

echo This run regenerates all Serenoa Chapter 1 lines from scratch.
echo ============================================================
echo.

"%PY%" tools\run_voice_target_csv.py ^
  --csv imports\chapter1_serenoa_regen.csv ^
  --voice-target serenoa ^
  --output-dir output\chapter1_serenoa_male14 ^
  --overwrite ^
  --reset

set "ERR=%ERRORLEVEL%"
echo.
if "%ERR%"=="0" (
  echo SUCCESS - Serenoa Chapter 1 finished.
  echo Output: %CD%\output\chapter1_serenoa_male14
) else (
  echo FAILED with exit code %ERR%
  echo Fix the cause, then run again. The runner supports checkpoint/resume.
)
echo.
pause
exit /b %ERR%
