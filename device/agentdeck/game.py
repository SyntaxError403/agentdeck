"""Byte Run: a tiny endless runner.

You are a cursor bot. Jump bugs and merge conflicts, duck under null
pointers, grab tokens. A jumps (hold for higher), Down ducks, Start pauses.
"""
import json
import os
import random

import pygame

import theme as T

HERE = os.path.dirname(os.path.abspath(__file__))
SCORE_FILE = os.path.join(HERE, "highscore.json")

GRAVITY = 2300.0
JUMP_V = -800.0
CUT_V = -320.0
BOT_W, BOT_H, DUCK_H = 38, 48, 28


class ByteRun:
    title = "Byte Run"

    def __init__(self, app):
        self.app = app
        self.best = self._load_best()
        self.reset()
        self.state = "ready"

    # ---- persistence
    def _load_best(self):
        try:
            with open(SCORE_FILE) as f:
                return int(json.load(f).get("best", 0))
        except (OSError, ValueError):
            return 0

    def _save_best(self):
        try:
            with open(SCORE_FILE, "w") as f:
                json.dump({"best": self.best}, f)
        except OSError:
            pass

    # ---- game state
    def reset(self):
        self.y = 0.0          # bot feet offset above ground (negative = up)
        self.vy = 0.0
        self.on_ground = True
        self.speed = 300.0
        self.dist = 0.0
        self.bonus = 0
        self.obstacles = []
        self.tokens = []
        self.spawn_in = 1.2
        self.t = 0.0
        self.state = "run"
        self.stars = [(random.randint(0, T.W), random.randint(0, 250), random.choice((1, 2)))
                      for _ in range(40)]

    @property
    def score(self):
        return int(self.dist / 10) + self.bonus

    def on_show(self):
        pass

    def on_hide(self):
        if self.state == "run":
            self.state = "paused"

    def hints(self):
        if self.state == "run":
            return [("A", "Jump"), ("Down", "Duck"), ("Start", "Pause")]
        return [("A", "Play"), ("L1/R1", "Tabs")]

    def handle(self, a, repeat=False):
        if repeat:
            return
        if self.state in ("ready", "over"):
            if a == "a":
                self.reset()
            return
        if self.state == "paused":
            if a in ("a", "start"):
                self.state = "run"
            return
        if a == "start":
            self.state = "paused"
        elif a == "a" and self.on_ground:
            self.vy = JUMP_V
            self.on_ground = False

    def _spawn(self):
        r = random.random()
        if r < 0.45:
            self.obstacles.append({"kind": "bug", "x": T.W + 20, "w": 34, "h": 24, "lift": 0})
        elif r < 0.75:
            self.obstacles.append({"kind": "conflict", "x": T.W + 20, "w": 30, "h": 54, "lift": 0})
        else:
            self.obstacles.append({"kind": "null", "x": T.W + 20, "w": 58, "h": 22, "lift": 38})
        if random.random() < 0.5:
            self.tokens.append({"x": T.W + 140 + random.randint(0, 80), "lift": random.choice((70, 110))})
        gap = random.uniform(0.85, 1.6) * (340.0 / self.speed) ** 0.5
        self.spawn_in = gap

    def update(self, dt):
        if self.state != "run":
            return
        dt = min(dt, 0.05)
        self.t += dt
        self.speed = min(720.0, self.speed + 9.0 * dt)
        self.dist += self.speed * dt

        ducking = "down" in self.app.held and self.on_ground
        if not self.on_ground:
            if self.vy < CUT_V and "a" not in self.app.held:
                self.vy = CUT_V
            if "down" in self.app.held:
                self.vy += GRAVITY * dt * 1.5  # fast fall
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            if self.y >= 0:
                self.y, self.vy, self.on_ground = 0.0, 0.0, True

        self.spawn_in -= dt
        if self.spawn_in <= 0:
            self._spawn()
        for o in self.obstacles:
            o["x"] -= self.speed * dt
        for tk in self.tokens:
            tk["x"] -= self.speed * dt
        self.obstacles = [o for o in self.obstacles if o["x"] + o["w"] > -10]
        self.tokens = [tk for tk in self.tokens if tk["x"] > -20]

        bot = self._bot_rect(ducking).inflate(-8, -6)
        for o in self.obstacles:
            if bot.colliderect(self._ob_rect(o).inflate(-6, -4)):
                self.state = "over"
                if self.score > self.best:
                    self.best = self.score
                    self._save_best()
                return
        keep = []
        for tk in self.tokens:
            if bot.colliderect(pygame.Rect(tk["x"] - 9, self.gy - tk["lift"] - 9, 18, 18)):
                self.bonus += 25
            else:
                keep.append(tk)
        self.tokens = keep

    # ---- geometry
    @property
    def gy(self):
        return 380  # ground line in screen coords

    def _bot_rect(self, ducking):
        h = DUCK_H if ducking else BOT_H
        w = BOT_W + (10 if ducking else 0)
        return pygame.Rect(90, int(self.gy + self.y - h), w, h)

    def _ob_rect(self, o):
        return pygame.Rect(int(o["x"]), self.gy - o["lift"] - o["h"], o["w"], o["h"])

    # ---- drawing
    def _draw_bot(self, surf, r, ducking):
        T.rrect(surf, T.GOOD, r, 8)
        screen = r.inflate(-10, -14 if not ducking else -10)
        screen.y = r.y + 5
        screen.h = max(8, r.h - 18)
        T.rrect(surf, T.TERM_BG, screen, 4)
        f = T.font(14, mono=True, bold=True)
        cursor = ">_" if int(self.t * 3) % 2 == 0 or self.state != "run" else "> "
        if self.state == "over":
            cursor = "x_x"
        img = f.render(cursor, True, T.GOOD)
        surf.blit(img, img.get_rect(center=screen.center))
        # legs
        phase = int(self.t * 12) % 2 if self.on_ground and self.state == "run" else 0
        ly = r.bottom
        for i, lx in enumerate((r.x + 9, r.right - 13)):
            lift = 4 if (i == phase and self.on_ground and self.state == "run") else 0
            pygame.draw.rect(surf, T.GOOD, (lx, ly - 2, 5, 8 - lift))

    def _draw_obstacle(self, surf, o):
        r = self._ob_rect(o)
        if o["kind"] == "bug":
            pygame.draw.ellipse(surf, T.BAD, r)
            for k in range(3):
                lx = r.x + 7 + k * 9
                pygame.draw.line(surf, T.BAD, (lx, r.bottom - 4), (lx - 4, r.bottom + 4), 2)
            pygame.draw.line(surf, T.BAD, (r.x + 4, r.y + 6), (r.x - 4, r.y - 4), 2)
            pygame.draw.circle(surf, T.TERM_BG, (r.x + 8, r.y + 9), 3)
        elif o["kind"] == "conflict":
            T.rrect(surf, T.CLAUDE, r, 4)
            f = T.font(12, mono=True, bold=True)
            for k, s in enumerate(("<<<", "===", ">>>")):
                img = f.render(s, True, T.TERM_BG)
                surf.blit(img, img.get_rect(midtop=(r.centerx, r.y + 4 + k * 16)))
        else:
            T.rrect(surf, (170, 120, 240), r, 11)
            T.text(surf, "NULL", r.center, 13, T.TERM_BG, bold=True, anchor="center")

    def draw(self, surf, rect):
        x, y, w, h = rect
        clip = surf.get_clip()
        surf.set_clip(rect)
        surf.fill(T.TERM_BG, rect)
        # parallax specks
        for sx, sy, sz in self.stars:
            px = (sx - self.dist * 0.08 * sz) % w
            surf.fill(T.FAINT, (x + px, y + sy, sz, sz))
        gy = self.gy
        pygame.draw.line(surf, T.DIM, (x, gy), (x + w, gy), 2)
        for k in range(0, w + 40, 40):
            dx = x + (k - self.dist) % (w + 40)
            pygame.draw.line(surf, T.FAINT, (dx, gy + 12), (dx + 14, gy + 12), 2)

        for tk in self.tokens:
            cx, cy = int(tk["x"]), gy - tk["lift"]
            pygame.draw.polygon(surf, T.CODEX, [(cx, cy - 9), (cx + 8, cy), (cx, cy + 9), (cx - 8, cy)])
        for o in self.obstacles:
            self._draw_obstacle(surf, o)
        ducking = "down" in self.app.held and self.on_ground and self.state == "run"
        self._draw_bot(surf, self._bot_rect(ducking), ducking)

        T.text(surf, "%05d" % self.score, (x + w - 16, y + 10), 22, T.FG, bold=True, mono=True, anchor="topright")
        T.text(surf, "Best %05d" % self.best, (x + w - 16, y + 38), 14, T.DIM, mono=True, anchor="topright")

        if self.state in ("ready", "over", "paused"):
            panel = pygame.Rect(0, 0, 360, 130)
            panel.center = (x + w // 2, y + 150)
            T.rrect(surf, T.PANEL, panel, 12)
            if self.state == "ready":
                title, sub = "Byte Run", "Jump the bugs, duck the nulls. Press A."
            elif self.state == "paused":
                title, sub = "Paused", "Press A or Start to resume"
            else:
                title, sub = "Segfault", "Score %d. Press A to ship again." % self.score
            T.text(surf, title, (panel.centerx, panel.y + 22), 30, T.GOOD if self.state != "over" else T.BAD,
                   bold=True, anchor="midtop")
            T.text(surf, sub, (panel.centerx, panel.y + 76), 15, T.DIM, anchor="midtop")
        surf.set_clip(clip)
