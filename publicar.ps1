<#
.SYNOPSIS
    Publica a release no canal de atualizacao e apaga as antigas.

.DESCRIPTION
    Substitui a copia manual de dist_release para o OneDrive, que era o motivo
    de o canal acumular uma release inteira por versao: nada removia as
    anteriores, e cada uma pesa ~81 MB de zip mais ~89 MB de instalador.

    O canal so precisa do version.json e do zip que ele nomeia. Uma maquina em
    1.0.9 atualiza direto para a mais nova — nao existe salto intermediario que
    justifique guardar as do meio. -Manter deixa N versoes anteriores como
    escada de volta caso a nova saia com defeito.

    Duas pastas, de propositos diferentes:

      <canal>\..\   instaladores, para primeira instalacao numa maquina nova
      <canal>\      version.json + zip, o que o app le para se atualizar

    A ordem de copia nao e arbitraria: o zip vai primeiro e o version.json
    depois. Publicar o manifesto antes deixaria uma janela em que todo app da
    rede ve versao nova apontando para um zip ausente ou pela metade.

    Sem -Executar o script so mostra o que faria. Apagar em pasta compartilhada
    e o tipo de coisa que se confere antes.

.PARAMETER Canal
    Pasta do canal (a que tem version.json). Vazio usa o padrao do OneDrive
    corporativo, o mesmo que o app resolve em backend/caminhos_padrao.py.

.PARAMETER Manter
    Quantas versoes anteriores preservar, alem da que esta sendo publicada.

.PARAMETER Executar
    Copia e apaga de verdade. Sem isto, so relatorio.

.EXAMPLE
    .\publicar.ps1
    .\publicar.ps1 -Executar
#>
[CmdletBinding()]
param(
    [string]$Canal = '',
    [int]$Manter = 1,
    [switch]$Executar
)

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot

function Etapa($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }

# "Prisma-1.0.11.zip" -> [version]1.0.11. Comparar os nomes como texto erraria:
# em ordem alfabetica "1.0.9" vem depois de "1.0.11".
function Versao-DoNome([string]$nome) {
    if ($nome -match 'Prisma-(\d+(?:\.\d+)*)') {
        try { return [version]$Matches[1] } catch { return $null }
    }
    return $null
}

# Mantem os $Manter + 1 arquivos de maior versao (a publicada inclusive) e
# devolve os demais. Arquivo sem versao no nome nunca entra na lista de
# remocao: se alguem pos algo a mao ali, quem decide e a pessoa.
function Obsoletos($arquivos, [version]$atual, [int]$manter) {
    $comVersao = $arquivos |
        ForEach-Object { [pscustomobject]@{ Arquivo = $_; V = (Versao-DoNome $_.Name) } } |
        Where-Object { $_.V -ne $null }
    $todas = @($atual)
    foreach ($item in $comVersao) { $todas += $item.V }
    $manterVersoes = @($todas | Sort-Object -Unique -Descending | Select-Object -First ($manter + 1))
    return $comVersao | Where-Object { $manterVersoes -notcontains $_.V } |
        ForEach-Object { $_.Arquivo }
}

$release = Join-Path $raiz 'dist_release'
$manifestoLocal = Join-Path $release 'version.json'
if (-not (Test-Path $manifestoLocal)) {
    throw "Nao ha $manifestoLocal. Rode .\build.ps1 antes de publicar."
}

$manifesto = Get-Content $manifestoLocal -Raw -Encoding UTF8 | ConvertFrom-Json
$versao = $manifesto.versao
$nomeZip = $manifesto.arquivo
$zipLocal = Join-Path $release $nomeZip
if (-not (Test-Path $zipLocal)) { throw "O manifesto aponta para '$nomeZip', que nao existe em dist_release." }

# O manifesto e o app comparam versao com backend/versao.py; se o build ficou
# para tras, publicar entrega um canal que nunca oferece atualizacao.
$versaoFonte = (python -c "import sys; sys.path.insert(0, r'$raiz\backend'); import versao; print(versao.VERSAO)").Trim()
if ($versaoFonte -ne $versao) {
    throw "version.json diz $versao e backend/versao.py diz $versaoFonte. Rode .\build.ps1 de novo."
}

