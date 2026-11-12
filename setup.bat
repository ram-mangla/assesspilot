@echo off
REM AssessPilot One-Shot Setup (Windows)
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e . || exit /b 1
python -m playwright install chromium
echo.
echo Setup completed successfully!
echo Activate your environment:
echo   .venv\Scripts\activate.bat
echo Then run:
echo   assesspilot doctor
echo   assesspilot --help
