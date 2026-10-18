@echo off
chcp 65001 >nul
rem Запуск оверлея. При первом запуске создаёт окружение и ставит зависимости.
cd /d "%~dp0"

set "PY=py -3"
where py >nul 2>nul || set "PY=python"

if not exist ".venv\installed.txt" (
    echo Первый запуск: готовлю окружение, это займёт около минуты...
    %PY% -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
    echo ok> ".venv\installed.txt"
)
start "" ".venv\Scripts\pythonw.exe" -m arc_overlay
exit /b 0

:error
echo.
echo Не удалось подготовить окружение.
echo Проверь, что установлен Python 3.11+ с python.org: открой cmd и набери  py --version
pause
