@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-backend.ps1" %*
exit /b %ERRORLEVEL%
