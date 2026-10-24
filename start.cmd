@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto python
py -3 tools\deploy.py --native-launch %*
goto finish
:python
where python3 >nul 2>&1
if errorlevel 1 goto fallback
python3 tools\deploy.py --native-launch %*
goto finish
:fallback
python tools\deploy.py --native-launch %*
:finish
if errorlevel 1 pause
