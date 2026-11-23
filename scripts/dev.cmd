@echo off
REM Clip Factory - start the API and the UI together (two windows).
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run:  py -3 -m venv .venv
  echo                then:  .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

start "Clip Factory API" cmd /k "set PYTHONPATH=backend&& set CLIPPER_DATA_DIR=%CD%\data&& .venv\Scripts\python.exe -m clipper --port 8756"
start "Clip Factory UI" cmd /k "cd web && npm run dev"

echo API  http://127.0.0.1:8756
echo UI   http://localhost:5173
endlocal
