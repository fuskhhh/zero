@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.13 -m venv .venv
    if errorlevel 1 goto :failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File build_windows.ps1 -Python "%CD%\.venv\Scripts\python.exe"
if errorlevel 1 goto :failed
explorer release
pause
exit /b 0
:failed
echo Build failed. Python 3.13 x64, Inno Setup 6 and internet access are required.
pause
exit /b 1
