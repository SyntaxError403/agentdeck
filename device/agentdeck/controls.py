"""Turns joystick, hat, axis and keyboard events into named actions.

Actions: up down left right a b x y l1 r1 l2 r2 select start menu
Button numbers differ between firmwares. Run `python3 main.py --input-test`
on the device and copy the numbers into config.json -> "buttons".
"""
import pygame

DEFAULT_BUTTONS = {
    "a": 0, "b": 1, "y": 2, "x": 3,
    "l1": 4, "r1": 5, "select": 6, "start": 7, "menu": 8,
    "l2": 9, "r2": 10,
}

KEYMAP = {
    pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
    pygame.K_z: "a", pygame.K_RETURN: "a", pygame.K_SPACE: "a",
    pygame.K_x: "b", pygame.K_ESCAPE: "b", pygame.K_BACKSPACE: "b",
    pygame.K_a: "x", pygame.K_s: "y",
    pygame.K_q: "l1", pygame.K_w: "r1", pygame.K_e: "l2", pygame.K_r: "r2",
    pygame.K_TAB: "select", pygame.K_p: "start", pygame.K_m: "menu",
}

HAT_DIRS = (("up", lambda v: v[1] > 0), ("down", lambda v: v[1] < 0),
            ("left", lambda v: v[0] < 0), ("right", lambda v: v[0] > 0))


class Controls:
    def __init__(self, cfg):
        buttons = dict(DEFAULT_BUTTONS)
        buttons.update(cfg.get("buttons", {}))
        buttons.update(cfg.get("dpad_buttons", {}))  # firmwares that report the d-pad as buttons
        self.by_index = {}
        for action, idx in buttons.items():
            if isinstance(idx, int):
                self.by_index[idx] = action
        self.deadzone = float(cfg.get("axis_deadzone", 0.5))
        self.hat_state = set()
        self.axis_state = set()
        self.sticks = {}
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            self._open(i)

    def _open(self, index):
        try:
            js = pygame.joystick.Joystick(index)
            js.init()
            self.sticks[js.get_instance_id()] = js
        except pygame.error:
            pass

    def _diff(self, old, new):
        out = [(a, True) for a in new - old] + [(a, False) for a in old - new]
        return out

    def translate(self, ev):
        """Return a list of (action, pressed) tuples for one pygame event."""
        t = ev.type
        if t == pygame.JOYDEVICEADDED:
            self._open(ev.device_index)
            return []
        if t == pygame.JOYDEVICEREMOVED:
            self.sticks.pop(ev.instance_id, None)
            return []
        if t in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
            action = self.by_index.get(ev.button)
            return [(action, t == pygame.JOYBUTTONDOWN)] if action else []
        if t == pygame.JOYHATMOTION:
            new = {name for name, test in HAT_DIRS if test(ev.value)}
            out = self._diff(self.hat_state, new)
            self.hat_state = new
            return out
        if t == pygame.JOYAXISMOTION and ev.axis in (0, 1):
            keep = ("up", "down") if ev.axis == 0 else ("left", "right")
            new = {a for a in self.axis_state if a in keep}  # other axis is unchanged
            if ev.axis == 0:
                if ev.value < -self.deadzone:
                    new.add("left")
                elif ev.value > self.deadzone:
                    new.add("right")
            else:
                if ev.value < -self.deadzone:
                    new.add("up")
                elif ev.value > self.deadzone:
                    new.add("down")
            out = self._diff(self.axis_state, new)
            self.axis_state = new
            return out
        if t in (pygame.KEYDOWN, pygame.KEYUP):
            action = KEYMAP.get(ev.key)
            return [(action, t == pygame.KEYDOWN)] if action else []
        return []
