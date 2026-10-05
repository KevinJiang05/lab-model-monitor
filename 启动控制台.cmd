@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 (
    echo Could not open the project directory.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment is missing: .venv\Scripts\python.exe
    echo See README.md for environment setup.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -X utf8 "scripts\start_console.py" %*
if errorlevel 1 (
    echo Console startup failed. See the error above.
    pause
    exit /b 1
)
endlocal
