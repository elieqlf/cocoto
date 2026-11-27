@echo off
rem Lance l'interface de Cocoto (double-clic). Journal : %APPDATA%\Cocoto\bot_log.txt
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Environnement Python introuvable : .venv manque dans %~dp0
    echo Recree-le avec : python -m venv .venv  puis  .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m cocoto %*
