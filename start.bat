@echo off
rem Запуск Local AI Organizer без окна консоли (двойной клик по файлу).
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
) else (
    start "" pythonw "main.py"
)
