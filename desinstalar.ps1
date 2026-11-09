# Remove o Claude Limits: fecha o app, apaga o .exe instalado e tira da inicialização.
# O login do Claude Code NÃO é mexido.
#
#   .\desinstalar.cmd   (na pasta do repositório)

& {
function Passo($texto) { Write-Host ''; Write-Host "==> $texto" -ForegroundColor Cyan }

Passo 'Fechando o app'
Get-Process ClaudeLimits -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 800
Write-Host 'Pronto.'

Passo 'Removendo da inicialização do Windows'
$atalho = Join-Path ([Environment]::GetFolderPath('Startup')) 'claude-limits.cmd'
if (Test-Path $atalho) { Remove-Item $atalho -Force; Write-Host 'Removido.' } else { Write-Host 'Não estava configurado.' }

Passo 'Apagando o app instalado'
$dir = Join-Path $env:LOCALAPPDATA 'ClaudeLimits'
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force; Write-Host "Apagado: $dir" } else { Write-Host 'Não estava instalado.' }

# A entrada do ícone na bandeja (HKCU\Control Panel\NotifyIconSettings) fica de propósito:
# o Explorer guarda uma cópia em memória e, se ela for apagada, para de registrar o
# ícone até o próximo login. Ela é inofensiva e já deixa o ícone visível numa reinstalação.

Write-Host ''
Write-Host 'Claude Limits removido. Seu login do Claude Code continua como estava.' -ForegroundColor Green
}
