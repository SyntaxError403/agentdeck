"""Palette, fonts and small drawing helpers. Screen is 640x480."""
import glob
import os

import pygame

W, H = 640, 480
HERE = os.path.dirname(os.path.abspath(__file__))

BG = (20, 26, 42)          # deep navy
PANEL = (30, 39, 64)
RAISED = (42, 53, 86)
TERM_BG = (12, 16, 27)
FG = (230, 233, 242)
DIM = (138, 147, 173)
FAINT = (80, 90, 118)
CLAUDE = (242, 184, 75)    # amber tag for Claude Code
CODEX = (92, 200, 224)     # cyan tag for Codex
SHELL = (138, 147, 173)
ATTN = (255, 111, 168)     # needs input
GOOD = (123, 216, 143)
WARN = (242, 184, 75)
BAD = (255, 107, 107)

_fonts = {}
GOOD_MONO = False  # True when a font with box drawing glyphs is available


def _find_mono(bold):
    bundled = sorted(glob.glob(os.path.join(HERE, "fonts", "*.ttf")))
    if bundled:
        pick = [p for p in bundled if ("bold" in p.lower()) == bold] or bundled
        return pick[0], True
    try:
        for name in ("dejavusansmono", "liberationmono", "ubuntumono", "notosansmono", "monospace"):
            path = pygame.font.match_font(name, bold=bold)
            if path:
                return path, "dejavu" in path.lower() or "noto" in path.lower()
    except Exception:
        pass
    return None, False


def font(size, mono=False, bold=False):
    global GOOD_MONO
    key = (size, mono, bold)
    f = _fonts.get(key)
    if f is None:
        path, good = (None, False)
        if mono:
            path, good = _find_mono(bold)
            GOOD_MONO = GOOD_MONO or good
        if path:
            f = pygame.font.Font(path, size)
        else:
            f = pygame.font.Font(None, int(size * 1.3))
            f.set_bold(bold)
        _fonts[key] = f
    return f


# ASCII stand-ins for glyphs that the fallback font cannot draw.
_TERM_MAP = {
    "\u2500": "-", "\u2501": "-", "\u2502": "|", "\u2503": "|",
    "\u256d": "+", "\u256e": "+", "\u2570": "+", "\u256f": "+",
    "\u250c": "+", "\u2510": "+", "\u2514": "+", "\u2518": "+",
    "\u251c": "+", "\u2524": "+", "\u252c": "+", "\u2534": "+", "\u253c": "+",
    "\u276f": ">", "\u203a": ">", "\u25cf": "*", "\u23fa": "*", "\u2022": "*",
    "\u273b": "*", "\u2733": "*", "\u2736": "*", "\u273d": "*", "\u2722": "*", "\u00b7": ".",
    "\u23bf": "L", "\u2026": "...", "\u2192": "->", "\u2190": "<-", "\u2191": "^", "\u2193": "v",
    "\u2713": "v", "\u2714": "v", "\u2717": "x", "\u2718": "x", "\u26a0": "!",
    "\u2588": "#", "\u2591": ".", "\u2592": ":", "\u2593": "#",
    "\t": "    ",
}
_TERM_TABLE = str.maketrans(_TERM_MAP)
# Glyphs even DejaVu Sans Mono lacks; swap for close relatives it has.
_GOOD_TABLE = str.maketrans({"\u23fa": "\u25cf", "\u23bf": "\u2514", "\t": "    "})


def term_clean(line):
    if GOOD_MONO:
        return line.translate(_GOOD_TABLE)
    return line.translate(_TERM_TABLE)


def rrect(surf, color, rect, radius=8, width=0):
    try:
        pygame.draw.rect(surf, color, rect, width, border_radius=radius)
    except TypeError:  # very old pygame
        pygame.draw.rect(surf, color, rect, width)


def fit(text, f, maxw):
    if f.size(text)[0] <= maxw:
        return text
    while text and f.size(text + "...")[0] > maxw:
        text = text[:-1]
    return text + "..."


def text(surf, s, pos, size=16, color=FG, bold=False, mono=False, anchor="topleft", maxw=None):
    f = font(size, mono=mono, bold=bold)
    if maxw:
        s = fit(s, f, maxw)
    if not s:
        return pygame.Rect(pos, (0, 0))
    img = f.render(s, True, color)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def bar(surf, rect, frac, color, bg=RAISED):
    frac = max(0.0, min(1.0, frac or 0.0))
    rrect(surf, bg, rect, radius=rect[3] // 2)
    if frac > 0:
        w = max(rect[3], int(rect[2] * frac))
        rrect(surf, color, (rect[0], rect[1], w, rect[3]), radius=rect[3] // 2)


def level_color(frac):
    if frac is None:
        return DIM
    if frac < 0.6:
        return GOOD
    if frac < 0.85:
        return WARN
    return BAD


def human_bytes(n):
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.0f %s" if unit in ("B", "KB") else "%.1f %s") % (n, unit)
        n /= 1024.0


def human_age(s):
    if s is None:
        return ""
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm" % (s // 60)
    if s < 86400:
        return "%dh" % (s // 3600)
    return "%dd" % (s // 86400)
