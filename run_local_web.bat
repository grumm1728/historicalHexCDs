@echo off
setlocal
cd /d "%~dp0"
echo Serving web app at http://localhost:8000
echo Press Ctrl+C to stop.
start "" http://localhost:8000
python -m http.server 8000 --directory web

