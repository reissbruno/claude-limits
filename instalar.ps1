# Instalador do Claude Limits: um comando faz tudo. Na pasta do repositório clonado:
#
#   .\instalar.cmd
#
#   1. acha o Claude Code (terminal, VS Code ou Cursor); se não houver, instala
#      pelo instalador oficial da Anthropic
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
$ClaudeInstallerUrl = 'https://claude.ai/install.ps1'   # instalador oficial do Claude Code
$Credenciais = Join-Path $env:USERPROFILE '.claude\.credentials.json'

function Passo($texto) { Write-Host ''; Write-Host "==> $texto" -ForegroundColor Cyan }

function Achar-Claude {
    # 1) no PATH (instalado pelo terminal)
    $cmd = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    # 2) instalador oficial, mesmo que o PATH ainda não tenha sido atualizado
    $nativo = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path $nativo) { return $nativo }
    # 3) o executável que vem dentro da extensão do VS Code / Cursor (a versão mais nova)
    $achados = foreach ($d in "$env:USERPROFILE\.vscode\extensions", "$env:USERPROFILE\.vscode-insiders\extensions", "$env:USERPROFILE\.cursor\extensions") {
        if (Test-Path $d) {
            Get-ChildItem $d -Directory -Filter 'anthropic.claude-code-*' -ErrorAction SilentlyContinue |
                ForEach-Object { Join-Path $_.FullName 'resources\native-binary\claude.exe' } |
                Where-Object { Test-Path $_ } | ForEach-Object { Get-Item $_ }
        }
    }
    $maisNovo = $achados | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($maisNovo) { return $maisNovo.FullName }
    return $null
}

function Status-Login($claude) {
    try {
        $json = (& $claude auth status --json 2>$null) | Out-String
        return $json | ConvertFrom-Json
    } catch { return $null }
}

function Logado($st) { return $st -and $st.loggedIn -and $st.authMethod -eq 'claude.ai' }

try {
    # ------------------------------------------------------------ 1. Claude Code
    Passo 'Conferindo o Claude Code'
    $claude = Achar-Claude
    if (-not $claude) {
        Write-Host 'Claude Code não encontrado. Instalando pelo instalador oficial da Anthropic...' -ForegroundColor Yellow
        # Roda num PowerShell separado: assim nada do instalador interfere neste script
        & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm '$ClaudeInstallerUrl' | iex"
        # O instalador põe o claude em ~\.local\bin, mas nem sempre o coloca no PATH:
        # acrescenta no PATH do usuário (terminais futuros) e neste terminal
        $bin = Join-Path $env:USERPROFILE '.local\bin'
        $pathUsuario = [Environment]::GetEnvironmentVariable('Path', 'User')
        if (($pathUsuario -split ';') -notcontains $bin) {
            [Environment]::SetEnvironmentVariable('Path', (($pathUsuario.TrimEnd(';') + ";$bin").TrimStart(';')), 'User')
        }
        if ($env:Path -notlike "*$bin*") { $env:Path = "$bin;$env:Path" }
        $claude = Achar-Claude
        if (-not $claude) {
            throw 'Não consegui instalar o Claude Code. Instale manualmente (https://docs.claude.com/pt/docs/claude-code) e rode este comando de novo.'
        }
        Write-Host 'Claude Code instalado.'
    } else {
        Write-Host "Claude Code encontrado: $claude"
    }

    # ------------------------------------------------------------ 2. Login
    Passo 'Conferindo o login'
    $st = Status-Login $claude
    if (-not (Logado $st)) {
        Write-Host 'Vamos fazer o login na sua conta Claude. O navegador vai abrir: entre e autorize.' -ForegroundColor Yellow
        & $claude auth login --claudeai
        $st = Status-Login $claude
        if (-not (Logado $st)) {
            throw 'O login não foi concluído. Rode o comando de novo.'
        }
    }
    if (-not (Test-Path $Credenciais)) {
        throw "O login foi feito, mas o arquivo $Credenciais não apareceu. Rode o comando de novo."
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
