# Notarius installer (also the updater: running it again over an existing
# installation refreshes the program and keeps models, voices and meetings).
#
# Everything goes to %LOCALAPPDATA%\Notarius; nothing needs administrator
# rights except installing the Microsoft Visual C++ runtime when it is
# missing (one Windows prompt).  Downloads are pinned and checked against
# the SHA-256 written below, not against a checksum from the same server.
#
# Saved as UTF-8 with BOM so Windows PowerShell 5.1 reads the accents.

param(
    [switch]$Unattended,   # no questions, do not open the app at the end (CI)
    [switch]$SkipSetup     # do not download models or measure speed
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # PowerShell 5.1 downloads crawl with the bar on
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072

$UvVersion = '0.13.1'
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
$UvSha256 = '3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672'
$FfmpegUrl = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
$FfmpegSha256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
$VcRedistUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
$PythonVersion = '3.12'

$Root = Join-Path $env:LOCALAPPDATA 'Notarius'
$App = Join-Path $Root 'app'
$Source = Split-Path -Parent $PSScriptRoot          # the extracted "app" folder
$Venv = Join-Path $Root 'env'
$Python = Join-Path $Venv 'Scripts\python.exe'

function Say($text) { Write-Host $text }
function Step($text) { Write-Host ''; Write-Host "==> $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ''
    Write-Host "ERRO: $text" -ForegroundColor Red
    Write-Host 'Se precisar de ajuda, envie o arquivo de registro:'
    Write-Host "  $Log"
    if (-not $Unattended) { Read-Host 'Aperte Enter para fechar' | Out-Null }
    exit 1
}

function Download($url, $file, $sha256) {
    for ($i = 1; $i -le 3; $i++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing
            if ($sha256) {
                $got = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLower()
                if ($got -ne $sha256) { throw "checksum $got" }
            }
            return
        } catch {
            Say "  tentativa $i falhou: $($_.Exception.Message)"
            Start-Sleep -Seconds (5 * $i)
        }
    }
    Fail "Não consegui baixar $url. Verifique a internet e rode o instalador de novo."
}

function Run($exe, [string[]]$arguments, $what) {
    for ($i = 1; $i -le 2; $i++) {
        & $exe @arguments
        if ($LASTEXITCODE -eq 0) { return }
        Say "  $what falhou (código $LASTEXITCODE), tentando de novo..."
    }
    Fail "$what falhou."
}

New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Log = Join-Path $Root 'instalacao.log'
Start-Transcript -LiteralPath $Log -Append | Out-Null

Write-Host ''
Write-Host '  Notarius — instalação' -ForegroundColor Yellow
Write-Host '  Transcrição de reuniões com reconhecimento de vozes, tudo no seu computador.'

# ---------------------------------------------------------------- checks
Step 'Verificando o computador'
if (-not [Environment]::Is64BitOperatingSystem) { Fail 'O Notarius precisa do Windows de 64 bits.' }
if ([Environment]::OSVersion.Version.Major -lt 10) { Fail 'O Notarius precisa do Windows 10 ou mais novo.' }
$drive = Get-PSDrive -Name ($Root.Substring(0, 1))
$freeGb = [math]::Round($drive.Free / 1GB, 1)
Say "  Espaço livre no disco $($drive.Name): $freeGb GB"
if ($freeGb -lt 12 -and -not (Test-Path -LiteralPath $Venv)) {
    Fail "São necessários pelo menos 12 GB livres (há $freeGb GB). Libere espaço e tente de novo."
}

# Torch needs the Visual C++ runtime, which is not part of Windows.
$sys32 = Join-Path $env:SystemRoot 'System32'
$hasVc = (Test-Path -LiteralPath (Join-Path $sys32 'msvcp140.dll')) -and
         (Test-Path -LiteralPath (Join-Path $sys32 'vcruntime140_1.dll'))
if (-not $hasVc) {
    Step 'Instalando o Microsoft Visual C++ (o Windows vai pedir permissão)'
    $vc = Join-Path $env:TEMP 'vc_redist.x64.exe'
    Download $VcRedistUrl $vc $null
    $p = Start-Process -FilePath $vc -ArgumentList '/install', '/quiet', '/norestart' -Verb RunAs -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        Fail "A instalação do Visual C++ não terminou (código $($p.ExitCode))."
    }
}

# --------------------------------------------------------------- program
Step 'Copiando o programa'
$sameFolder = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\') -eq $App.TrimEnd('\')
if (-not $sameFolder) {   # running the installed copy again (repair): nothing to copy
    if (Test-Path -LiteralPath $App) { Remove-Item -LiteralPath $App -Recurse -Force }
    Copy-Item -LiteralPath $Source -Destination $App -Recurse
}
Get-ChildItem -LiteralPath $App -Recurse -File | Unblock-File

