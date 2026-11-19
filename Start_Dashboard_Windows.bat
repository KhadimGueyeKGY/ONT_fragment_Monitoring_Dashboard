@echo off
setlocal
title ONT Fragment Monitoring Dashboard
cd /d "%~dp0"

where wsl.exe >nul 2>&1 || goto nowsl
wsl.exe -l -q >nul 2>&1 || goto nowsl
wsl.exe -e bash -c "exit 0" >nul 2>&1 || goto nobash

wsl.exe --cd "%~dp0." -- bash ./app/bootstrap.sh
if errorlevel 1 (
  echo.
  echo   The dashboard stopped with an error. Read the message above.
  pause
)
exit /b

:nobash
echo.
echo   WSL is installed, but its default Linux system cannot run the dashboard.
echo   Make Ubuntu the default one by typing this command in a Command Prompt:
echo.
echo       wsl --set-default Ubuntu
echo.
echo   If Ubuntu is not installed, type:  wsl --install -d Ubuntu
pause
exit /b

:nowsl
echo.
echo   The dashboard needs WSL (Windows Subsystem for Linux), which is not installed.
echo   It is installed once, needs administrator rights and a restart of the computer.
echo.
choice /c YN /m "  Install WSL now"
if errorlevel 2 exit /b
powershell -NoProfile -Command "Start-Process wsl.exe -ArgumentList '--install','-d','Ubuntu' -Verb RunAs"
echo.
echo   Follow the installation window. When it is finished, restart the computer,
echo   open Ubuntu once from the Start menu to create a user, then double-click this file again.
pause
