@echo off
REM =========================================================================
REM  start_chrome.bat — Opens a debug Chrome window for the Outlook Viewer
REM
REM  This opens a SEPARATE Chrome window alongside your existing Chrome.
REM  Your normal Chrome stays open and is not affected.
REM  Sign in to webmail in the new window, then click "Connect" in the app.
REM  (MFA is only needed once — the session is saved for next time.)
REM =========================================================================

set CHROME_PATH=
for %%p in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do (
  if not defined CHROME_PATH if exist %%p set CHROME_PATH=%%~p
)

if not defined CHROME_PATH (
  echo Chrome not found. Install Google Chrome or update CHROME_PATH in this script.
  pause
  exit /b 1
)

REM Check if port 9222 is already in use
netstat -an 2>nul | findstr ":9222 " >nul 2>&1
if %errorlevel% == 0 (
  echo Chrome debug port is already open on port 9222.
  echo Go back to the app and click "Connect to Running Chrome".
  timeout /t 5
  exit /b 0
)

REM Use a dedicated profile so this instance can run alongside your normal Chrome
set PROFILE_DIR=%LOCALAPPDATA%\OutlookDebugChrome

echo Opening debug Chrome window (your normal Chrome stays open)...
echo Profile saved at: %PROFILE_DIR%
echo.
echo After the window opens, sign in to webmail if prompted,
echo then go back to the app and click "Connect to Running Chrome".
echo.

start "" "%CHROME_PATH%" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%PROFILE_DIR%" ^
  --no-first-run ^
  --no-default-browser-check ^
  --ignore-certificate-errors ^
  https://webmail.medtronic.com

timeout /t 3 >nul
