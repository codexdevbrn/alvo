<#
.SYNOPSIS
    Gera o pacote distribuível do Prisma e os arquivos que vão para o canal de
    atualização.

.DESCRIPTION
    Ordem obrigatória: o frontend é buildado ANTES do PyInstaller, porque o
    dashboard/dist entra embutido no pacote. Empacotar com um dist velho passa
    despercebido — o app abre normalmente, só com a interface da versão anterior.

    Saída em dist_release/:
      Prisma-<versao>.zip   pacote completo, o que vai para o canal
      version.json          metadados que o app lê para detectar release nova
      Prisma/               pasta descompactada, para testar sem instalar

.PARAMETER PularFrontend
    Reaproveita o dashboard/dist existente. Só para iterar no empacotamento sem
    esperar o build do Vite — nunca para gerar release.

.PARAMETER Notas
    Uma linha sobre o que mudou, exibida ao usuário junto do aviso de atualização.
    Vazio deixa o aviso sem explicação, o que é pior para quem vai clicar.

.EXAMPLE
    .\build.ps1 -Notas "Caminhos padrão: máquina nova não precisa configurar."
#>
[CmdletBinding()]
param(
    [switch]$PularFrontend,
    [string]$Notas = ''
)

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot

function Etapa($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }

# A versão sai de backend/versao.py, a fonte única — assim o nome do zip e o
# version.json nunca divergem do número que o app reporta.
$versao = (python -c "import sys; sys.path.insert(0, r'$raiz\backend'); import versao; print(versao.VERSAO)").Trim()
if (-not $versao) { throw "Não foi possível ler VERSAO de backend/versao.py." }
Write-Host "Prisma v$versao" -ForegroundColor Green

if (-not $PularFrontend) {
    Etapa "Frontend (vite build)"
    Push-Location (Join-Path $raiz 'dashboard')
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build falhou." }
    } finally { Pop-Location }
} else {
    Write-Warning "Frontend pulado: o pacote vai levar o dashboard/dist atual."
}

Etapa "Testes do backend"
Push-Location (Join-Path $raiz 'backend')
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Testes falharam — release abortada." }
} finally { Pop-Location }

Etapa "PyInstaller"
$distPy = Join-Path $raiz 'dist_pyinstaller'
python -m PyInstaller (Join-Path $raiz 'prisma.spec') --noconfirm `
    --distpath $distPy --workpath (Join-Path $raiz 'build_pyinstaller')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou." }

$pacote = Join-Path $distPy 'Prisma'
if (-not (Test-Path (Join-Path $pacote 'Prisma.exe'))) { throw "Prisma.exe não foi gerado." }

Etapa "PyInstaller (atualizador)"
# Empacotado separado porque no Windows um executável em uso não sobrescreve a si
# mesmo. Vai para dentro do pacote: é o Prisma.exe que o invoca, ao seu lado.
python -m PyInstaller (Join-Path $raiz 'atualizador.spec') --noconfirm `
    --distpath $distPy --workpath (Join-Path $raiz 'build_pyinstaller')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller do atualizador falhou." }

$atualizador = Join-Path $distPy 'atualizador.exe'
if (-not (Test-Path $atualizador)) { throw "atualizador.exe não foi gerado." }
Copy-Item $atualizador -Destination $pacote -Force

Etapa "Empacotando release"
$release = Join-Path $raiz 'dist_release'
New-Item -ItemType Directory -Force -Path $release | Out-Null
$zip = Join-Path $release "Prisma-$versao.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $pacote '*') -DestinationPath $zip -CompressionLevel Optimal

$info = Get-Item $zip
# sha256 + tamanho são o que permite ao app recusar um zip que o OneDrive ainda
# não sincronizou por inteiro (placeholder de 0 byte ou download parcial).
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
[ordered]@{
    versao   = $versao
    arquivo  = $info.Name
    sha256   = $hash
    tamanho  = $info.Length
    data     = (Get-Date -Format 'yyyy-MM-dd')
    notas    = $Notas
} | ConvertTo-Json | Set-Content -Path (Join-Path $release 'version.json') -Encoding UTF8
if (-not $Notas) { Write-Warning "Release sem notas. Use -Notas para explicar ao usuário o que muda." }

Etapa "Instalador (Inno Setup)"
# Opcional de propósito: o zip acima já é uma distribuição completa. Sem o Inno
# instalado o build segue e só avisa, em vez de derrubar a release.
# O caminho varia: winget sem elevação instala por usuário em
# %LOCALAPPDATA%\Programs; o instalador oficial com admin vai para Program Files.
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }

if (-not $iscc) {
    Write-Warning "Inno Setup não encontrado — instalador não gerado. Instale com: winget install JRSoftware.InnoSetup"
} else {
    & $iscc "/DVersaoApp=$versao" "/DPastaPacote=$pacote" (Join-Path $raiz 'instalador\prisma.iss') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ISCC falhou." }
    $instalador = Join-Path $release "Prisma-$versao-instalador.exe"
    if (-not (Test-Path $instalador)) { throw "O instalador não foi gerado." }
    Write-Host ("Instalador: {0} ({1:N0} MB)" -f $instalador, ((Get-Item $instalador).Length / 1MB))
}

Etapa "Pronto"
Write-Host ("Pacote: {0} ({1:N0} MB)" -f $zip, ($info.Length / 1MB))
Write-Host "sha256: $hash"
Write-Host ""
Write-Host "Para publicar: copie Prisma-$versao.zip e version.json para a pasta" -ForegroundColor Yellow
Write-Host "de atualizacoes no OneDrive. Preencha 'notas' no version.json antes." -ForegroundColor Yellow
