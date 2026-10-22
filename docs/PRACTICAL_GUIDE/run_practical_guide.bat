@echo off
REM ============================================================
REM PlanX Practical Guide - screenshot generator (Windows / OSGeo4W)
REM ============================================================
REM Runs every PlanX algorithm headless in QGIS on the real Utrecht
REM open-data set and writes the 4-panel captures.
REM
REM Prerequisites:
REM   - QGIS 3.44 LTR / 4.2 via OSGeo4W
REM   - the data set under C:\Users\YE\Downloads\planx_nl_data
REM
REM Usage:
REM   run_practical_guide.bat --all
REM   run_practical_guide.bat --algo serviceareas
REM ============================================================
setlocal

set QGIS_PYTHON=
if exist "C:\OSGeo4W\bin\python-qgis-ltr.bat" set QGIS_PYTHON=C:\OSGeo4W\bin\python-qgis-ltr.bat
if exist "C:\OSGeo4W64\bin\python-qgis-ltr.bat" set QGIS_PYTHON=C:\OSGeo4W64\bin\python-qgis-ltr.bat
if not defined QGIS_PYTHON (
  echo [ERROR] QGIS Python not found. Install QGIS via OSGeo4W.
  pause & exit /b 1
)

set SCRIPT_DIR=%~dp0
if "%~1"=="" (
  echo Usage: run_practical_guide.bat [--all | --algo ALGO_ID]
  echo.
  echo   --all           run every algorithm (resumes: existing captures are reused)
  echo   --algo <id>     run a single algorithm, e.g. serviceareas
  pause & exit /b 0
)

echo [INFO] Using %QGIS_PYTHON%
call "%QGIS_PYTHON%" -u "%SCRIPT_DIR%scripts\practical_guide_runner_real.py" %*
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% neq 0 (echo [ERROR] exited with %EXIT_CODE%) else (echo [OK] done)
pause
exit /b %EXIT_CODE%
