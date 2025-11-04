@echo off
REM Simple wrapper for cmd.exe users to run the PowerShell helper
setlocal
if "%1"=="" (
  set MODE=api
) else (
  set MODE=%1
)
if "%2"=="" (
  set PORT=8000
) else (
  set PORT=%2
)

powershell -ExecutionPolicy Bypass -File "%~dp0dev-run.ps1" -Mode %MODE% -Port %PORT%
