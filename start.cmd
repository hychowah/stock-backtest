@echo off
setlocal
set PYTHONUTF8=1
where py >nul 2>&1
if errorlevel 1 goto python
py -3 "%~dp0tools\deploy.py" --native-launch %*
goto finish
:python
where python3 >nul 2>&1
if errorlevel 1 goto fallback
python3 "%~dp0tools\deploy.py" --native-launch %*
goto finish
:fallback
python "%~dp0tools\deploy.py" --native-launch %*
:finish
if errorlevel 1 pause
