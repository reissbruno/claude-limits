"""Claude Limits: ícone na bandeja do Windows com os limites de uso do Claude Code.

Clique no ícone para abrir um painel no estilo da página de uso do Claude.
Lê o token do login do Claude Code da própria máquina (~/.claude/.credentials.json)
a cada consulta e o mantém só em memória. Não grava nem renova credenciais.
"""
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pystray
from PIL import Image, ImageDraw, ImageFont

APP_NAME = "Claude Limits"
CREDENTIALS = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
POLL_SECONDS = 180
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
STARTUP_FILE = os.path.join(STARTUP_DIR, "claude-limits.cmd")

ICON_COLORS = {"ok": (34, 160, 90), "warn": (225, 150, 20), "high": (210, 50, 45), "off": (120, 120, 120)}
WEEKDAYS = ["seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom."]
WEEKDAYS_FULL = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
                 "sexta-feira", "sábado", "domingo"]

# Paleta do painel (tema escuro, como a página de uso)
BG = "#1f1f1f"
FG = "#ececec"
MUTED = "#9a9a9a"
TRACK_ACTIVE = "#1d2a3a"
TRACK = "#2c2c2c"
BAR = "#2f7de1"
BAR_WARN = "#e0962a"
BAR_HIGH = "#d9443d"
BORDER = "#3a3a3a"
HOVER = "#2a2a2a"


class UsageError(Exception):
    """Erro com uma mensagem curta para mostrar ao usuário."""


# ---------------------------------------------------------------- dados

def read_token():
    """Lê o access token do login do Claude Code. Não guarda cópia.

    O Claude Code regrava o arquivo ao renovar o login, e ele pode sumir ou ficar
    incompleto por um instante: por isso tenta algumas vezes antes de dar erro."""
    for attempt in range(4):
        try:
            with open(CREDENTIALS, encoding="utf-8") as f:
                oauth = json.load(f).get("claudeAiOauth") or {}
            error = None if oauth.get("accessToken") else "Sem login no Claude Code"
        except FileNotFoundError:
            error = "Sem login no Claude Code"
        except (OSError, ValueError):
            error = "Não consegui ler o login"
        if error is None:
            break
        if attempt < 3:
            time.sleep(1.5)
    else:
        raise UsageError(error)
    token = oauth["accessToken"]
    expires = oauth.get("expiresAt")
    if expires and expires / 1000 < time.time():
        raise UsageError("Login expirado: abra o Claude Code")
    return token


def fetch_usage():
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + read_token(),
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-limit-coast",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise UsageError("Login expirado: abra o Claude Code")
        if e.code == 429:
            raise UsageError("Muitas consultas, tentando depois")
        raise UsageError(f"Erro {e.code} na consulta")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UsageError("Sem conexão")


def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return None
    # O servidor manda 15:59:59.86 para "16:00": arredonda para o minuto mais próximo
    return (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)


def parse_rows(data):
    """Converte a resposta em linhas: dict(kind, title, subtitle, pct, active, severity, resets)."""
    shares = {s.get("limit_index"): s for s in data.get("weekly_scoped_shares") or []}
    rows = []
    for i, lim in enumerate(data.get("limits") or []):
        kind = lim.get("kind")
        pct = lim.get("percent")
        if pct is None:
            continue
        when = parse_time(lim.get("resets_at"))
        if kind == "session":
            title = "Sessão atual"
            sub = f"Redefine às {when:%H:%M}" if when else ""
        else:
            reset = f"Reinicia {WEEKDAYS[when.weekday()]}, {when:%H:%M}" if when else ""
            if kind == "weekly_all":
                title, sub = "Limite semanal · Todos os modelos", reset
            else:
                scope = lim.get("scope") or {}
                name = ((scope.get("model") or {}).get("display_name")
                        or (scope.get("surface") or {}).get("display_name")
                        or kind.replace("_", " ").capitalize())
                title = name
                share = shares.get(i, {}).get("allowance_percent_of_weekly")
                sub = (f"Até {share:.0f}% do seu limite semanal\n{reset}" if share else reset)
        rows.append({
            "kind": kind, "title": title, "subtitle": sub, "pct": float(pct),
            "active": bool(lim.get("is_active")), "severity": lim.get("severity") or "normal",
            "resets": when,
        })
    # Resposta antiga sem "limits": usa os campos five_hour / seven_day
    if not rows:
        for key, kind, title in (("five_hour", "session", "Sessão atual"),
                                 ("seven_day", "weekly_all", "Limite semanal · Todos os modelos")):
            win = data.get(key) or {}
            if win.get("utilization") is None:
                continue
            when = parse_time(win.get("resets_at"))
            rows.append({"kind": kind, "title": title, "subtitle": "", "pct": float(win["utilization"]),
                         "active": kind == "session", "severity": "normal", "resets": when})
    return rows


