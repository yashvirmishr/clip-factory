@echo off
REM Clip Factory - serve the built UI and API from one Python process.
REM Pass --rebuild to rebuild the UI even when web\dist already exists.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run scripts\install.ps1 first.
  exit /b 1
)

if not exist "web\dist\index.html" goto build
if /I "%~1"=="--rebuild" goto build
echo Using the existing UI build ^(pass --rebuild to rebuild^).
goto serve

:build
echo Building the UI...
set "BUILDTMP=%CD%\.buildtmp"
if not exist "%BUILDTMP%" mkdir "%BUILDTMP%"
pushd web
set "TEMP=%BUILDTMP%"
set "TMP=%BUILDTMP%"
call npm run build
set "BUILD=%ERRORLEVEL%"
popd
if exist "%BUILDTMP%" rmdir /s /q "%BUILDTMP%"
if not "%BUILD%"=="0" (
  echo UI build failed.
  exit /b 1
)

:serve
set PYTHONPATH=backend
set CLIPPER_DATA_DIR=%CD%\data
echo Serving http://127.0.0.1:8756
start "" http://127.0.0.1:8756/
.venv\Scripts\python.exe -m clipper --port 8756
endlocal
