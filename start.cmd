@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto python
py -3 website\serve.py %*
goto finish
:python
where python3 >nul 2>&1
if errorlevel 1 goto fallback
python3 website\serve.py %*
goto finish
:fallback
python website\serve.py %*
:finish
if errorlevel 1 pause
