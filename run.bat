@echo off
chcp 65001 >nul
rem Запуск оверлея. При первом запуске создаёт окружение и ставит зависимости.
cd /d "%~dp0"
if not exist .venv (
    py -3 -m venv .venv || goto :error
    .venv\Scripts\python -m pip install -r requirements.txt || goto :error
)
start "" .venv\Scripts\pythonw -m arc_overlay
exit /b 0
:error
echo Не удалось подготовить окружение. Проверь, что установлен Python 3.11+ с python.org.
pause
