@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv\Scripts\python.exe not found.
  echo Run this command from a configured OmniVoice Thai Studio checkout.
  exit /b 2
)

".venv\Scripts\python.exe" -B csv_batch_cli.py %*
exit /b %ERRORLEVEL%
