#!/usr/bin/env python3
"""AgentDeck for Anbernic RG35XX Pro (640x480). Also runs on a desktop for testing."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pygame  # noqa: E402

import theme as T  # noqa: E402
from controls import Controls  # noqa: E402
from game import ByteRun  # noqa: E402
from net import Api, Poller  # noqa: E402
from screens import GitHubScreen, MacScreen, SessionsScreen  # noqa: E402

TOP_H, BOT_H = 40, 34
REPEAT_DELAY, REPEAT_RATE = 0.35, 0.09


def load_config(path=None):
    for p in (path, os.path.join(HERE, "config.json"), os.path.join(HERE, "config.example.json")):
        if p and os.path.exists(p):
            with open(p) as f:
                cfg = json.load(f)
            cfg["_path"] = p
            return cfg
    return {"host": "127.0.0.1", "port": 8765, "token": "", "_path": None}


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.api = Api(cfg.get("host", "127.0.0.1"), cfg.get("port", 8765), cfg.get("token", ""))
        self.poller = Poller(self.api)
        self.poller.start()
        self.held = set()
        self.next_repeat = {}
        self.toast_msg, self.toast_until = "", 0.0
        self.tabs = [SessionsScreen(self), MacScreen(self), GitHubScreen(self), ByteRun(self)]
        self.tab = 0
        self.tabs[0].on_show()

    @property
    def current(self):
        return self.tabs[self.tab]

    def set_tab(self, i):
        self.current.on_hide()
        self.tab = i % len(self.tabs)
        self.current.on_show()

    def toast(self, msg):
        self.toast_msg, self.toast_until = msg, time.time() + 1.4

    def press(self, action):
        if action == "l1":
            self.set_tab(self.tab - 1)
        elif action == "r1":
            self.set_tab(self.tab + 1)
        else:
            self.current.handle(action)

    def repeat_tick(self, now):
        for a in ("up", "down", "left", "right", "l2", "r2"):
            if a in self.held and now >= self.next_repeat.get(a, float("inf")):
                self.next_repeat[a] = now + REPEAT_RATE
                self.current.handle(a, repeat=True)

    # ---- drawing
    def draw_top(self, surf):
        surf.fill(T.PANEL, (0, 0, T.W, TOP_H))
        x = 10
        waiting = self.tabs[0].waiting_count()
        for i, s in enumerate(self.tabs):
            label = s.title
            f = T.font(16, bold=True)
            tw = f.size(label)[0] + 24
            extra = 22 if (i == 0 and waiting) else 0
            if i == self.tab:
                T.rrect(surf, T.RAISED, (x, 6, tw + extra, TOP_H - 12), 8)
            T.text(surf, label, (x + 12, TOP_H // 2), 16, T.FG if i == self.tab else T.DIM, bold=True,
                   anchor="midleft")
            if i == 0 and waiting:
                cx = x + tw + 6
                pygame.draw.circle(surf, T.ATTN, (cx, TOP_H // 2), 9)
                T.text(surf, str(waiting), (cx, TOP_H // 2), 13, T.TERM_BG, bold=True, anchor="center")
            x += tw + extra + 6
        online = self.poller.online
        dot = T.GOOD if online else (T.BAD if online is False else T.DIM)
        clock = time.strftime("%H:%M")
        r = T.text(surf, clock, (T.W - 12, TOP_H // 2), 16, T.FG, anchor="midright")
        pygame.draw.circle(surf, dot, (r.left - 12, TOP_H // 2), 5)

    def draw_bottom(self, surf):
        y = T.H - BOT_H
        surf.fill(T.PANEL, (0, y, T.W, BOT_H))
        x = 10
        for btn, label in self.current.hints():
            f = T.font(13, bold=True)
            bw = f.size(btn)[0] + 12
            T.rrect(surf, T.RAISED, (x, y + 7, bw, BOT_H - 14), 6)
            T.text(surf, btn, (x + bw // 2, y + BOT_H // 2), 13, T.FG, bold=True, anchor="center")
            r = T.text(surf, label, (x + bw + 6, y + BOT_H // 2), 14, T.DIM, anchor="midleft")
            x = r.right + 14
        if time.time() < self.toast_until:
            T.text(surf, self.toast_msg, (T.W - 12, y + BOT_H // 2), 14, T.GOOD, anchor="midright")

    def draw(self, surf):
        surf.fill(T.BG)
        body = (0, TOP_H, T.W, T.H - TOP_H - BOT_H)
        self.current.draw(surf, body)
        self.draw_top(surf)
        self.draw_bottom(surf)


def input_test(surf, controls):
    """Shows raw events so you can fill in config.json -> buttons."""
    lines = ["Input test. Press each button. Select+Start or close to exit."]
    clock = pygame.time.Clock()
    held = set()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            raw = None
            if ev.type == pygame.JOYBUTTONDOWN:
                raw = "button %d" % ev.button
            elif ev.type == pygame.JOYHATMOTION:
                raw = "hat %d value %s" % (ev.hat, ev.value)
            elif ev.type == pygame.JOYAXISMOTION and abs(ev.value) > 0.5:
                raw = "axis %d value %.2f" % (ev.axis, ev.value)
            elif ev.type == pygame.KEYDOWN:
                raw = "key %s" % pygame.key.name(ev.key)
            mapped = controls.translate(ev)
            for a, down in mapped:
                (held.add if down else held.discard)(a)
            if raw:
                names = ", ".join(a for a, d in mapped if d) or "unmapped"
                lines.append("%s  ->  %s" % (raw, names))
                lines = lines[-22:]
                print(lines[-1], flush=True)
        if {"select", "start"} <= held:
            return
        surf.fill(T.BG)
        for i, ln in enumerate(lines):
            T.text(surf, ln, (16, 12 + i * 20), 15, T.FG if i else T.CLAUDE, mono=True)
        pygame.display.flip()
        clock.tick(30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--input-test", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    pygame.display.init()  # no audio needed, skip the mixer
    pygame.font.init()
    pygame.joystick.init()
    fullscreen = cfg.get("fullscreen", True) and not args.windowed
    surf = pygame.display.set_mode((T.W, T.H), pygame.FULLSCREEN if fullscreen else 0)
    pygame.display.set_caption("AgentDeck")
    pygame.mouse.set_visible(False)
    controls = Controls(cfg)

    if args.input_test:
        input_test(surf, controls)
        pygame.quit()
        return

    app = App(cfg)
    clock = pygame.time.Clock()
    running = True
    while running:
        fps = 60 if isinstance(app.current, ByteRun) else 30
        dt = clock.tick(fps) / 1000.0
        now = time.time()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            for action, down in controls.translate(ev):
                if down:
                    app.held.add(action)
                    app.next_repeat[action] = now + REPEAT_DELAY
                    app.press(action)
                else:
                    app.held.discard(action)
                    app.next_repeat.pop(action, None)
        if {"select", "start"} <= app.held:
            running = False
        app.repeat_tick(now)
        app.current.update(dt)
        app.draw(surf)
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
