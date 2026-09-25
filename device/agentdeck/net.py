"""Talks to the Mac agent. All network calls happen on a background thread
so the UI never blocks on Wi-Fi."""
import json
import queue
import threading
import time
import urllib.error
import urllib.request


class Api:
    def __init__(self, host, port, token, timeout=3.0):
        self.base = "http://%s:%d" % (host, int(port))
        self.token = token
        self.timeout = timeout

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "X-AgentDeck-Token": self.token,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise RuntimeError("Token rejected. Check token in config.json")
            raise RuntimeError("Agent returned HTTP %d" % e.code)

    def sessions(self):
        return self._req("GET", "/api/sessions")

    def screen(self, pane, lines=150):
        return self._req("GET", "/api/screen?pane=%s&lines=%d" % (pane.replace("%", "%25"), lines))

    def stats(self):
        return self._req("GET", "/api/stats")

    def github(self):
        return self._req("GET", "/api/github")

    def keys(self, pane, keys=None, text=None, enter=False):
        return self._req("POST", "/api/keys", {"pane": pane, "keys": keys or [], "text": text, "enter": enter})


class Poller(threading.Thread):
    daemon = True
    INTERVALS = {"sessions": 2.0, "screen": 0.7, "stats": 2.5, "github": 60.0}

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.lock = threading.Lock()
        self.data = {}
        self.stamp = {}
        self.next = {}
        self.outbox = queue.Queue()
        self.online = None      # None = not checked yet
        self.error = ""
        self.focus_pane = None  # pane shown in the session view
        self.want_stats = False
        self.want_github = False

    # ---- UI side
    def get(self, name):
        with self.lock:
            return self.data.get(name)

    def age(self, name):
        with self.lock:
            t = self.stamp.get(name)
        return None if t is None else time.time() - t

    def kick(self, name, delay=0.0):
        self.next[name] = time.time() + delay

    def send(self, pane, keys=None, text=None, enter=False):
        self.outbox.put({"pane": pane, "keys": keys, "text": text, "enter": enter})

    # ---- worker side
    def _store(self, name, value):
        with self.lock:
            self.data[name] = value
            self.stamp[name] = time.time()

    def _call(self, fn):
        try:
            result = fn()
            self.online, self.error = True, ""
            return result
        except Exception as e:
            self.online = False
            msg = str(e)
            if hasattr(e, "reason"):
                msg = str(e.reason)
            self.error = msg[:120]
            return None

    def run(self):
        while True:
            sent = False
            while True:
                try:
                    job = self.outbox.get_nowait()
                except queue.Empty:
                    break
                self._call(lambda: self.api.keys(**job))
                sent = True
            if sent:
                self.kick("screen", 0.15)
                self.kick("sessions", 0.4)

            now = time.time()
            pane = self.focus_pane
            wanted = {"sessions": True, "screen": pane is not None,
                      "stats": self.want_stats, "github": self.want_github}
            for name, on in wanted.items():
                if not on or now < self.next.get(name, 0):
                    continue
                self.next[name] = now + self.INTERVALS[name]
                if name == "screen":
                    res = self._call(lambda: self.api.screen(pane))
                else:
                    res = self._call(getattr(self.api, name))
                if res is not None:
                    self._store(name, res)
                if self.online is False:
                    # back off a little while the agent is unreachable
                    self.next[name] = max(self.next[name], now + 3.0)
            time.sleep(0.05)
