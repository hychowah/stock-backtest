@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto python
py -3 website\serve.py --managed %*
goto finish
:python
where python3 >nul 2>&1
if errorlevel 1 goto fallback
python3 website\serve.py --managed %*
goto finish
:fallback
python website\serve.py --managed %*
:finish
if errorlevel 1 pause
