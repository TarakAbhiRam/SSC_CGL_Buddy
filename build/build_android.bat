@echo off
setlocal
cd /d "%~dp0..\android"

where gradle >nul 2>nul
if errorlevel 1 (
  if exist gradlew.bat (
    call gradlew.bat :app:assembleDebug
  ) else (
    echo Gradle is required. Install Android Studio or Gradle, then rerun this script.
    exit /b 1
  )
) else (
  gradle :app:assembleDebug
)

echo Built android\app\build\outputs\apk\debug\app-debug.apk
