@echo off
rem Starts the Notarius installer.  Kept ASCII-only on purpose.
setlocal
if not exist "%~dp0app\windows\install.ps1" (
    echo.
    echo   Extraia o arquivo .zip antes de instalar:
    echo   clique com o botao direito no .zip e escolha "Extrair tudo".
    echo.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\windows\install.ps1" %*
if errorlevel 1 pause
