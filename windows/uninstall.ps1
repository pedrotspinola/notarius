# Removes the Notarius program, its Python environment and downloaded models
# (%LOCALAPPDATA%\Notarius) and its shortcuts.  The user's own folder with
# transcripts and voices is kept unless they say otherwise.
#
# Saved as UTF-8 with BOM so Windows PowerShell 5.1 reads the accents.

$ErrorActionPreference = 'Stop'
$Root = Join-Path $env:LOCALAPPDATA 'Notarius'
$Data = Join-Path $env:USERPROFILE 'Notarius'

Write-Host ''
Write-Host '  Desinstalar o Notarius' -ForegroundColor Yellow
Write-Host ''
Write-Host "  Vai apagar o programa e os modelos baixados ($Root)."
$answer = Read-Host '  Continuar? (s/n)'
if ($answer -notmatch '^[sS]') { exit 0 }

# Stop a running Notarius so its files can be removed.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*notarius*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'Notarius'
Remove-Item -LiteralPath (Join-Path $desktop 'Notarius.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $programs -Recurse -Force -ErrorAction SilentlyContinue

# This script lives inside $Root; copy it out of the way is not needed —
# PowerShell has already read it.
Set-Location $env:TEMP
Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $Root) {
    Write-Host '  Alguns arquivos estavam em uso. Reinicie o computador e apague a pasta:'
    Write-Host "  $Root"
}

Write-Host ''
Write-Host "  Suas transcrições e vozes continuam em: $Data"
$answer = Read-Host '  Apagar também essa pasta? Isso não tem volta. (s/n)'
if ($answer -match '^[sS]') {
    Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host '  Apagada.'
}
Write-Host ''
Write-Host '  O Notarius foi desinstalado.'
Read-Host '  Aperte Enter para fechar' | Out-Null
