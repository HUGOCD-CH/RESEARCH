@echo off
REM Start Chrome with remote debugging enabled so the app can attach to it.
REM After Chrome opens, navigate to webmail.medtronic.com and log in,
REM then click "Connect to Running Chrome" in the app.

set CHROME_PATH=
for %%p in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do (
  if not defined CHROME_PATH if exist %%p set CHROME_PATH=%%~p
)

if not defined CHROME_PATH (
  echo Chrome not found. Please update CHROME_PATH in this script.
  pause
  exit /b 1
)

echo Starting Chrome with remote debugging on port 9222...
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --no-first-run https://webmail.medtronic.com
