# Orquestra normalizacao (corte D-1), base CNPJ, dump de precificacao, preparo das telas e analises IA. A chave so entra no ambiente do processo de analise.
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SemNormalizacao,
    [switch]$SemPrecificacao,
    [switch]$SemTelas,
    [string]$AguardarFonteAte = "",
    [switch]$DryRunAnalises
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $raiz "logs_agendador"
$arquivoSegredo = Join-Path $env:LOCALAPPDATA "Prisma\secrets\ollama_api_key.dpapi"
$normalizador = Join-Path $raiz "normalizar_todas_empresas.py"
$analisador = Join-Path $raiz "gerar_analises_ia.py"
$precificacao = Join-Path $raiz "precificacao_do_postgres.py"
$baseEmpresas = Join-Path $raiz "montar_base_empresas.py"
$preparoTelas = Join-Path $raiz "preparar_telas.py"
$aguardarFonte = Join-Path $raiz "aguardar_fonte.py"
$inicioUtc = [DateTime]::UtcNow
$codigoNormalizacao = 0
$codigoAnalises = 0
$codigoPrecificacao = 0
$codigoTelas = 0
$ponte = [IntPtr]::Zero
$pythonUtf8Anterior = $env:PYTHONUTF8
$pythonIoAnterior = $env:PYTHONIOENCODING

New-Item -ItemType Directory -Path $logs -Force | Out-Null
$logResumo = Join-Path $logs "lote_noturno.log"
$logDetalhado = Join-Path $logs "lote_noturno_detalhado.log"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $comandoPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $comandoPython) {
        throw "Python nao encontrado no PATH."
    }
    $Python = $comandoPython.Source
}

if (-not (Test-Path -LiteralPath $analisador)) {
    throw "Gerador de analises nao encontrado: $analisador"
}

function Invoke-PythonComLog {
    param([string[]]$Argumentos)

    # Windows PowerShell transforma stderr nativo em ErrorRecord. Isso e saida
    # operacional valida; o codigo de saida do Python e a fonte de verdade.
    $preferenciaAnterior = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Python @Argumentos 2>&1 |
            Out-File -LiteralPath $logDetalhado -Append -Encoding UTF8
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $preferenciaAnterior
    }
}

# Uma passada por vez. As tarefas das 05:30, 13:00 e 18:00 (e rodadas a mao) podem
# se sobrepor quando uma demora; a segunda encontrava o log detalhado aberto pela
# primeira e morria em "Falha de configuracao" (24/09/2026, 13:00). Mutex nomeado
# da sessao: some sozinho se o processo morrer; o Abandoned e tratado como livre.
$mutexLote = New-Object System.Threading.Mutex($false, "Local\Prisma-LoteNoturno")
$temMutex = $false
try {
    $temMutex = $mutexLote.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $temMutex = $true
}
if (-not $temMutex) {
    "[$(Get-Date -Format o)] Lote anterior ainda em andamento; esta passada foi pulada" | Add-Content -LiteralPath $logResumo -Encoding UTF8
    exit 0
}

"[$(Get-Date -Format o)] Inicio lote noturno" | Add-Content -LiteralPath $logResumo -Encoding UTF8
$etapa = "inicio"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

