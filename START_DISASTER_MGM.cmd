@echo off
setlocal
set "PROJECT_DIR=%~dp0"

if not exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
  echo Python environment missing. Run: py -m venv .venv
  pause
  exit /b 1
)
start "DISASTER_MGM API" /D "%PROJECT_DIR%" "%PROJECT_DIR%.venv\Scripts\python.exe" backend\api.py
start "DISASTER_MGM UI" /D "%PROJECT_DIR%frontend" cmd /c npm run dev -- --host 127.0.0.1

timeout /t 3 /nobreak >nul
start "" http://localhost:5173
endlocal
