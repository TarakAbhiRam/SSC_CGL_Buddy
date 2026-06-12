@echo off
REM Build the lightweight distributable Windows .exe (run on a Windows machine).
REM Note the ';' separator for --add-data (Windows convention).

cd /d "%~dp0\.."

pyinstaller --noconfirm --windowed --onedir ^
  --name "CGL Buddy" ^
  --add-data "frontend;frontend" ^
  --add-data "data;data" ^
  --collect-data webview ^
  main.py

echo.
echo Built dist\CGL Buddy\CGL Buddy.exe