def level(pct):
    if pct is None:
        return "off"
    if pct >= 80:
        return "high"
    if pct >= 50:
        return "warn"
    return "ok"


# ---------------------------------------------------------------- ícone

def load_font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


FROZEN = getattr(sys, "frozen", False)  # rodando como .exe (PyInstaller)
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
SVG_FILE = os.path.join(HERE, "claude-code.svg")
LOGO_FILE = os.path.join(HERE, "claude_icon.png")
_logo_cache = []


def render_pixel_svg(path, size):
    """Desenha um SVG simples (caminhos só com M/H/V/L/z, como o ícone do Claude Code)."""
    import re
    text = open(path, encoding="utf-8").read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', text).group(1).split()]
    d = re.search(r'\sd="([^"]+)"', text).group(1)
    fill = (re.search(r'fill="(#[0-9a-fA-F]{6})"', text) or [None, "#D97757"])[1]
    color = tuple(int(fill[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    scale = 8  # desenha grande e reduz, para bordas suaves
    s = size * scale / max(vb[2], vb[3])
    polys, cur, x, y = [], [], 0.0, 0.0
    tokens = re.findall(r"[MmHhVvLlZz]|-?\d*\.?\d+", d)
    i, cmd = 0, None
    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    polys.append(cur)
                cur = []
            continue
        rel = cmd.islower()  # minúsculas são relativas à posição atual
        if cmd in "Mm":
            if cur:
                polys.append(cur)
            dx, dy = float(tokens[i]), float(tokens[i + 1])
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            cur, i, cmd = [(x, y)], i + 2, ("l" if rel else "L")
        elif cmd in "Ll":
            dx, dy = float(tokens[i]), float(tokens[i + 1])
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            cur.append((x, y))
            i += 2
        elif cmd in "Hh":
            v = float(tokens[i])
            x = x + v if rel else v
            cur.append((x, y))
            i += 1
        elif cmd in "Vv":
            v = float(tokens[i])
            y = y + v if rel else v
            cur.append((x, y))
            i += 1
        else:
            raise ValueError("comando SVG não suportado: " + cmd)
    if cur:
        polys.append(cur)
    # Regra even-odd: cada subcaminho inverte a máscara
    from PIL import ImageChops
    mask = Image.new("1", (size * scale, size * scale), 0)
    for poly in polys:
        layer = Image.new("1", mask.size, 0)
        ImageDraw.Draw(layer).polygon([((px - vb[0]) * s, (py - vb[1]) * s) for px, py in poly], fill=1)
        mask = ImageChops.logical_xor(mask, layer)
    img = Image.new("RGBA", mask.size, color)
    img.putalpha(mask.convert("L"))
    return img.resize((size, size), Image.LANCZOS)


# O boneco do claude-code.svg é pixel art numa grade de 16 x 10 "pixels" (cada um = 1,5 unidade do SVG).
MASCOT = [
    "..############..",
    "..############..",
    "..##.######.##..",
    "..##.######.##..",
    "################",
    "################",
    "..############..",
    "..############..",
    "..#.#.....#.#...",
    "..#.#.....#.#...",
]
MASCOT_COLOR = (217, 119, 87)   # #D97757, a cor do SVG
MASCOT_OFF = (140, 140, 140)
BAR_TRACK = (95, 95, 95)


def tray_size():
    """Tamanho real do ícone na bandeja (16 px a 100%, 20 px a 125%...)."""
    try:
        return max(16, ctypes.windll.user32.GetSystemMetrics(49))  # SM_CXSMICON
    except Exception:
        return 16


def draw_tray_icon(pct, color_key, size=None):
    """Boneco do Claude Code em pixel art nítido, com a barra de uso da sessão embaixo."""
    size = size or tray_size()
    # Base em 1 px por célula: boneco 16x10, 1 linha vazia, barra de 2 linhas
    base = Image.new("RGBA", (16, 13), (0, 0, 0, 0))
    px = base.load()
    body = MASCOT_OFF if color_key == "off" else MASCOT_COLOR
    for y, row in enumerate(MASCOT):
        for x, ch in enumerate(row):
            if ch == "#":
                px[x, y] = body + (255,)
    filled = 0 if pct is None or pct <= 0 else max(1, round(16 * min(pct, 100) / 100))
    for x in range(16):
        color = ICON_COLORS[color_key] if x < filled else BAR_TRACK
        for y in (11, 12):
            px[x, y] = color + (255,)
    # Ocupa a largura toda do ícone; NEAREST mantém os pixels nítidos
    art = base.resize((size, round(13 * size / 16)), Image.NEAREST)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(art, ((size - art.width) // 2, (size - art.height) // 2), art)
    return img


def install_crisp_tray_loader():
    """O pystray carrega o ícone em 32 px e o Windows reduz (fica borrado).
    Aqui o ícone é carregado já no tamanho exato da bandeja."""
    import tempfile
    from pystray import _win32
    from pystray._util import win32

    def _assert_icon_handle(self):
        if self._icon_handle:
            return
        size = tray_size()
        img = self.icon if self.icon.size == (size, size) else self.icon.resize((size, size), Image.NEAREST)
        fd, path = tempfile.mkstemp(suffix=".ico")
        os.close(fd)
        try:
            img.save(path, "ICO", sizes=[(size, size)])
            self._icon_handle = win32.LoadImage(None, path, win32.IMAGE_ICON, size, size,
                                                win32.LR_LOADFROMFILE)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    _win32.Icon._assert_icon_handle = _assert_icon_handle


def draw_icon(text, color_key):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=14, fill=ICON_COLORS[color_key])
    font = load_font(44 if len(text) <= 2 else 32)
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), text, font=font, fill="white")
    return img


# ---------------------------------------------------------------- painel

def work_area():
    """Área útil da tela principal (sem a barra de tarefas)."""
    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
    r = RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    return r.l, r.t, r.r, r.b


class Panel:
    WIDTH = 560
    BAR_W = 230

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.win = None
        self.pinned = False
        self.closed_at = 0.0
        self._drag = None

    # -- abrir / fechar
    def toggle(self):
        if self.win:
            self.close()
        elif time.time() - self.closed_at > 0.4:  # o clique no ícone já fechou por perda de foco
            self.open()

    def open(self):
        self.win = tk.Toplevel(self.root, bg=BORDER)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.bind("<Escape>", lambda _: self.close())
        self.win.bind("<FocusOut>", self._on_focus_out)
        self.body = tk.Frame(self.win, bg=BG, padx=22, pady=18)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self.render()
        self._place()
        self.win.focus_force()

    def close(self):
        if self.win:
            self.win.destroy()
            self.win = None
            self.closed_at = time.time()

    def _on_focus_out(self, _):
        if self.pinned or not self.win:
            return
        # Espera um instante: o foco pode ter ido para um filho do próprio painel
        self.root.after(150, self._close_if_unfocused)

    def _close_if_unfocused(self):
        if self.win and not self.pinned:
            focused = self.win.focus_get() if self.win else None
            if focused is None:
                self.close()

    def _place(self):
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        l, t, r, b = work_area()
        self.win.geometry(f"{w}x{h}+{r - w - 12}+{b - h - 12}")

    # -- arrastar quando fixado
    def _drag_start(self, e):
        if self.pinned:
            self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        if self.pinned and self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def show_floating(self):
        """Abre o painel já fixado na tela (modo flutuante)."""
        self.pinned = True
        if self.win:
            self.render(keep_position=True)
        else:
            self.open()

    def _toggle_pin(self):
        self.pinned = not self.pinned
        self.render(keep_position=True)

    # -- desenho
    def render(self, keep_position=False):
        if not self.win:
            return
        for child in self.body.winfo_children():
            child.destroy()
        app = self.app
        rows = app.rows

        # Cabeçalho: frase + botões
        head = tk.Frame(self.body, bg=BG)
        head.pack(fill="x")
        weekly = next((r for r in rows if r["kind"] == "weekly_all"), None)
        if weekly and weekly["resets"]:
            w = weekly["resets"]
            text = f"Seu limite semanal é redefinido {WEEKDAYS_FULL[w.weekday()]}, {w:%H:%M}."
        else:
            text = "Limites de uso do Claude"
        drag_widgets = [head]
        if not hasattr(self, "_mascot"):
            self._mascot = None
            try:
                from PIL import ImageTk
                px = int(26 * self.root.winfo_fpixels("1i") / 96)
                art = render_pixel_svg(SVG_FILE, px * 2)
                art = art.crop(art.getbbox()) if art.getbbox() else art
                art.thumbnail((px, px), Image.LANCZOS)
                self._mascot = ImageTk.PhotoImage(art, master=self.root)
            except Exception:
                pass
        if self._mascot:
            m = tk.Label(head, image=self._mascot, bg=BG)
            m.pack(side="left", padx=(0, 10))
            drag_widgets.append(m)
        title = tk.Label(head, text=text, bg=BG, fg=FG, font=("Segoe UI Semibold", 12), anchor="w")
        title.pack(side="left")
        drag_widgets.append(title)
        for widget in drag_widgets:
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
        self._button(head, "✕", self.close, "Fechar").pack(side="right")
        self._button(head, "📌", self._toggle_pin, "Fixar na tela",
                     active=self.pinned).pack(side="right", padx=(0, 4))
        self._button(head, "⟳", app.request_refresh, "Atualizar").pack(side="right", padx=(0, 4))

        tk.Frame(self.body, bg=BG, height=12).pack(fill="x")

        if not rows:
            msg = app.error or "Consultando…"
            tk.Label(self.body, text=msg, bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=8)
        for row in rows:
            self._row(row, stale=app.error is not None)

        # Rodapé
        tk.Frame(self.body, bg=BORDER, height=1).pack(fill="x", pady=(14, 10))
        foot = tk.Frame(self.body, bg=BG)
        foot.pack(fill="x")
        if app.error:
            status, color = app.error, BAR_WARN
        elif app.updated:
            status, color = f"Atualizado às {app.updated:%H:%M}", MUTED
        else:
            status, color = "Consultando…", MUTED
        tk.Label(foot, text=status, bg=BG, fg=color, font=("Segoe UI", 9)).pack(side="left")
        if app.spend_text:
            tk.Label(foot, text=app.spend_text, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))
        link = tk.Label(foot, text="Trocar de conta", bg=BG, fg=BAR, cursor="hand2",
                        font=("Segoe UI", 9, "underline"))
        link.pack(side="right")
        link.bind("<Button-1>", lambda _: app.switch_account())

        if not keep_position:
            self._place()
        else:
            self.win.update_idletasks()
            self.win.geometry(f"{self.win.winfo_reqwidth()}x{self.win.winfo_reqheight()}")

    def _row(self, row, stale):
        s = self.root.winfo_fpixels("1i") / 96  # escala do Windows (125%, 150%...)
        left_w, bar_w = int(250 * s), int(self.BAR_W * s)
        frame = tk.Frame(self.body, bg=BG, pady=int(7 * s))
        frame.pack(fill="x")
        frame.columnconfigure(0, minsize=left_w)
        left = tk.Frame(frame, bg=BG)
        left.grid(row=0, column=0, sticky="w")
        name = tk.Label(left, text=row["title"], bg=BG, fg=FG, font=("Segoe UI", 11), anchor="w",
                        justify="left", wraplength=left_w - int(10 * s))
        name.pack(fill="x")
        sub = None
        if row["subtitle"]:
            sub = tk.Label(left, text=row["subtitle"], bg=BG, fg=MUTED, font=("Segoe UI", 9),
                           anchor="w", justify="left", wraplength=left_w - int(10 * s))
            sub.pack(fill="x", pady=(2, 0))

        h = int(10 * s)
        canvas = tk.Canvas(frame, width=bar_w, height=h + 4, bg=BG, highlightthickness=0)
        canvas.grid(row=0, column=1, padx=(int(10 * s), int(12 * s)))

        pct_label = tk.Label(frame, text=f"{row['pct']:.0f}% usado", bg=BG, fg=MUTED,
                             font=("Segoe UI", 10), width=10, anchor="e")
        pct_label.grid(row=0, column=2, sticky="e")

        y = h / 2 + 2
        track = TRACK_ACTIVE if row["active"] else TRACK
        canvas.create_line(h / 2, y, bar_w - h / 2, y, width=h, capstyle="round", fill=track)
        pct = max(0.0, min(row["pct"], 100.0))
        if pct > 0:
            color = MUTED if stale else {"ok": BAR, "warn": BAR_WARN, "high": BAR_HIGH}[level(pct)]
            if row["severity"] not in ("normal", None) and color == BAR:
                color = BAR_WARN
            end = h / 2 + (bar_w - h) * pct / 100
            canvas.create_line(h / 2, y, max(end, h / 2 + 0.1), y, width=h, capstyle="round", fill=color)

        # Destaque ao passar o mouse
        widgets = [frame, left, name, pct_label] + ([sub] if sub else [])
        def enter(_):
            for w in widgets:
                w.configure(bg=HOVER)
            canvas.configure(bg=HOVER)
        def leave(_):
            for w in widgets:
                w.configure(bg=BG)
            canvas.configure(bg=BG)
        frame.bind("<Enter>", enter)
        frame.bind("<Leave>", leave)

    def _button(self, parent, text, command, tip, active=False):
        rest_fg, rest_bg = (BAR, TRACK_ACTIVE) if active else (MUTED, BG)
        b = tk.Label(parent, text=text, bg=rest_bg, fg=rest_fg, font=("Segoe UI Symbol", 11),
                     padx=6, cursor="hand2")
        b.bind("<Button-1>", lambda _: command())
        b.bind("<Enter>", lambda _: b.configure(fg=FG, bg=HOVER))
        b.bind("<Leave>", lambda _: b.configure(fg=rest_fg, bg=rest_bg))
        return b


# ---------------------------------------------------------------- app

class App:
    def __init__(self):
        self.rows = []
        self.error = None
        self.updated = None
        self.spend_text = ""
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.ui_queue = queue.Queue()

        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = Panel(self)
        self.icon = pystray.Icon(APP_NAME, draw_tray_icon(None, "off"), APP_NAME, menu=self.build_menu())

    # -- comunicação com a thread da interface
    def ui(self, fn):
        self.ui_queue.put(fn)

    def _pump(self):
        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass
        if not self.stop.is_set():
            self.root.after(80, self._pump)

    # -- menu da bandeja
    def build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Abrir painel", lambda: self.ui(self.panel.toggle), default=True),
            pystray.MenuItem("Painel flutuante", lambda: self.ui(self.panel.show_floating)),
            pystray.MenuItem("Atualizar agora", lambda: self.request_refresh()),
            pystray.MenuItem("Trocar de conta", lambda: self.switch_account()),
            pystray.MenuItem("Iniciar com o Windows", lambda: self.toggle_startup(),
                             checked=lambda _: os.path.exists(STARTUP_FILE)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", lambda: self.quit()),
        )

    def request_refresh(self):
        self.wake.set()

    def login(self, switch=False):
        """Abre o login do Claude Code numa janela de terminal.
        Com switch=True, sai da conta atual antes, para dar para entrar com outra."""
        lines = ["@echo off", "chcp 65001 >nul", "title Claude Limits - login"]
        if switch:
            lines += [
                "echo Saindo da conta atual do Claude Code...",
                "call claude auth logout",
                "echo.",
                "echo ============================================================",
                "echo  Para entrar com OUTRA conta:",
                "echo  O navegador pode entrar direto na conta antiga, porque ela",
                "echo  continua logada no claude.ai. Se isso acontecer:",
                "echo   - saia da conta no claude.ai e tente de novo, ou",
                "echo   - copie o link que vai aparecer abaixo e abra numa",
                "echo     janela anônima (Ctrl+Shift+N).",
                "echo ============================================================",
                "echo.",
            ]
        lines += [
            "call claude auth login --claudeai",
            "echo.",
            "echo Pode fechar esta janela.",
            "pause >nul",
            '(goto) 2>nul & del "%~f0"',  # o script se apaga ao terminar
        ]
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".cmd", prefix="claude-limits-login-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")  # modo texto no Windows já grava \r\n
        subprocess.Popen(["cmd", "/c", path], creationflags=subprocess.CREATE_NEW_CONSOLE)
        threading.Thread(target=self._refresh_after_login, args=(path,), daemon=True).start()

    def switch_account(self):
        self.login(switch=True)

    def _refresh_after_login(self, script):
        self._asked_login = True  # não abrir outro login sozinho enquanto este está aberto
        try:
            start = os.path.getmtime(CREDENTIALS)
        except OSError:
            start = 0
        for _ in range(300):  # até ~10 min esperando o login novo ser gravado
            if self.stop.wait(2):
                return
            try:
                # Só conta quando o arquivo existe de novo (o logout o apaga)
                if os.path.getmtime(CREDENTIALS) != start:
                    self.stop.wait(1)
                    self.wake.set()
                    return
            except OSError:
                pass

    def toggle_startup(self):
        if os.path.exists(STARTUP_FILE):
            os.remove(STARTUP_FILE)
        else:
            if FROZEN:
                line = f'@start "" "{sys.executable}"'
            else:
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(pyw):
                    pyw = "pythonw"
                line = f'@start "" "{pyw}" "{os.path.abspath(__file__)}"'
            with open(STARTUP_FILE, "w", encoding="utf-8") as f:
                f.write(line + "\r\n")
        self.icon.update_menu()

    def quit(self):
        self.stop.set()
        self.wake.set()
        self.icon.stop()
        self.ui(self.root.destroy)

    # -- atualização
    def refresh(self):
        try:
            data = fetch_usage()
            self.rows = parse_rows(data)
            spend = data.get("spend") or {}
            used = (spend.get("used") or {})
            if spend.get("enabled") and used.get("amount_minor"):
                value = used["amount_minor"] / (10 ** used.get("exponent", 2))
                self.spend_text = f"Créditos extras: {used.get('currency', 'USD')} {value:.2f}"
            else:
                self.spend_text = ""
            self.error = None
            self._no_login_count = 0
            self.updated = datetime.now()
        except UsageError as e:
            self.error = str(e)
            # Sem login em duas consultas seguidas: abre o login uma vez, sozinho
            if self.error == "Sem login no Claude Code":
                self._no_login_count = getattr(self, "_no_login_count", 0) + 1
                if self._no_login_count >= 2 and not getattr(self, "_asked_login", False):
                    self._asked_login = True
                    self.login()
                elif self._no_login_count == 1:
                    self.stop.wait(20)  # confere de novo logo, sem esperar os 3 min
                    self.wake.set()
            else:
                self._no_login_count = 0
        except Exception as e:  # nunca derrubar o app
            self.error = f"Erro: {type(e).__name__}"
        self.render_icon()
        self.ui(lambda: self.panel.render(keep_position=self.panel.pinned))

    def render_icon(self):
        session = next((r for r in self.rows if r["kind"] == "session"), None)
        weekly = next((r for r in self.rows if r["kind"] == "weekly_all"), None)
        if session is None:
            self.icon.icon = draw_tray_icon(None, "off")
        else:
            pct = session["pct"]
            self.icon.icon = draw_tray_icon(pct, "off" if self.error else level(pct))
        parts = []
        if session:
            parts.append(f"Sessão: {session['pct']:.0f}%")
        if weekly:
            parts.append(f"Semana: {weekly['pct']:.0f}%")
        if self.error:
            parts.append(self.error)
        self.icon.title = (" | ".join(parts) or APP_NAME)[:127]

    def poll_loop(self):
        while not self.stop.is_set():
            self.refresh()
            self.wake.wait(POLL_SECONDS)
            self.wake.clear()

    def run(self):
        self.icon.run_detached()
        self.icon.visible = True
        threading.Thread(target=self.poll_loop, daemon=True).start()
        self.root.after(80, self._pump)
        if "--flutuante" in sys.argv:
            self.root.after(300, self.panel.show_floating)
        self.root.mainloop()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texto nítido em telas com escala
    except Exception:
        pass
    try:
        install_crisp_tray_loader()
    except Exception:
        pass  # se o pystray mudar, volta ao carregamento padrão
    App().run()
