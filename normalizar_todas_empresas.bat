@echo off
REM Compatibilidade: orquestra normalização e análises IA pelo PowerShell seguro.
setlocal
cd /d "%~dp0"
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0executar_lote_noturno.ps1" %*
exit /b %ERRORLEVEL%
