# Orquestra normalizacao e analises IA. A chave so entra no ambiente do processo de analise.
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SemNormalizacao,
    [switch]$DryRunAnalises
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $raiz "logs_agendador"
$arquivoSegredo = Join-Path $env:LOCALAPPDATA "Prisma\secrets\ollama_api_key.dpapi"
$normalizador = Join-Path $raiz "normalizar_todas_empresas.py"
$analisador = Join-Path $raiz "gerar_analises_ia.py"
$inicioUtc = [DateTime]::UtcNow
$codigoNormalizacao = 0
$codigoAnalises = 0
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

"[$(Get-Date -Format o)] Inicio lote noturno" | Add-Content -LiteralPath $logResumo -Encoding UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

try {
    if (-not $SemNormalizacao) {
        if (-not (Test-Path -LiteralPath $normalizador)) {
            throw "Normalizador nao encontrado: $normalizador"
        }

        "[$(Get-Date -Format o)] Inicio normalizacao" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
        $codigoNormalizacao = Invoke-PythonComLog -Argumentos @($normalizador)
        "[$(Get-Date -Format o)] Fim normalizacao exit=$codigoNormalizacao" | Add-Content -LiteralPath $logDetalhado -Encoding UTF8
    }

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
    # Nao registrar excecoes internas que possam conter valores sensiveis.
    "[$(Get-Date -Format o)] Falha de configuracao no lote" | Add-Content -LiteralPath $logResumo -Encoding UTF8
    [Console]::Error.WriteLine("Falha de configuracao. Consulte os arquivos esperados e a chave DPAPI.")
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
if ($codigoNormalizacao -ne 0 -or $codigoAnalises -ne 0) {
    $codigoFinal = 1
}
"[$(Get-Date -Format o)] Fim lote normalizacao=$codigoNormalizacao analises=$codigoAnalises exit=$codigoFinal" |
    Add-Content -LiteralPath $logResumo -Encoding UTF8
exit $codigoFinal
