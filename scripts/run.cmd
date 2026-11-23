@echo off
REM Clip Factory - build the UI and serve everything from one Python process.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. See README.md
  exit /b 1
)

pushd web
call npm run build || (popd & exit /b 1)
popd

set PYTHONPATH=backend
set CLIPPER_DATA_DIR=%CD%\data
echo Serving http://127.0.0.1:8756
start "" http://127.0.0.1:8756/
.venv\Scripts\python.exe -m clipper --port 8756
endlocal
