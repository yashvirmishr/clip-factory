@echo off
REM Clip Factory - launcher used by the desktop shortcut.
REM run.cmd builds the UI, serves it on 127.0.0.1:8756 and opens the browser.
setlocal
cd /d "%~dp0.."
call "scripts\run.cmd" %*
endlocal
