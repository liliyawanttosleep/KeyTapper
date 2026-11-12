@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0keytapper.py"
    exit /b
)
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0keytapper.py"
    exit /b
)
echo Python was not found. Please install Python 3.8+ and run: pip install -r requirements.txt
pause
