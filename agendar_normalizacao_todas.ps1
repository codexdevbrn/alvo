# Registra ou atualiza o lote noturno: normalizacao seguida das analises IA.
# As analises usam o Claude pela assinatura (Claude Code logado neste usuario);
# a chave do Ollama Cloud (configurar_ollama.ps1) e reserva opcional.
[CmdletBinding()]
param(
    [string]$NomeTarefa = "Prisma-NormalizarTodasEmpresas",
    [string]$Hora = "02:00",
    [switch]$Remover
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$orquestrador = Join-Path $raiz "executar_lote_noturno.ps1"
$arquivoSegredo = Join-Path $env:LOCALAPPDATA "Prisma\secrets\ollama_api_key.dpapi"

if ($Remover) {
    Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa removida: $NomeTarefa"
    exit 0
}

if (-not (Test-Path -LiteralPath $orquestrador)) {
    throw "Orquestrador nao encontrado: $orquestrador"
}
$temClaude = [bool](Get-Command claude -ErrorAction SilentlyContinue) -or
    (Test-Path -LiteralPath (Join-Path $env:USERPROFILE ".local\bin\claude.exe"))
if (-not $temClaude -and -not (Test-Path -LiteralPath $arquivoSegredo)) {
    throw "Sem Claude Code logado e sem chave Ollama. Instale o Claude Code ou execute .\configurar_ollama.ps1 antes de agendar."
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python nao esta no PATH. Instale ou configure antes de agendar."
}
$powershell = (Get-Command PowerShell.exe -ErrorAction Stop).Source

Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false -ErrorAction SilentlyContinue

$argumentos = "-NoProfile -ExecutionPolicy Bypass -File `"$orquestrador`" -Python `"$($python.Source)`""
$acao = New-ScheduledTaskAction -Execute $powershell -Argument $argumentos -WorkingDirectory $raiz
# Segunda a sexta, depois do fechamento e da normalizacao das bases.
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
    -Description "Normaliza empresas e atualiza dossies executivos via Claude (Ollama Cloud de reserva) (seg-sex)." `
    -Force | Out-Null

Write-Host "Tarefa registrada: $NomeTarefa"
Write-Host "  Quando:  segunda a sexta as $Hora"
Write-Host "  Comando: $powershell $argumentos"
Write-Host "  Teste:   Start-ScheduledTask -TaskName $NomeTarefa"
Write-Host "  Remover: powershell -File .\agendar_normalizacao_todas.ps1 -Remover"
