# Registra (ou atualiza) a tarefa agendada de normalização noturna.
# Requer PowerShell com permissão para criar tarefas (idealmente Admin).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\agendar_normalizacao_todas.ps1
#   powershell -ExecutionPolicy Bypass -File .\agendar_normalizacao_todas.ps1 -Hora "04:00"
#   powershell -ExecutionPolicy Bypass -File .\agendar_normalizacao_todas.ps1 -Remover

param(
    [string]$NomeTarefa = "Prisma-NormalizarTodasEmpresas",
    [string]$Hora = "02:00",
    [switch]$Remover
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $raiz "normalizar_todas_empresas.bat"

if (-not (Test-Path $bat)) {
    throw "Não encontrado: $bat"
}

if ($Remover) {
    Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa removida: $NomeTarefa"
    exit 0
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "python não está no PATH. Instale/configure antes de agendar."
}

Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false -ErrorAction SilentlyContinue

$acao = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $raiz
# seg=Monday ... sex=Friday (madrugada antes do dia útil)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Hora
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $NomeTarefa `
    -Action $acao `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Normaliza BI→Base.csv (+ Liquidez) de todas as empresas do Prisma (madrugada seg-sex)." `
    -Force | Out-Null

Write-Host "Tarefa registrada: $NomeTarefa"
Write-Host "  Quando:  seg-sex as $Hora"
Write-Host "  Comando: $bat"
Write-Host "  Teste:   Start-ScheduledTask -TaskName $NomeTarefa"
Write-Host "  Remover: powershell -File .\agendar_normalizacao_todas.ps1 -Remover"
