# Diálogo nativo de pasta estilo Explorer (IFileDialog + FOS_PICKFOLDERS).
# Uso: powershell -NoProfile -STA -File escolher_pasta_explorer.ps1 ["Título"]
# Saída: caminho UTF-8 na stdout; vazio = cancelado; exit 0.

param(
    [string]$Titulo = "Selecionar pasta"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

function Get-PastaEstiloExplorer {
    param([string]$Title)

    $ofd = New-Object System.Windows.Forms.OpenFileDialog
    $ofd.AddExtension = $false
    $ofd.CheckFileExists = $false
    $ofd.DereferenceLinks = $true
    $ofd.Filter = "Pastas|`n"
    $ofd.Multiselect = $false
    $ofd.Title = $Title
    $ofd.FileName = "Selecione a pasta"

    $binding = [System.Reflection.BindingFlags]"Instance, Public, NonPublic"
    $ofdType = $ofd.GetType()
    $assembly = [System.Windows.Forms.OpenFileDialog].Assembly

    $iFileDialog = $ofdType.GetMethod("CreateVistaDialog", $binding).Invoke($ofd, $null)
    [void]$ofdType.GetMethod("OnBeforeVistaDialog", $binding).Invoke($ofd, @($iFileDialog))

    $fosType = $assembly.GetType("System.Windows.Forms.FileDialogNative+FOS")
    $pickFolders = [uint32]$fosType.GetField("FOS_PICKFOLDERS").GetValue($null)
    $options = $ofdType.GetMethod("get_Options", $binding).Invoke($ofd, $null) -bor $pickFolders

    $iFileDialogType = $assembly.GetType("System.Windows.Forms.FileDialogNative+IFileDialog")
    [void]$iFileDialogType.GetMethod("SetOptions", $binding).Invoke($iFileDialog, @($options))
    try {
        [void]$iFileDialogType.GetMethod("Show", $binding).Invoke($iFileDialog, @([System.IntPtr]::Zero))
    } catch {
        # Cancelar no diálogo COM costuma virar exceção — trata como cancelado
        return $null
    }

    # OpenFileDialog.FileName fica com o caminho da pasta em modo PICKFOLDERS
    $path = $ofd.FileName
    if ([string]::IsNullOrWhiteSpace($path)) { return $null }
    if ((Split-Path -Leaf $path) -eq "Selecione a pasta") {
        $parent = Split-Path -Parent $path
        if (-not [string]::IsNullOrWhiteSpace($parent)) { $path = $parent }
    }
    if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path -PathType Container)) {
        return $path
    }
    return $null
}

try {
    $escolhido = Get-PastaEstiloExplorer -Title $Titulo
} catch {
    # Fallback: diálogo clássico (árvore) se a reflexão Vista falhar
    try {
        $d = New-Object System.Windows.Forms.FolderBrowserDialog
        $d.Description = $Titulo
        $d.ShowNewFolderButton = $true
        try { $d.UseDescriptionForTitle = $true } catch {}
        if ($d.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            exit 0
        }
        $escolhido = $d.SelectedPath
    } catch {
        [Console]::Error.WriteLine("ERR_DIALOG:$($_.Exception.Message)")
        exit 3
    }
}

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if ($escolhido) {
    [Console]::Out.Write($escolhido)
}
exit 0
