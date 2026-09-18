@echo off
setlocal
cd /d "%~dp0"

rem This batch file is kept as a console fallback. For a completely hidden launch,
rem double-click LaunchOrderAudit.lnk (or launch_hidden.vbs) instead.
wscript.exe "%~dp0launch_hidden.vbs"

endlocal
exit /b 0
