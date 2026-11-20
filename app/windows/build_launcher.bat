@echo off
rem Malaria dashboard monitor: builds "Malaria dashboard monitor.exe" with the logo.
rem Author: Khadim Gueye
cd /d "%~dp0..\.."
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize+ /win32icon:img\logo.ico /out:"Malaria dashboard monitor.exe" /r:System.Windows.Forms.dll /r:System.Drawing.dll app\windows\launcher.cs
