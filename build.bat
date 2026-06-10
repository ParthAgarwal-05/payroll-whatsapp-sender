@echo off
REM Build script for Payroll WhatsApp Sender
REM Prerequisites: Python 3.11+, PyInstaller

echo ============================================
echo   Payroll WhatsApp Sender - Build Script
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1 || (echo ERROR: Python not found in PATH && exit /b 1)

REM Create and activate a virtual environment for reproducible builds
echo Setting up build environment...
if not exist build_venv (
    python -m venv build_venv
)
call build_venv\Scripts\activate.bat

REM Install/upgrade dependencies
echo Installing dependencies...
pip install -r requirements.lock
pip install pyinstaller

REM Clean previous builds
echo Cleaning previous builds...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Build
echo Building executable...
pyinstaller payroll.spec --clean

echo.
echo Build complete! Output in dist/PayrollWhatsAppSender/
pause
