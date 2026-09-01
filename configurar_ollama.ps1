# Armazena a chave do Ollama Cloud criptografada pelo DPAPI do usuario Windows.
# A chave nunca e recebida por argumento, gravada em log ou salva dentro do repositorio.
[CmdletBinding()]
param(
    [switch]$Remover
)

$ErrorActionPreference = "Stop"
$pastaSegredos = Join-Path $env:LOCALAPPDATA "Prisma\secrets"
$arquivoSegredo = Join-Path $pastaSegredos "ollama_api_key.dpapi"

if ($Remover) {
    if (Test-Path -LiteralPath $arquivoSegredo) {
        Remove-Item -LiteralPath $arquivoSegredo -Force
        Write-Host "Chave Ollama removida."
    } else {
        Write-Host "Nenhuma chave Ollama configurada."
    }
    exit 0
}

$segredo = Read-Host "Cole a API key do Ollama Cloud" -AsSecureString
$ponte = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($segredo)
try {
    if ([string]::IsNullOrWhiteSpace([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ponte))) {
        throw "A API key nao pode ficar vazia."
    }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ponte)
}

New-Item -ItemType Directory -Path $pastaSegredos -Force | Out-Null
$segredo | ConvertFrom-SecureString |
    Set-Content -LiteralPath $arquivoSegredo -Encoding UTF8 -NoNewline

# Defesa adicional: somente usuario atual e SYSTEM podem ler o arquivo cifrado.
$sidAtual = [Security.Principal.WindowsIdentity]::GetCurrent().User
$sidSystem = New-Object Security.Principal.SecurityIdentifier("S-1-5-18")
$acl = New-Object Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $sidAtual,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.AccessControlType]::Allow
)))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $sidSystem,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.AccessControlType]::Allow
)))
Set-Acl -LiteralPath $arquivoSegredo -AclObject $acl

# Confirma que o blob pode ser decifrado sem revelar o valor.
$blobProtegido = (Get-Content -Raw -LiteralPath $arquivoSegredo).Trim()
$confirmacao = ConvertTo-SecureString -String $blobProtegido
if ($confirmacao.Length -eq 0) {
    throw "Falha ao validar a chave criptografada."
}

Write-Host "Chave Ollama salva com DPAPI para este usuario Windows."
Write-Host "Local protegido: $arquivoSegredo"
