# Instalador do Claude Limits: um comando faz tudo. Na pasta do repositório clonado:
#
#   .\instalar.cmd
#
#   1. confere se o Claude Code está instalado
#   2. faz o login (abre o navegador) se ainda não houver
#   3. instala o bin\ClaudeLimits.exe em %LOCALAPPDATA%\ClaudeLimits
#   4. configura para abrir junto com o Windows
#   5. abre o app e deixa o ícone sempre visível ao lado do relógio
#
# Se o bin\ClaudeLimits.exe não estiver na pasta, baixa do GitHub.

& {
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # download bem mais rápido no PowerShell 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$ExeUrl = 'https://github.com/reissbruno/claude-limits/raw/main/bin/ClaudeLimits.exe'

function Passo($texto) { Write-Host ''; Write-Host "==> $texto" -ForegroundColor Cyan }

function Status-Login {
    try {
        $json = (& claude auth status --json 2>$null) | Out-String
        return $json | ConvertFrom-Json
    } catch { return $null }
}

try {
    # ------------------------------------------------------------ 1. Claude Code
    Passo 'Conferindo o Claude Code'
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        throw 'Claude Code não encontrado. Instale primeiro (https://docs.claude.com/pt/docs/claude-code) e rode este comando de novo.'
    }
    Write-Host 'Claude Code encontrado.'

    # ------------------------------------------------------------ 2. Login
    Passo 'Conferindo o login'
    $st = Status-Login
    if (-not $st -or -not $st.loggedIn -or $st.authMethod -ne 'claude.ai') {
        Write-Host 'Vamos fazer o login na sua conta Claude. O navegador vai abrir: entre e autorize.' -ForegroundColor Yellow
        & claude auth login --claudeai
        $st = Status-Login
        if (-not $st -or -not $st.loggedIn -or $st.authMethod -ne 'claude.ai') {
            throw 'O login não foi concluído. Rode o comando de novo.'
        }
    }
    Write-Host "Logado como $($st.email)."

    # ------------------------------------------------------------ 3. Baixar / copiar o app
    Passo 'Instalando o app'
    $destDir = Join-Path $env:LOCALAPPDATA 'ClaudeLimits'
    $exe = Join-Path $destDir 'ClaudeLimits.exe'
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    # Rodando de um arquivo local com o .exe ao lado? Usa ele. Senão, baixa do GitHub.
    $local = $null
    if ($PSCommandPath) {
        $here = Split-Path -Parent $PSCommandPath
        $local = @("$here\ClaudeLimits.exe", "$here\bin\ClaudeLimits.exe", "$here\dist\ClaudeLimits.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    $tmp = Join-Path $env:TEMP 'ClaudeLimits-download.exe'
    if ($local) {
        Copy-Item $local $tmp -Force
    } else {
        Write-Host 'Baixando o ClaudeLimits.exe...'
        Invoke-WebRequest -Uri $ExeUrl -OutFile $tmp -UseBasicParsing
        if ((Get-Item $tmp).Length -lt 1MB) { throw 'O download veio incompleto. Tente de novo.' }
    }

    Get-Process ClaudeLimits -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 800
    Move-Item $tmp $exe -Force
    Unblock-File $exe -ErrorAction SilentlyContinue
    Write-Host "Instalado em $exe"

    # ------------------------------------------------------------ 4. Iniciar com o Windows
    Passo 'Configurando para abrir junto com o Windows'
    $startup = [Environment]::GetFolderPath('Startup')
    # Mesmo arquivo que a opção "Iniciar com o Windows" do menu do app usa
    Set-Content -Path (Join-Path $startup 'claude-limits.cmd') -Value "@start `"`" `"$exe`"" -Encoding ASCII
    Write-Host 'Pronto.'

    # ------------------------------------------------------------ 5. Abrir e deixar o ícone visível
    Passo 'Abrindo o Claude Limits'
    Start-Process $exe

    # O Windows cria a entrada do ícone alguns segundos depois de o app abrir
    $chave = 'HKCU:\Control Panel\NotifyIconSettings'
    $promovido = $false
    for ($i = 0; $i -lt 30 -and -not $promovido; $i++) {
        Start-Sleep -Seconds 1
        if (-not (Test-Path $chave)) { continue }
        Get-ChildItem $chave | ForEach-Object {
            $p = Get-ItemProperty $_.PSPath
            # Ignora cópias isoladas de apps empacotados (\Packages\), que não são esta instalação
            if ($p.ExecutablePath -match '\\ClaudeLimits\\ClaudeLimits\.exe$' -and $p.ExecutablePath -notmatch '\\Packages\\') {
                Set-ItemProperty -Path $_.PSPath -Name IsPromoted -Value 1 -Type DWord
                $promovido = $true
            }
        }
    }
    if ($promovido) {
        # Reabre o app para o Windows aplicar o ícone visível
        Get-Process ClaudeLimits -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Milliseconds 800
        Start-Process $exe
        Write-Host 'Ícone fixado ao lado do relógio.'
    } else {
        Write-Host 'Não consegui fixar o ícone sozinho. Se ele estiver escondido na setinha ^, arraste-o para a barra.' -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host 'Tudo pronto! Clique no boneco do Claude Code perto do relógio para ver seus limites.' -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
}
}
