"""Sessions, Mac and GitHub tabs.

Each screen implements:
  handle(action, repeat=False)   a button press
  update(dt)
  draw(surf, rect)
  hints() -> list of (button, label)
  on_show() / on_hide()
"""
import os
import time

import pygame

import theme as T

DEFAULT_QUICK = [
    {"label": "Pick option 1", "keys": ["1"]},
    {"label": "Pick option 2", "keys": ["2"]},
    {"label": "Pick option 3", "keys": ["3"]},
    {"label": "Type \"continue\"", "text": "continue", "enter": True},
    {"label": "Type \"yes\"", "text": "yes", "enter": True},
    {"label": "Shift+Tab (cycle mode)", "keys": ["BTab"]},
    {"label": "Tab", "keys": ["Tab"]},
    {"label": "Ctrl+C (interrupt)", "keys": ["C-c"]},
]

TOOL_TAGS = {"claude": ("Claude", T.CLAUDE), "codex": ("Codex", T.CODEX), "shell": ("Shell", T.SHELL)}

# On-screen keyboard. Last row holds action keys (2 cells wide each in the grid).
KB_LOWER = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm,.?"]
KB_UPPER = ["!@#$%^&*()", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM;:/"]
KB_ACTIONS = ["shift", "space", "back", "send"]  # bottom row
KB_ACTION_LABEL = {"shift": "Shift", "space": "Space", "back": "Del", "send": "Send"}


def offline_panel(surf, rect, app):
    x, y, w, h = rect
    T.rrect(surf, T.PANEL, (x + 20, y + 40, w - 40, 190), 12)
    T.text(surf, "Can't reach your Mac", (x + 40, y + 60), 24, T.FG, bold=True)
    T.text(surf, app.poller.error or "Connecting...", (x + 40, y + 98), 15, T.ATTN, maxw=w - 80)
    T.text(surf, "Agent: %s" % app.api.base, (x + 40, y + 130), 15, T.DIM, maxw=w - 80)
    T.text(surf, "On the Mac run: python3 agent/agentdeck_agent.py", (x + 40, y + 158), 15, T.DIM)
    T.text(surf, "Then check host and token in agentdeck/config.json", (x + 40, y + 182), 15, T.DIM)


# =========================================================================== Sessions

class SessionsScreen:
    title = "Sessions"

    def __init__(self, app):
        self.app = app
        self.mode = "list"      # list | detail | menu | keyboard
        self.sel = 0
        self.pane = None
        self.scroll = 0
        self.menu_sel = 0
        self.quick = DEFAULT_QUICK + list(app.cfg.get("quick_replies", []))
        self._cache_key = None
        self._cache = None
        # on-screen keyboard state
        self.kb_text = ""
        self.kb_r = 0
        self.kb_c = 0
        self.kb_shift = False

    # ---- data
    def sessions(self):
        d = self.app.poller.get("sessions") or {}
        lst = list(d.get("sessions", []))
        lst.sort(key=lambda s: (not s.get("waiting"), s.get("idle_s") or 0))
        return lst

    def waiting_count(self):
        return sum(1 for s in self.sessions() if s.get("waiting"))

    def current(self):
        for s in self.sessions():
            if s["pane"] == self.pane:
                return s
        return None

    # ---- lifecycle
    def on_show(self):
        if self.mode != "list":
            self.app.poller.focus_pane = self.pane

    def on_hide(self):
        self.app.poller.focus_pane = None

    def _open(self, s):
        self.pane = s["pane"]
        self.mode = "detail"
        self.scroll = 0
        self.app.poller.focus_pane = self.pane
        self.app.poller.kick("screen")

    def _close(self):
        self.mode = "list"
        self.pane = None
        self.app.poller.focus_pane = None

    def _send(self, label, keys=None, text=None, enter=False):
        if not self.pane:
            return
        self.app.poller.send(self.pane, keys=keys, text=text, enter=enter)
        self.app.toast("Sent " + label)
        self.scroll = 0

    def menu_items(self):
        return [{"label": "Type a message…", "kb": True}] + self.quick

    # ---- on-screen keyboard
    def _kb_rows(self):
        return (KB_UPPER if self.kb_shift else KB_LOWER)

    def _kb_cell(self):
        """The value under the cursor: a single char, or an action name."""
        rows = self._kb_rows()
        if self.kb_r < len(rows):
            row = rows[self.kb_r]
            return row[min(self.kb_c, len(row) - 1)]
        return KB_ACTIONS[min(self.kb_c, len(KB_ACTIONS) - 1)]

    def _kb_row_len(self, r):
        rows = self._kb_rows()
        return len(rows[r]) if r < len(rows) else len(KB_ACTIONS)

    def _kb_type(self, ch):
        if len(self.kb_text) < 480:
            self.kb_text += ch

    def _kb_activate(self):
        cell = self._kb_cell()
        if cell == "shift":
            self.kb_shift = not self.kb_shift
        elif cell == "space":
            self._kb_type(" ")
        elif cell == "back":
            self.kb_text = self.kb_text[:-1]
        elif cell == "send":
            self._kb_send()
        else:
            self._kb_type(cell)

    def _kb_send(self):
        txt = self.kb_text.strip("\n")
        if txt:
            self._send("message", text=txt, enter=True)
        self.kb_text = ""
        self.kb_shift = False
        self.mode = "detail"

    def _handle_keyboard(self, a, repeat=False):
        rows = self._kb_rows()
        nrows = len(rows) + 1  # + action row
        if a == "up":
            self.kb_r = (self.kb_r - 1) % nrows
        elif a == "down":
            self.kb_r = (self.kb_r + 1) % nrows
        elif a == "left":
            self.kb_c = (self.kb_c - 1) % self._kb_row_len(self.kb_r)
        elif a == "right":
            self.kb_c = (self.kb_c + 1) % self._kb_row_len(self.kb_r)
        elif repeat:
            return
        elif a == "a":
            self._kb_activate()
        elif a == "b":
            if self.kb_text:
                self.kb_text = self.kb_text[:-1]   # backspace
            else:
                self.mode = "detail"               # cancel when empty
        elif a == "x":
            self.kb_shift = not self.kb_shift
        elif a == "y":
            self._kb_send()
        self.kb_c = min(self.kb_c, self._kb_row_len(self.kb_r) - 1)

    # ---- input
    def handle(self, a, repeat=False):
        if self.mode == "list":
            lst = self.sessions()
            if a == "up":
                self.sel = max(0, self.sel - 1)
            elif a == "down":
                self.sel = min(max(0, len(lst) - 1), self.sel + 1)
            elif a == "a" and lst:
                self._open(lst[min(self.sel, len(lst) - 1)])
            elif a == "y":
                self.app.poller.kick("sessions")
                self.app.toast("Refreshing")
            return

        if self.mode == "menu":
            items = self.menu_items()
            if a == "up":
                self.menu_sel = (self.menu_sel - 1) % len(items)
            elif a == "down":
                self.menu_sel = (self.menu_sel + 1) % len(items)
            elif a == "a" and not repeat:
                q = items[self.menu_sel]
                if q.get("kb"):
                    self.mode = "keyboard"
                    self.kb_r = self.kb_c = 0
                else:
                    self._send(q["label"], q.get("keys"), q.get("text"), q.get("enter", False))
                    self.mode = "detail"
            elif a in ("b", "y"):
                self.mode = "detail"
            return

        if self.mode == "keyboard":
            self._handle_keyboard(a, repeat)
            return

        # detail
        if repeat and a not in ("l2", "r2"):
            return
        arrows = {"up": "Up", "down": "Down", "left": "Left", "right": "Right"}
        if a == "b":
            self._close()
        elif a == "a":
            self._send("Enter", ["Enter"])
        elif a == "x":
            self._send("Esc", ["Escape"])
        elif a == "y":
            self.mode = "menu"
            self.menu_sel = 0
        elif a in arrows:
            self._send(arrows[a], [arrows[a]])
        elif a == "l2":
            self.scroll += 8
        elif a == "r2":
            self.scroll = max(0, self.scroll - 8)

    def update(self, dt):
        pass

    def hints(self):
        if self.mode == "list":
            return [("A", "Open"), ("Y", "Refresh"), ("L1/R1", "Tabs")]
        if self.mode == "menu":
            return [("A", "Pick"), ("B", "Close")]
        if self.mode == "keyboard":
            return [("A", "Key"), ("X", "Shift"), ("Y", "Send"), ("B", "Del/Back")]
        return [("A", "Enter"), ("X", "Esc"), ("Y", "Quick"), ("D-pad", "Arrows"),
                ("L2/R2", "Scroll"), ("B", "Back")]

    # ---- drawing
    def draw(self, surf, rect):
        data = self.app.poller.get("sessions")
        if data is None:
            if self.app.poller.online is False:
                offline_panel(surf, rect, self.app)
            else:
                T.text(surf, "Connecting to your Mac...", (rect[0] + 24, rect[1] + 40), 20, T.DIM)
            return
        if self.mode == "list":
            self._draw_list(surf, rect, data)
        else:
            self._draw_detail(surf, rect)
            if self.mode == "menu":
                self._draw_menu(surf, rect)
            elif self.mode == "keyboard":
                self._draw_keyboard(surf, rect)

    def _draw_list(self, surf, rect, data):
        x, y, w, h = rect
        lst = self.sessions()
        if not data.get("tmux", True):
            T.text(surf, "tmux isn't installed on the Mac", (x + 24, y + 40), 22, T.ATTN, bold=True)
            T.text(surf, "Run: brew install tmux", (x + 24, y + 76), 17, T.DIM)
            return
        if not lst:
            T.text(surf, "No Claude or Codex sessions found", (x + 24, y + 36), 22, T.FG, bold=True)
            T.text(surf, "Start one inside tmux on your Mac:", (x + 24, y + 76), 17, T.DIM)
            T.rrect(surf, T.TERM_BG, (x + 24, y + 104, w - 48, 72), 8)
            T.text(surf, "scripts/agentdeck-new claude ~/code/app", (x + 38, y + 116), 16, T.CLAUDE, mono=True)
            T.text(surf, "scripts/agentdeck-new codex ~/code/api", (x + 38, y + 144), 16, T.CODEX, mono=True)
            T.text(surf, "They show up here within a few seconds.", (x + 24, y + 196), 17, T.DIM)
            return

        self.sel = min(self.sel, len(lst) - 1)
        row_h = 66
        visible = max(1, (h - 8) // row_h)
        first = max(0, min(self.sel - visible // 2, len(lst) - visible))
        blink = int(time.time() * 2) % 2 == 0
        for i, s in enumerate(lst[first:first + visible]):
            idx = first + i
            ry = y + 6 + i * row_h
            selected = idx == self.sel
            T.rrect(surf, T.RAISED if selected else T.PANEL, (x + 12, ry, w - 24, row_h - 8), 10)
            if selected:
                T.rrect(surf, T.FG, (x + 12, ry, w - 24, row_h - 8), 10, width=2)
            tool = s.get("tool")
            label, color = TOOL_TAGS.get(tool, TOOL_TAGS["shell"])
            tx = x + 42
            if tool == "claude" and T.icon(surf, "claude.png", (x + 32, ry + (row_h - 8) // 2), 30):
                tx = x + 56
            else:
                T.rrect(surf, color, (x + 24, ry + 10, 6, row_h - 28), 3)
            name = "%s:%s" % (s["session"], s["window"])
            T.text(surf, name, (tx, ry + 8), 19, T.FG, bold=True, maxw=w - 260)
            if s.get("waiting"):
                status, scol = "Needs input", (T.ATTN if blink else T.FG)
            else:
                idle = s.get("idle_s")
                status = "Working" if idle is not None and idle < 5 else "Idle %s" % T.human_age(idle)
                scol = T.GOOD if status == "Working" else T.DIM
            T.text(surf, status, (x + w - 30, ry + 9), 16, scol, bold=s.get("waiting"), anchor="topright")
            T.text(surf, label, (x + w - 30, ry + 32), 14, color, anchor="topright")
            sub = os.path.basename(s.get("cwd", "").rstrip("/")) or "~"
            last = s.get("last_line", "")
            T.text(surf, sub + "   " + last, (tx, ry + 34), 14, T.DIM, maxw=w - 170)

        if len(lst) > visible:
            T.text(surf, "%d/%d" % (self.sel + 1, len(lst)), (x + w - 16, y + h - 4), 13, T.FAINT,
                   anchor="bottomright")

    def _term_surface(self, text, w, h):
        key = (text, self.scroll, w, h)
        if key == self._cache_key:
            return self._cache
        f = T.font(14, mono=True)
        cw = max(1, f.size("M")[0])
        lh = f.get_linesize()
        cols = max(20, (w - 12) // cw)
        rows = max(1, (h - 8) // lh)
        lines = []
        for raw in text.split("\n"):
            raw = T.term_clean(raw.rstrip())
            if not raw:
                lines.append("")
                continue
            while len(raw) > cols:
                lines.append(raw[:cols])
                raw = raw[cols:]
            lines.append(raw)
        while lines and not lines[-1].strip():
            lines.pop()
        self.scroll = min(self.scroll, max(0, len(lines) - rows))
        end = len(lines) - self.scroll
        start = max(0, end - rows)
        s = pygame.Surface((w, h))
        s.fill(T.TERM_BG)
        for i, ln in enumerate(lines[start:end]):
            if ln:
                low = ln.lower()
                color = T.BAD if ("error" in low or "failed" in low) else T.FG
                s.blit(f.render(ln, True, color), (6, 4 + i * lh))
        if self.scroll:
            T.text(s, "scrolled up %d lines" % self.scroll, (w - 8, 4), 12, T.WARN, anchor="topright")
        self._cache_key, self._cache = key, s
        return s

    def _draw_detail(self, surf, rect):
        x, y, w, h = rect
        s = self.current()
        tool = (s or {}).get("tool")
        label, color = TOOL_TAGS.get(tool, TOOL_TAGS["shell"])
        tx = x + 26
        if tool == "claude" and T.icon(surf, "claude.png", (x + 20, y + 20), 28):
            tx = x + 40
        else:
            T.rrect(surf, color, (x + 12, y + 8, 6, 26), 3)
        title = "%s:%s" % (s["session"], s["window"]) if s else "Session closed"
        T.text(surf, title, (tx, y + 8), 19, T.FG, bold=True, maxw=w - 220)
        if s and s.get("waiting"):
            T.text(surf, "Needs input", (x + w - 16, y + 10), 16, T.ATTN, bold=True, anchor="topright")
        else:
            T.text(surf, label, (x + w - 16, y + 10), 16, color, anchor="topright")

        box = (x + 8, y + 42, w - 16, h - 48)
        data = self.app.poller.get("screen")
        if data and data.get("pane") == self.pane:
            term = self._term_surface(data.get("text", ""), box[2], box[3])
            surf.blit(term, box[:2])
        else:
            T.rrect(surf, T.TERM_BG, box, 6)
            T.text(surf, "Loading...", (box[0] + 12, box[1] + 10), 15, T.DIM)

    def _draw_menu(self, surf, rect):
        x, y, w, h = rect
        items = self.menu_items()
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        surf.blit(shade, (x, y))
        mw, row = 360, 32
        mh = 52 + row * len(items)
        mx, my = x + (w - mw) // 2, y + max(8, (h - mh) // 2)
        T.rrect(surf, T.PANEL, (mx, my, mw, mh), 12)
        T.text(surf, "Reply", (mx + 18, my + 14), 18, T.FG, bold=True)
        for i, q in enumerate(items):
            ry = my + 46 + i * row
            on = i == self.menu_sel
            if on:
                T.rrect(surf, T.RAISED, (mx + 8, ry, mw - 16, row - 4), 8)
            col = T.CLAUDE if q.get("kb") else (T.FG if on else T.DIM)
            T.text(surf, q["label"], (mx + 20, ry + 5), 16, col, bold=q.get("kb", False))

    def _draw_keyboard(self, surf, rect):
        x, y, w, h = rect
        shade = pygame.Surface((w, h), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        surf.blit(shade, (x, y))
        pad = 14
        kx, kw = x + pad, w - 2 * pad
        # text buffer box
        T.rrect(surf, T.TERM_BG, (kx, y + 12, kw, 46), 8)
        shown = self.kb_text[-60:] if self.kb_text else "Type a message, then Send (Y)"
        col = T.FG if self.kb_text else T.FAINT
        T.text(surf, shown + ("_" if self.kb_text else ""), (kx + 12, y + 24), 18, col, mono=True, maxw=kw - 24)
        # key grid
        rows = self._kb_rows()
        top = y + 72
        cols = 10
        cw = kw // cols
        ch = 34
        for r, rowstr in enumerate(rows):
            ry = top + r * (ch + 4)
            off = (kw - len(rowstr) * cw) // 2
            for c, chx in enumerate(rowstr):
                cx = kx + off + c * cw
                on = (r == self.kb_r and c == self.kb_c)
                T.rrect(surf, T.RAISED if on else T.PANEL, (cx + 2, ry, cw - 4, ch), 6)
                if on:
                    T.rrect(surf, T.CLAUDE, (cx + 2, ry, cw - 4, ch), 6, width=2)
                T.text(surf, chx, (cx + cw // 2, ry + ch // 2), 18, T.FG, bold=True, anchor="center")
        # action row
        ry = top + len(rows) * (ch + 4)
        aw = kw // len(KB_ACTIONS)
        for c, act in enumerate(KB_ACTIONS):
            cx = kx + c * aw
            on = (self.kb_r == len(rows) and self.kb_c == c)
            active = (act == "shift" and self.kb_shift)
            base = T.CLAUDE if act == "send" else (T.RAISED if (on or active) else T.PANEL)
            T.rrect(surf, base, (cx + 2, ry, aw - 4, ch), 6)
            if on:
                T.rrect(surf, T.FG, (cx + 2, ry, aw - 4, ch), 6, width=2)
            lbl = KB_ACTION_LABEL[act]
            tc = T.TERM_BG if act == "send" else T.FG
            T.text(surf, lbl, (cx + aw // 2, ry + ch // 2), 15, tc, bold=True, anchor="center")


# =========================================================================== Mac

class MacScreen:
    title = "Mac"

    def __init__(self, app):
        self.app = app
        self.hist = []
        self._last_ts = None

    def on_show(self):
        self.app.poller.want_stats = True
        self.app.poller.kick("stats")

    def on_hide(self):
        self.app.poller.want_stats = False

    def handle(self, a, repeat=False):
        if a == "y":
            self.app.poller.kick("stats")

    def update(self, dt):
        d = self.app.poller.get("stats") or {}
        if d.get("ts") and d["ts"] != self._last_ts and d.get("cpu") is not None:
            self._last_ts = d["ts"]
            self.hist = (self.hist + [d["cpu"]])[-60:]

    def hints(self):
        return [("Y", "Refresh"), ("L1/R1", "Tabs")]

    def _card(self, surf, r, title, value, frac, sub):
        T.rrect(surf, T.PANEL, r, 10)
        T.text(surf, title, (r[0] + 14, r[1] + 10), 15, T.DIM)
        T.text(surf, value, (r[0] + r[2] - 14, r[1] + 6), 22, T.FG, bold=True, anchor="topright")
        T.bar(surf, (r[0] + 14, r[1] + 40, r[2] - 28, 10), frac, T.level_color(frac))
        T.text(surf, sub, (r[0] + 14, r[1] + 56), 13, T.DIM, maxw=r[2] - 28)

    def draw(self, surf, rect):
        x, y, w, h = rect
        d = self.app.poller.get("stats")
        if not d:
            if self.app.poller.online is False:
                offline_panel(surf, rect, self.app)
            else:
                T.text(surf, "Loading stats...", (x + 24, y + 40), 20, T.DIM)
            return
        if not d.get("ok"):
            T.text(surf, "Stats unavailable: %s" % d.get("error", "starting up"), (x + 24, y + 40), 17, T.DIM)
            return

        # Header
        T.text(surf, d.get("host", "Mac"), (x + 16, y + 6), 22, T.FG, bold=True)
        chip = " ".join(p for p in (d.get("chip"), d.get("os")) if p)
        T.text(surf, chip, (x + w - 16, y + 12), 14, T.DIM, anchor="topright", maxw=w - 240)

        colw = (w - 40) // 2
        lx, rx = x + 12, x + 28 + colw
        cy = y + 40

        cpu = d.get("cpu")
        cpu_frac = cpu / 100.0 if cpu is not None else None
        load = d.get("load") or []
        self._card(surf, (lx, cy, colw, 78), "CPU", "%s%%" % (int(cpu) if cpu is not None else "?"),
                   cpu_frac, "Load " + " ".join("%.2f" % v for v in load[:3]))

        mem = d.get("mem") or {}
        mfrac = (mem["used"] / float(mem["total"])) if mem.get("total") else None
        self._card(surf, (lx, cy + 88, colw, 78), "Memory",
                   "%d%%" % int(mfrac * 100) if mfrac is not None else "?", mfrac,
                   "%s of %s in use" % (T.human_bytes(mem.get("used")), T.human_bytes(mem.get("total"))))

        disk = d.get("disk") or {}
        dfrac = (disk["used"] / float(disk["total"])) if disk.get("total") else None
        self._card(surf, (lx, cy + 176, colw, 78), "Disk",
                   "%s free" % T.human_bytes(disk.get("free")), dfrac,
                   "%s of %s used" % (T.human_bytes(disk.get("used")), T.human_bytes(disk.get("total"))))

        bat = d.get("battery")
        if bat:
            bfrac = bat["percent"] / 100.0
            col = T.GOOD if bat.get("ac") or bfrac > 0.3 else (T.WARN if bfrac > 0.15 else T.BAD)
            r = (lx, cy + 264, colw, 78)
            T.rrect(surf, T.PANEL, r, 10)
            T.text(surf, "Battery", (r[0] + 14, r[1] + 10), 15, T.DIM)
            T.text(surf, "%d%%" % bat["percent"], (r[0] + r[2] - 14, r[1] + 6), 22, T.FG, bold=True,
                   anchor="topright")
            T.bar(surf, (r[0] + 14, r[1] + 40, r[2] - 28, 10), bfrac, col)
            T.text(surf, bat.get("state", "").capitalize() + (" on power" if bat.get("ac") else ""),
                   (r[0] + 14, r[1] + 56), 13, T.DIM)

        # CPU history
        r = (rx, cy, colw, 124)
        T.rrect(surf, T.PANEL, r, 10)
        T.text(surf, "CPU, last 2 minutes", (r[0] + 14, r[1] + 10), 15, T.DIM)
        up = d.get("uptime_s")
        if up:
            T.text(surf, "Up " + T.human_age(up), (r[0] + r[2] - 14, r[1] + 10), 13, T.DIM, anchor="topright")
        gx, gy, gw, gh = r[0] + 14, r[1] + 36, r[2] - 28, r[3] - 48
        pygame.draw.line(surf, T.RAISED, (gx, gy + gh), (gx + gw, gy + gh), 1)
        if len(self.hist) > 1:
            step = gw / 59.0
            off = 60 - len(self.hist)
            pts = [(gx + (off + i) * step, gy + gh - (v / 100.0) * gh) for i, v in enumerate(self.hist)]
            pygame.draw.lines(surf, T.CODEX, False, pts, 2)

        # Top processes
        r = (rx, cy + 134, colw, 208)
        T.rrect(surf, T.PANEL, r, 10)
        T.text(surf, "Top processes", (r[0] + 14, r[1] + 10), 15, T.DIM)
        for i, p in enumerate(d.get("procs") or []):
            py = r[1] + 38 + i * 32
            T.text(surf, p["name"], (r[0] + 14, py), 15, T.FG, maxw=r[2] - 110)
            T.text(surf, "%.0f%%" % p["cpu"], (r[0] + r[2] - 14, py), 15,
                   T.level_color(min(1.0, p["cpu"] / 100.0)), anchor="topright")


# =========================================================================== GitHub

class GitHubScreen:
    title = "GitHub"

    def __init__(self, app):
        self.app = app

    def on_show(self):
        self.app.poller.want_github = True
        if self.app.poller.get("github") is None:
            self.app.poller.kick("github")

    def on_hide(self):
        self.app.poller.want_github = False

    def handle(self, a, repeat=False):
        if a == "y":
            self.app.poller.kick("github")
            self.app.toast("Refreshing")

    def update(self, dt):
        pass

    def hints(self):
        return [("Y", "Refresh"), ("L1/R1", "Tabs")]

    def draw(self, surf, rect):
        x, y, w, h = rect
        d = self.app.poller.get("github")
        if d is None:
            if self.app.poller.online is False:
                offline_panel(surf, rect, self.app)
            else:
                T.text(surf, "Loading GitHub...", (x + 24, y + 40), 20, T.DIM)
            return
        if not d.get("ok"):
            err = d.get("error", "")
            if err == "no_token":
                T.text(surf, "Connect GitHub", (x + 24, y + 30), 24, T.FG, bold=True)
                T.text(surf, "On the Mac, either sign in with the GitHub CLI:", (x + 24, y + 72), 16, T.DIM)
                T.text(surf, "gh auth login", (x + 40, y + 98), 16, T.CODEX, mono=True)
                T.text(surf, "or add github_token to ~/.agentdeck/config.json,", (x + 24, y + 132), 16, T.DIM)
                T.text(surf, "then restart the agent.", (x + 24, y + 156), 16, T.DIM)
            else:
                T.text(surf, "GitHub: %s" % err, (x + 24, y + 40), 17, T.DIM, maxw=w - 48)
            return

        T.text(surf, "@" + d.get("login", ""), (x + 16, y + 6), 22, T.FG, bold=True)
        T.text(surf, "%d contributions this year" % d.get("year_total", 0), (x + w - 16, y + 12), 14,
               T.DIM, anchor="topright")

        tiles = [("Today", d.get("today")), ("Streak", d.get("streak")),
                 ("Open PRs", d.get("open_prs")), ("Reviews", d.get("review_requests")),
                 ("Inbox", d.get("notifications"))]
        tw = (w - 24 - 8 * 4) // 5
        for i, (label, val) in enumerate(tiles):
            r = (x + 12 + i * (tw + 8), y + 40, tw, 70)
            T.rrect(surf, T.PANEL, r, 10)
            hot = label == "Reviews" and val
            T.text(surf, "-" if val is None else str(val), (r[0] + r[2] // 2, r[1] + 8), 26,
                   T.ATTN if hot else T.FG, bold=True, anchor="midtop")
            T.text(surf, label, (r[0] + r[2] // 2, r[1] + 44), 13, T.DIM, anchor="midtop")

        # Contribution grid, last 16 weeks
        weeks = d.get("weeks") or []
        r = (x + 12, y + 120, w - 24, 120)
        T.rrect(surf, T.PANEL, r, 10)
        T.text(surf, "Last 16 weeks", (r[0] + 14, r[1] + 10), 15, T.DIM)
        this_week = sum(weeks[-1]) if weeks else 0
        T.text(surf, str(this_week), (r[0] + 14, r[1] + 40), 30, T.FG, bold=True)
        T.text(surf, "this week", (r[0] + 14, r[1] + 78), 14, T.DIM)
        peak = max([c for wk in weeks for c in wk] or [1]) or 1
        cell, gap = 11, 3
        gx = r[0] + 180 + (r[2] - 194 - len(weeks) * (cell + gap)) // 2
        for wi, wk in enumerate(weeks):
            for di, c in enumerate(wk):
                if c == 0:
                    col = T.RAISED
                else:
                    t = 0.35 + 0.65 * min(1.0, c / float(peak))
                    col = tuple(int(T.PANEL[k] + (T.GOOD[k] - T.PANEL[k]) * t) for k in range(3))
                pygame.draw.rect(surf, col, (gx + wi * (cell + gap), r[1] + 12 + di * (cell + gap), cell, cell))

        # Recent activity
        r = (x + 12, y + 250, w - 24, h - 256)
        T.rrect(surf, T.PANEL, r, 10)
        T.text(surf, "Recent activity", (r[0] + 14, r[1] + 10), 15, T.DIM)
        rows = max(0, (r[3] - 40) // 24)
        for i, ev in enumerate((d.get("events") or [])[:rows]):
            ey = r[1] + 36 + i * 24
            T.text(surf, ev["verb"], (r[0] + 14, ey), 15, T.FG, maxw=170)
            T.text(surf, ev["repo"], (r[0] + 190, ey), 15, T.CODEX, maxw=r[2] - 260)
            T.text(surf, T.human_age(ev.get("ago_s")), (r[0] + r[2] - 14, ey), 14, T.DIM, anchor="topright")
