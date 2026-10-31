@echo off
setlocal
rem Portable preview: register only this user's website handoff. No elevation.
reg add "HKCU\Software\Classes\subtitled" /ve /t REG_SZ /d "URL:SubtitleD Companion" /f >nul
if errorlevel 1 goto failed
reg add "HKCU\Software\Classes\subtitled" /v "URL Protocol" /t REG_SZ /d "" /f >nul
if errorlevel 1 goto failed
reg add "HKCU\Software\Classes\subtitled\shell\open\command" /ve /t REG_SZ /d "\"%~dp0SubtitleD-Companion.exe\" --url \"%%1\"" /f >nul
if errorlevel 1 goto failed
start "" "%~dp0SubtitleD-Companion.exe"
exit /b 0
:failed
echo Could not register the companion. Keep the extracted folder and open SubtitleD-Companion.exe directly.
pause
exit /b 1