# uv keeps everything it installs inside $Root.
$env:UV_CACHE_DIR = Join-Path $Root 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'python'
$env:UV_PYTHON_CACHE_DIR = Join-Path $Root 'uv-cache\python'
$env:UV_PROJECT_ENVIRONMENT = $Venv
$env:UV_TOOL_DIR = Join-Path $Root 'uv-tools'
$env:UV_TOOL_BIN_DIR = Join-Path $Root 'uv-tools\bin'
$env:UV_PYTHON_BIN_DIR = Join-Path $Root 'python\bin'
$env:UV_PYTHON_INSTALL_BIN = '0'
$env:UV_PYTHON_INSTALL_REGISTRY = '0'
$env:UV_NO_CONFIG = '1'
$env:UV_MANAGED_PYTHON = '1'
$Uv = Join-Path $Root 'bin\uv.exe'

if (-not (Test-Path -LiteralPath $Uv)) {
    Step 'Baixando o gerenciador de pacotes (uv)'
    $zip = Join-Path $env:TEMP "uv-$UvVersion.zip"
    Download $UvUrl $zip $UvSha256
    $tmp = Join-Path $env:TEMP "uv-$UvVersion"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp
    New-Item -ItemType Directory -Force -Path (Split-Path $Uv) | Out-Null
    Copy-Item -LiteralPath (Join-Path $tmp 'uv.exe') -Destination $Uv
}

Step 'Instalando o Python e as bibliotecas (alguns minutos; cerca de 1,5 GB)'
Run $Uv @('python', 'install', $PythonVersion) 'A instalação do Python'
Run $Uv @('sync', '--frozen', '--no-dev', '--project', $App) 'A instalação das bibliotecas'

$FfmpegDir = Join-Path $Root 'ffmpeg'
if (-not (Test-Path -LiteralPath (Join-Path $FfmpegDir 'ffprobe.exe'))) {
    Step 'Baixando o ffmpeg (leitor de áudio e vídeo; cerca de 115 MB)'
    $zip = Join-Path $env:TEMP 'ffmpeg-essentials.zip'
    Download $FfmpegUrl $zip $FfmpegSha256
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.Name -eq 'ffmpeg.exe' -or $entry.Name -eq 'ffprobe.exe') {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $FfmpegDir $entry.Name), $true)
            }
        }
    } finally { $archive.Dispose() }
    Remove-Item -LiteralPath $zip -Force
}

Step 'Conferindo a instalação'
& $Python -c "import torch, tkinter, notarius; print('ok', notarius.__version__)"
if ($LASTEXITCODE -ne 0) { Fail 'O Python instalado não conseguiu carregar o Notarius.' }
& (Join-Path $FfmpegDir 'ffmpeg.exe') -hide_banner -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { Fail 'O ffmpeg não funcionou.' }

# ---------------------------------------------------------------- models
if (-not $SkipSetup) {
    Step 'Baixando os modelos de reconhecimento e medindo a velocidade do computador'
    Say '  Isto baixa cerca de 5 GB e pode levar de 15 minutos a uma hora.'
    Say '  Se a internet cair, rode o instalador de novo: ele continua de onde parou.'
    & $Python -m notarius setup
    if ($LASTEXITCODE -ne 0 -and $Unattended) { Fail 'A preparação dos modelos falhou.' }
    if ($LASTEXITCODE -ne 0) {
        Say ''
        Say 'A preparação não terminou. Você pode completá-la depois pelo próprio'
        Say 'Notarius: Ajustes → Preparar agora.'
    }
}

# ------------------------------------------------------------- shortcuts
Step 'Criando os atalhos'
$shell = New-Object -ComObject WScript.Shell
$icon = Join-Path $App 'windows\notarius.ico'
function Shortcut($path, $target, $arguments, $description) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $Root
    $s.IconLocation = "$icon,0"
    $s.Description = $description
    $s.WindowStyle = 7   # start minimized: the console only keeps the app running
    $s.Save()
}
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'Notarius'
New-Item -ItemType Directory -Force -Path $programs | Out-Null
Shortcut (Join-Path $desktop 'Notarius.lnk') $Python '-m notarius app' 'Transcrição de reuniões'
Shortcut (Join-Path $programs 'Notarius.lnk') $Python '-m notarius app' 'Transcrição de reuniões'
$uninstall = Join-Path $App 'windows\uninstall.ps1'
$s = $shell.CreateShortcut((Join-Path $programs 'Desinstalar o Notarius.lnk'))
$s.TargetPath = 'powershell.exe'
$s.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$uninstall`""
$s.Save()

Step 'Pronto!'
Say '  O atalho "Notarius" está na área de trabalho e no menu Iniciar.'
Say "  Suas transcrições e vozes ficam em: $env:USERPROFILE\Notarius"
Stop-Transcript | Out-Null
if (-not $Unattended) {
    Start-Process -FilePath $Python -ArgumentList '-m', 'notarius', 'app' -WorkingDirectory $Root -WindowStyle Minimized
    Start-Sleep -Seconds 2
}
exit 0
