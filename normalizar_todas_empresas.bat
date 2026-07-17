@echo off
REM Wrapper para o Agendador de Tarefas — normalização noturna de todas as empresas.
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "LOGDIR=%~dp0logs_agendador"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

set "STAMP=%DATE:~6,4%-%DATE:~3,2%-%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "STAMP=%STAMP: =0%"

echo [%DATE% %TIME%] Inicio normalizar_todas_empresas >> "%LOGDIR%\agendador.log"
python "%~dp0normalizar_todas_empresas.py" %*
set "ERR=%ERRORLEVEL%"
echo [%DATE% %TIME%] Fim exit=%ERR% >> "%LOGDIR%\agendador.log"
exit /b %ERR%
