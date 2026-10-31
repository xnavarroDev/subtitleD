@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto directpython
py -3 "%~dp0local_connector.py" %*
goto finished
:directpython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto missingpython
python "%~dp0local_connector.py" %*
goto finished
:missingpython
echo Python 3.10 or later is needed to run the SubtitleD launcher.
echo Install it from https://www.python.org/downloads/windows/ and enable its PATH option.
echo Then double-click Start-SubtitleD.cmd again.
pause
exit /b 1
:finished
set "SubtitleDExit=%errorlevel%"
pause
exit /b %SubtitleDExit%