try {
    $etapa = "aguardar fonte"
    if ($AguardarFonteAte) {
        # Passada da madrugada: espera os parquets do dia (com o D-1) chegarem.
        # Estourar o prazo nao e falha: segue com o que tem e a passada da tarde completa.
        "[$(Get-Date -Format o)] Inicio aguardar fonte ate $AguardarFonteAte" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        $codigoAguardar = Invoke-PythonComLog -Argumentos @($aguardarFonte, "--ate", $AguardarFonteAte)
        "[$(Get-Date -Format o)] Fim aguardar fonte exit=$codigoAguardar" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
    }

    if (-not $SemNormalizacao) {
        if (-not (Test-Path -LiteralPath $normalizador)) {
            throw "Normalizador nao encontrado: $normalizador"
        }

        $etapa = "normalizacao"
        "[$(Get-Date -Format o)] Inicio normalizacao" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        $codigoNormalizacao = Invoke-PythonComLog -Argumentos @($normalizador)
        "[$(Get-Date -Format o)] Fim normalizacao exit=$codigoNormalizacao" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
    }

    if (-not $SemPrecificacao) {
        # Rodada nova no PRICE so entrava quando alguem rodava o script a mao.
        # Empresa sem precificacao nova custa uma agregacao no banco, nao download.
        # Falha aqui (banco fora do ar) nao impede as analises: entra so no exit.
        # Base empresa/loja/CNPJ do DW primeiro: e ela que diz de quais CNPJs
        # buscar a precificacao. Falha aqui so deixa o lote na base de ontem.
        $etapa = "base empresas"
        "[$(Get-Date -Format o)] Inicio base empresas" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        $codigoBase = Invoke-PythonComLog -Argumentos @($baseEmpresas)
        "[$(Get-Date -Format o)] Fim base empresas exit=$codigoBase" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        if ($codigoBase -ne 0) { $codigoPrecificacao = $codigoBase }

        $etapa = "precificacao"
        "[$(Get-Date -Format o)] Inicio precificacao" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        $codigoDump = Invoke-PythonComLog -Argumentos @($precificacao)
        if ($codigoDump -ne 0) { $codigoPrecificacao = $codigoDump }
        "[$(Get-Date -Format o)] Fim precificacao exit=$codigoDump" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
    }

    if (-not $SemTelas) {
        # Clientes, Diagnostico, Vendedores, Estoque e Pos-precificacao prontos em
        # disco: a primeira abertura do dia deixa de recalcular. Depois da
        # precificacao, porque a Pos-precificacao le o dump que ela acabou de gravar.
        $etapa = "preparo telas"
        "[$(Get-Date -Format o)] Inicio preparo telas" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        $codigoTelas = Invoke-PythonComLog -Argumentos @($preparoTelas)
        "[$(Get-Date -Format o)] Fim preparo telas exit=$codigoTelas" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
    }

    $etapa = "chave e analises IA"
    $argumentosAnalise = @($analisador)
    if (-not $SemNormalizacao) {
        # Impede analise com summary antigo quando a normalizacao do cliente falhou.
        $argumentosAnalise += @("--fresh-since", $inicioUtc.ToString("o"))
    }
    if ($DryRunAnalises) {
        $argumentosAnalise += "--dry-run"
    } else {
        if (-not (Test-Path -LiteralPath $arquivoSegredo)) {
            throw "Chave Ollama ausente. Execute configurar_ollama.ps1 primeiro."
        }

        $blobProtegido = (Get-Content -Raw -LiteralPath $arquivoSegredo).Trim()
        $segredo = ConvertTo-SecureString -String $blobProtegido
        $ponte = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($segredo)
        $env:OLLAMA_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ponte)
    }

    "[$(Get-Date -Format o)] Inicio analises IA" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
    $codigoAnalises = Invoke-PythonComLog -Argumentos $argumentosAnalise
    "[$(Get-Date -Format o)] Fim analises IA exit=$codigoAnalises" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
} catch {
    # So a etapa e o tipo do erro: a mensagem pode carregar valor sensivel (chave).
    $tipoErro = $_.Exception.GetType().Name
    "[$(Get-Date -Format o)] Falha no lote na etapa '$etapa' ($tipoErro)" | Add-Content -LiteralPath $logResumo -Encoding UTF8
    [Console]::Error.WriteLine("Falha no lote na etapa '$etapa' ($tipoErro).")
    $mutexLote.ReleaseMutex()
    exit 2
} finally {
    Remove-Item Env:OLLAMA_API_KEY -ErrorAction SilentlyContinue
    if ($null -eq $pythonUtf8Anterior) {
        Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONUTF8 = $pythonUtf8Anterior
    }
    if ($null -eq $pythonIoAnterior) {
        Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONIOENCODING = $pythonIoAnterior
    }
    if ($ponte -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ponte)
    }
}

$codigoFinal = 0
if ($codigoNormalizacao -ne 0 -or $codigoPrecificacao -ne 0 -or $codigoTelas -ne 0 -or $codigoAnalises -ne 0) {
    $codigoFinal = 1
}
"[$(Get-Date -Format o)] Fim lote normalizacao=$codigoNormalizacao precificacao=$codigoPrecificacao telas=$codigoTelas analises=$codigoAnalises exit=$codigoFinal" |
    Add-Content -LiteralPath $logResumo -Encoding UTF8
$mutexLote.ReleaseMutex()
exit $codigoFinal
