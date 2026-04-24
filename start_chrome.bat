@echo off
REM =========================================================================
REM  start_chrome.bat — Opens Chrome with remote debugging on port 9222
REM
REM  IMPORTANT: Chrome must NOT already be running when you double-click this.
REM             Close all Chrome windows first, then run this script.
REM             Your session/cookies are saved, so you won't need MFA again.
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
  echo Chrome not found. Please install Google Chrome or update CHROME_PATH in this script.
  pause
  exit /b 1
)

REM Check whether Chrome is already running on port 9222
netstat -an 2>nul | findstr ":9222" >nul 2>&1
if %errorlevel% == 0 (
  echo Chrome is already listening on port 9222. You can go back to the app and click "Try again".
  pause
  exit /b 0
)

REM Check whether any Chrome process is running at all
tasklist /fi "imagename eq chrome.exe" 2>nul | findstr /i "chrome.exe" >nul 2>&1
if %errorlevel% == 0 (
  echo.
  echo WARNING: Chrome is already running.
  echo The --remote-debugging-port flag only works when Chrome starts fresh.
  echo.
  echo Please close ALL Chrome windows and then run this script again.
  echo.
  pause
  exit /b 1
)

echo Starting Chrome with remote debugging on port 9222...
echo Your saved session will be used — no need to log in again.
echo.
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --no-first-run https://webmail.medtronic.com