$hashLocal = (Get-FileHash $zipLocal -Algorithm SHA256).Hash.ToLower()
if ($hashLocal -ne $manifesto.sha256) {
    throw "O sha256 de $nomeZip nao casa com o do version.json. Rode .\build.ps1 de novo."
}

if (-not $Canal) {
    $Canal = (python -c "import sys; sys.path.insert(0, r'$raiz\backend'); import caminhos_padrao; print(caminhos_padrao.atualizacoes() or '')").Trim()
    if (-not $Canal) {
        throw "Canal padrao nao encontrado no OneDrive. Informe com -Canal '<pasta>'."
    }
}
if (-not (Test-Path $Canal -PathType Container)) { throw "Canal nao encontrado: $Canal" }
$pastaInstalador = Split-Path $Canal -Parent

$versaoAtual = [version]$versao
$instaladorLocal = Join-Path $release "Prisma-$versao-instalador.exe"

Write-Host "Prisma v$versao" -ForegroundColor Green
Write-Host "Canal:        $Canal"
Write-Host "Instaladores: $pastaInstalador"
if (-not $Executar) { Write-Warning "Simulacao. Nada e copiado nem apagado. Use -Executar para valer." }

Etapa "Copiando"
$copias = @(
    [pscustomobject]@{ De = $zipLocal; Para = (Join-Path $Canal $nomeZip) }
)
if (Test-Path $instaladorLocal) {
    $copias += [pscustomobject]@{ De = $instaladorLocal; Para = (Join-Path $pastaInstalador (Split-Path $instaladorLocal -Leaf)) }
} else {
    Write-Warning "Instalador nao encontrado em dist_release (Inno Setup ausente no build?). Publicando so o zip."
}
# version.json por ultimo, sempre.
$copias += [pscustomobject]@{ De = $manifestoLocal; Para = (Join-Path $Canal 'version.json') }

foreach ($c in $copias) {
    $mb = (Get-Item $c.De).Length / 1MB
    Write-Host ("  {0} -> {1} ({2:N0} MB)" -f (Split-Path $c.De -Leaf), (Split-Path $c.Para -Parent), $mb)
    if ($Executar) { Copy-Item $c.De -Destination $c.Para -Force }
}

Etapa "Removendo releases antigas"
$aRemover = @()
# Zip antigo no canal.
$aRemover += Obsoletos (Get-ChildItem $Canal -File -Filter 'Prisma-*.zip' -ErrorAction SilentlyContinue) $versaoAtual $Manter
# Instalador antigo na pasta de cima.
$aRemover += Obsoletos (Get-ChildItem $pastaInstalador -File -Filter 'Prisma-*-instalador.exe' -ErrorAction SilentlyContinue) $versaoAtual $Manter
# Instalador dentro do canal e sempre resto: o app nunca o le, e a primeira
# instalacao acontece pela pasta de cima. Mesmo o da versao atual sai daqui.
$aRemover += Get-ChildItem $Canal -File -Filter 'Prisma-*-instalador.exe' -ErrorAction SilentlyContinue

if (-not $aRemover) {
    Write-Host "  nada a remover."
} else {
    $total = ($aRemover | Measure-Object -Property Length -Sum).Sum / 1MB
    foreach ($f in $aRemover) {
        Write-Host ("  {0}  ({1:N0} MB)" -f $f.FullName, ($f.Length / 1MB)) -ForegroundColor DarkYellow
        if ($Executar) { Remove-Item $f.FullName -Force }
    }
    Write-Host ("  {0} arquivo(s), {1:N0} MB" -f $aRemover.Count, $total)
}

Etapa "Pronto"
if ($Executar) {
    Write-Host "Publicado. Guardando a versao publicada e as $Manter anterior(es)." -ForegroundColor Green
    Write-Host "O OneDrive precisa terminar de sincronizar antes de as maquinas verem a release." -ForegroundColor Yellow
} else {
    Write-Host "Simulacao concluida. Rode de novo com -Executar para aplicar." -ForegroundColor Yellow
}
