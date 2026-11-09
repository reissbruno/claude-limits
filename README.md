# Claude Limits

Mostra os limites de uso do Claude Code ao lado do relógio do Windows.

![Painel do Claude Limits](docs/painel.png)

## O que ele mostra

### Ícone na bandeja

O boneco do Claude Code fica ao lado do relógio. Passe o mouse por cima para ver um resumo.

![Ícone na bandeja com o resumo ao passar o mouse](docs/bandeja.png)

A **barra embaixo do boneco** mostra quanto você já usou da sessão (janela de 5h):

![Cores do ícone conforme o uso](docs/cores.png)

### Painel

**Clique no boneco** para abrir um painel no estilo da página de uso do Claude. Ele mostra a sessão atual, o limite semanal e os limites por modelo, cada um com o horário em que reinicia.

As barras mudam de cor conforme o uso: azul até 49%, amarelo de 50% a 79% e vermelho a partir de 80%.

![Painel com uso alto](docs/painel-uso-alto.png)

## Instalação: um comando

Pré-requisito: ter o **Claude Code** instalado ([como instalar](https://docs.claude.com/pt/docs/claude-code)).

Abra o **PowerShell** e rode:

```powershell
irm https://raw.githubusercontent.com/reissbruno/claude-limits/main/instalar.ps1 | iex
```

Esse comando faz tudo sozinho:

1. Confere se o Claude Code está instalado.
2. **Faz o login**, se você ainda não estiver logado: o navegador abre, você entra na sua conta Claude e autoriza.
3. Baixa o app para `%LOCALAPPDATA%\ClaudeLimits`.
4. Configura para abrir **junto com o Windows**.
5. Abre o app e **fixa o ícone ao lado do relógio**, fora da setinha `^`.

![Instalador rodando no terminal](docs/instalador.png)

**Para atualizar**, rode o mesmo comando de novo.

**Para remover**, rode o comando abaixo. Ele fecha o app, apaga o `.exe` e tira o app da inicialização do Windows. O seu login do Claude Code continua como estava.

```powershell
irm https://raw.githubusercontent.com/reissbruno/claude-limits/main/desinstalar.ps1 | iex
```

## Como usar

| Ação | O que faz |
|---|---|
| Clique no boneco | Abre ou fecha o painel |
| ⟳ no painel | Atualiza na hora (sozinho, atualiza a cada 3 min) |
| 📌 no painel | Fixa o painel na tela: ele não fecha sozinho e pode ser arrastado pelo título |
| ✕ ou Esc | Fecha o painel |
| Botão direito no boneco | Menu: painel flutuante, atualizar, trocar de conta, iniciar com o Windows, sair |

## Login e segurança

- O app **não pede nem guarda senha**. Ele usa o login do Claude Code do seu computador: a cada consulta, lê o token de `~/.claude/.credentials.json` e o mantém só na memória.
- O app **não renova o token**, para não atrapalhar o Claude Code.
  - Se o boneco ficar **cinza** com "Login expirado", abra o Claude Code uma vez. Ele renova o login sozinho.
  - Para entrar com outra conta, use **Trocar de conta**, no menu ou no rodapé do painel.
    - Primeiro ele sai da conta atual do **Claude Code**: a conta do app e a do Claude Code são a mesma.
    - Depois abre o login. Se o navegador entrar direto na conta antiga, saia dela no claude.ai, ou abra o link do terminal numa janela anônima (Ctrl+Shift+N).
- Os números são **da sua conta**: incluem o uso do Claude Code em qualquer lugar onde você estiver logado.

## Problemas comuns

- **O ícone ficou escondido na setinha `^`.** Arraste-o para a barra. Outra opção: em Configurações → Personalização → Barra de tarefas → Outros ícones da bandeja do sistema, ative **ClaudeLimits**.
- **O antivírus reclamou do `.exe`.** Isso acontece porque o arquivo não tem assinatura digital. Libere o `ClaudeLimits.exe`.
- **Aparece "Sem login no Claude Code".** Rode `claude auth login` no terminal, ou use **Trocar de conta**.

> ⚠️ Os dados vêm do mesmo endpoint que o comando `/usage` do Claude Code usa. Não é uma API pública documentada e pode mudar sem aviso.

---

## Para quem mantém o projeto

Arquivos do projeto:

- `claude_limits.pyw`: código do app (Python, com `pystray` e `Pillow`).
- `claude-code.svg`: ícone do boneco, usado no painel e no `.exe`.
- `bin/ClaudeLimits.exe`: o app pronto. É ele que o comando de instalação baixa.
- `instalar.ps1` e `desinstalar.ps1`: o instalador e o desinstalador, que rodam pelo `irm | iex` ou localmente. Os arquivos `.cmd` ao lado só chamam os `.ps1`.
- `docs/`: as imagens deste README e o `app.ico`.

Para rodar sem gerar o `.exe`:

```bash
python -m pip install --user -r requirements.txt
```

```bash
pythonw claude_limits.pyw
```

Para gerar uma versão nova do `.exe` em `bin\`:

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name ClaudeLimits --icon docs/app.ico --add-data "claude-code.svg;." --distpath bin claude_limits.pyw
```

Depois faça commit e push do `bin/ClaudeLimits.exe`. Na próxima vez que alguém rodar o comando de instalação, recebe a versão nova.
