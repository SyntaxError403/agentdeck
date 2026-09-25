#!/usr/bin/env python3
"""AgentDeck agent.

Runs on your Mac. Exposes tmux-hosted Claude Code and Codex sessions,
machine stats and GitHub stats to the AgentDeck handheld over HTTP.
Standard library only (Python 3.8+).
"""
import argparse
import calendar
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0"
CONFIG_DIR = os.path.expanduser("~/.agentdeck")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]

PANE_RE = re.compile(r"^%\d+$")
NAMED_KEYS = {"Enter", "Escape", "Up", "Down", "Left", "Right", "Tab", "BTab", "Space", "BSpace", "C-c"}
CHAR_KEYS = set("yn123456789")
MAX_TEXT = 500

# Heuristic: does the bottom of the pane look like the agent is asking something?
WAIT_PATTERNS = [re.compile(p) for p in (
    r"do you want",
    r"\(y/n\)",
    r"\[y/n\]",
    r"press enter",
    r"\u276f\s*1\.",          # "❯ 1." selection menu
    r"\b1\.\s*yes\b",
    r"allow (this|once|always|command)",
    r"approve",
    r"don't ask again",
    r"waiting for (your )?(input|approval)",
)]


# --------------------------------------------------------------------------- utils

def which(name):
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_PATHS:
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def run(cmd, timeout=5):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


TMUX = which("tmux")
IS_MAC = sys.platform == "darwin"


# --------------------------------------------------------------------------- config

def load_config():
    cfg = {"port": 8765, "bind": "0.0.0.0", "token": "", "github_token": "", "show_all_panes": False}
    file_cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                file_cfg = json.load(f)
        except (OSError, ValueError) as e:
            print("warning: could not read %s: %s" % (CONFIG_PATH, e), file=sys.stderr)
    cfg.update(file_cfg)

    if not cfg["token"]:
        cfg["token"] = secrets.token_urlsafe(16)
        file_cfg["token"] = cfg["token"]
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(file_cfg, f, indent=2)
        os.chmod(CONFIG_PATH, 0o600)

    env = os.environ
    if env.get("AGENTDECK_TOKEN"):
        cfg["token"] = env["AGENTDECK_TOKEN"]
    if env.get("AGENTDECK_PORT"):
        cfg["port"] = int(env["AGENTDECK_PORT"])
    if env.get("AGENTDECK_BIND"):
        cfg["bind"] = env["AGENTDECK_BIND"]
    if env.get("GITHUB_TOKEN"):
        cfg["github_token"] = env["GITHUB_TOKEN"]
    if not cfg["github_token"]:
        gh = which("gh")
        if gh:
            cfg["github_token"] = run([gh, "auth", "token"]).strip()
    return cfg


# --------------------------------------------------------------------------- tmux

PANE_FMT = "\t".join([
    "#{pane_id}", "#{session_name}", "#{window_index}", "#{window_name}", "#{pane_index}",
    "#{pane_pid}", "#{pane_current_command}", "#{pane_current_path}", "#{window_activity}",
    "#{session_attached}", "#{pane_width}", "#{pane_height}",
])


def process_table():
    out = run(["ps", "-A", "-o", "pid=,ppid=,command="])
    children, cmds = {}, {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        cmds[pid] = parts[2] if len(parts) > 2 else ""
        children.setdefault(ppid, []).append(pid)
    return children, cmds


def detect_agent(pane_pid, children, cmds):
    """Walk the pane's process tree looking for claude or codex."""
    stack, seen = [pane_pid], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for tok in cmds.get(pid, "").split()[:2]:
            name = os.path.basename(tok).lower()
            if name.startswith("claude"):
                return "claude"
            if name.startswith("codex"):
                return "codex"
        stack.extend(children.get(pid, []))
    return None


def capture(pane, lines=60):
    if not TMUX:
        return ""
    out = run([TMUX, "capture-pane", "-p", "-J", "-t", pane, "-S", "-%d" % lines])
    rows = [r.rstrip() for r in out.split("\n")]
    while rows and not rows[-1]:
        rows.pop()
    return "\n".join(rows[-lines:])


def looks_waiting(text):
    tail = "\n".join(text.splitlines()[-15:]).lower()
    return any(p.search(tail) for p in WAIT_PATTERNS)


def list_sessions(show_all):
    if not TMUX:
        return []
    out = run([TMUX, "list-panes", "-a", "-F", PANE_FMT])
    if not out:
        return []
    children, cmds = process_table()
    now = time.time()
    result = []
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) < 12:
            continue
        pid = int(f[5]) if f[5].isdigit() else 0
        tool = detect_agent(pid, children, cmds)
        if not tool and not show_all:
            continue
        tail = capture(f[0], 25)
        nonblank = [r for r in tail.splitlines() if r.strip()]
        activity = int(f[8]) if f[8].isdigit() else 0
        result.append({
            "pane": f[0],
            "session": f[1],
            "window": f[2],
            "window_name": f[3],
            "index": f[4],
            "tool": tool or "shell",
            "command": f[6],
            "cwd": f[7],
            "idle_s": max(0, int(now - activity)) if activity else None,
            "attached": f[9] not in ("0", ""),
            "size": [int(f[10] or 0), int(f[11] or 0)],
            "waiting": bool(tool) and looks_waiting(tail),
            "last_line": nonblank[-1].strip()[:160] if nonblank else "",
        })
    return result


def send_keys(pane, keys=None, text=None, enter=False):
    if not TMUX:
        raise ValueError("tmux not found on this machine")
    if not PANE_RE.match(pane or ""):
        raise ValueError("bad pane id")
    keys = keys or []
    for k in keys:
        if k not in NAMED_KEYS and k not in CHAR_KEYS:
            raise ValueError("key not allowed: %r" % k)
    if text:
        if len(text) > MAX_TEXT or "\n" in text:
            raise ValueError("text too long or multi-line")
        run([TMUX, "send-keys", "-t", pane, "-l", text])
        time.sleep(0.05)
    for k in keys:
        run([TMUX, "send-keys", "-t", pane, k])
    if enter:
        run([TMUX, "send-keys", "-t", pane, "Enter"])


# --------------------------------------------------------------------------- machine stats

def _static_info():
    info = {"host": socket.gethostname().split(".")[0], "model": "", "chip": "", "os": ""}
    if IS_MAC:
        info["model"] = run(["sysctl", "-n", "hw.model"]).strip()
        info["chip"] = run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        info["os"] = "macOS " + run(["sw_vers", "-productVersion"]).strip()
    else:
        info["os"] = sys.platform
    return info


def _cpu_percent():
    if IS_MAC:
        out = run(["top", "-l", "2", "-n", "0", "-s", "1"], timeout=8)
        m = re.findall(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle", out)
        if m:
            return round(100.0 - float(m[-1][2]), 1)
        return None
    try:  # Linux fallback, handy for testing
        def snap():
            with open("/proc/stat") as f:
                vals = [int(x) for x in f.readline().split()[1:]]
            return vals[3] + vals[4], sum(vals)
        i1, t1 = snap()
        time.sleep(1)
        i2, t2 = snap()
        return round(100.0 * (1 - (i2 - i1) / max(1, t2 - t1)), 1)
    except OSError:
        return None


def _memory():
    if IS_MAC:
        total = int(run(["sysctl", "-n", "hw.memsize"]).strip() or 0)
        vm = run(["vm_stat"])
        m = re.search(r"page size of (\d+) bytes", vm)
        page = int(m.group(1)) if m else 16384

        def pages(label):
            mm = re.search(r"%s:\s+(\d+)" % re.escape(label), vm)
            return int(mm.group(1)) if mm else 0

        used = (pages("Pages active") + pages("Pages wired down")
                + pages("Pages occupied by compressor")) * page
        return {"used": used, "total": total}
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        return {"used": info["MemTotal"] - info.get("MemAvailable", 0), "total": info["MemTotal"]}
    except (OSError, KeyError, ValueError):
        return None


def _disk():
    path = "/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else "/"
    try:
        du = shutil.disk_usage(path)
        return {"used": du.used, "total": du.total, "free": du.free}
    except OSError:
        return None


def _battery():
    if not IS_MAC:
        return None
    out = run(["pmset", "-g", "batt"])
    m = re.search(r"(\d+)%;\s*([^;]+);", out)
    if not m:
        return None
    return {"percent": int(m.group(1)), "state": m.group(2).strip(), "ac": "AC Power" in out}


def _uptime():
    if IS_MAC:
        m = re.search(r"sec = (\d+)", run(["sysctl", "-n", "kern.boottime"]))
        return int(time.time() - int(m.group(1))) if m else None
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except OSError:
        return None


def _top_procs(n=5):
    cmd = ["ps", "-A", "-o", "%cpu=,%mem=,comm=", "-r"] if IS_MAC else \
          ["ps", "-eo", "%cpu=,%mem=,comm=", "--sort=-%cpu"]
    procs = []
    for line in run(cmd).splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            procs.append({"cpu": float(parts[0]), "mem": float(parts[1]),
                          "name": os.path.basename(parts[2])[:28]})
        except ValueError:
            continue
        if len(procs) >= n:
            break
    return procs


class StatsCollector(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.static = _static_info()
        self.data = {"ok": False}

    def run(self):
        while True:
            try:
                d = dict(self.static)
                d.update({
                    "ok": True,
                    "cpu": _cpu_percent(),
                    "mem": _memory(),
                    "disk": _disk(),
                    "battery": _battery(),
                    "load": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
                    "uptime_s": _uptime(),
                    "procs": _top_procs(),
                    "ts": time.time(),
                })
            except Exception as e:  # keep the loop alive no matter what
                d = {"ok": False, "error": str(e)}
            with self.lock:
                self.data = d
            time.sleep(2)

    def get(self):
        with self.lock:
            return dict(self.data)


# --------------------------------------------------------------------------- GitHub

GH_QUERY = """
query {
  viewer {
    login
    name
    pullRequests(states: OPEN) { totalCount }
    issues(states: OPEN) { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def _event_verb(ev):
    t = ev.get("type", "")
    p = ev.get("payload") or {}
    if t == "PushEvent":
        n = p.get("size") or len(p.get("commits") or []) or 1
        return "pushed %d commit%s" % (n, "" if n == 1 else "s")
    if t == "PullRequestEvent":
        return "PR " + p.get("action", "")
    if t == "PullRequestReviewEvent":
        return "reviewed PR"
    if t == "IssuesEvent":
        return "issue " + p.get("action", "")
    if t == "IssueCommentEvent":
        return "commented"
    if t == "CreateEvent":
        return "created " + (p.get("ref_type") or "")
    if t == "DeleteEvent":
        return "deleted " + (p.get("ref_type") or "")
    if t == "WatchEvent":
        return "starred"
    if t == "ForkEvent":
        return "forked"
    if t == "ReleaseEvent":
        return "released"
    return t.replace("Event", "").lower()


class GitHubCollector(threading.Thread):
    daemon = True
    INTERVAL = 90

    def __init__(self, token):
        super().__init__()
        self.token = token
        self.lock = threading.Lock()
        if token:
            self.data = {"ok": False, "error": "loading"}
        else:
            self.data = {"ok": False, "error": "no_token"}

    def _req(self, url, body=None):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "agentdeck/" + VERSION,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))

    def fetch(self):
        d = {"ok": True, "ts": time.time()}
        g = self._req("https://api.github.com/graphql", {"query": GH_QUERY})
        if g.get("errors"):
            raise RuntimeError(g["errors"][0].get("message", "GraphQL error"))
        v = g["data"]["viewer"]
        cal = v["contributionsCollection"]["contributionCalendar"]
        weeks = [[day["contributionCount"] for day in w["contributionDays"]] for w in cal["weeks"]]
        days = [day for w in cal["weeks"] for day in w["contributionDays"]]
        counts = [day["contributionCount"] for day in days]

        streak = 0
        i = len(counts) - 1
        if i >= 0 and counts[i] == 0:
            i -= 1  # today not counted yet does not break the streak
        while i >= 0 and counts[i] > 0:
            streak += 1
            i -= 1

        d.update({
            "login": v["login"],
            "name": v.get("name") or v["login"],
            "open_prs": v["pullRequests"]["totalCount"],
            "open_issues": v["issues"]["totalCount"],
            "year_total": cal["totalContributions"],
            "today": counts[-1] if counts else 0,
            "streak": streak,
            "weeks": weeks[-16:],
        })

        try:
            q = urllib.parse.quote("is:pr is:open review-requested:@me")
            d["review_requests"] = self._req(
                "https://api.github.com/search/issues?per_page=1&q=" + q).get("total_count", 0)
        except Exception:
            d["review_requests"] = None
        try:
            d["notifications"] = len(self._req("https://api.github.com/notifications?per_page=50"))
        except Exception:
            d["notifications"] = None  # fine-grained tokens cannot read notifications
        try:
            evs = self._req("https://api.github.com/users/%s/events?per_page=12" % v["login"])
            now = time.time()
            items = []
            for ev in evs:
                ts = calendar.timegm(time.strptime(ev["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
                items.append({"verb": _event_verb(ev), "repo": ev.get("repo", {}).get("name", ""),
                              "ago_s": max(0, int(now - ts))})
            d["events"] = items[:8]
        except Exception:
            d["events"] = []
        return d

    def run(self):
        if not self.token:
            return
        while True:
            try:
                d = self.fetch()
            except urllib.error.HTTPError as e:
                d = {"ok": False, "error": "GitHub HTTP %d" % e.code}
            except Exception as e:
                d = {"ok": False, "error": str(e)[:200]}
            with self.lock:
                if d.get("ok") or not self.data.get("ok"):
                    self.data = d
                else:
                    self.data["stale_error"] = d.get("error")
            time.sleep(self.INTERVAL)

    def get(self):
        with self.lock:
            return dict(self.data)


# --------------------------------------------------------------------------- HTTP

CFG = {}
STATS = None
GITHUB = None
VERBOSE = False


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentDeck/" + VERSION

    def log_message(self, fmt, *args):
        if VERBOSE:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        tok = self.headers.get("X-AgentDeck-Token", "")
        if secrets.compare_digest(tok.encode("utf-8"), CFG["token"].encode("utf-8")):
            return True
        self._json(401, {"error": "bad token"})
        return False

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/health":
            return self._json(200, {"ok": True, "app": "agentdeck", "version": VERSION})
        if not self._authed():
            return
        if u.path == "/api/sessions":
            show_all = CFG.get("show_all_panes") or q.get("all", ["0"])[0] == "1"
            return self._json(200, {"ok": True, "tmux": bool(TMUX), "sessions": list_sessions(show_all)})
        if u.path == "/api/screen":
            pane = q.get("pane", [""])[0]
            if not PANE_RE.match(pane):
                return self._json(400, {"error": "bad pane id"})
            try:
                lines = max(10, min(400, int(q.get("lines", ["120"])[0])))
            except ValueError:
                lines = 120
            return self._json(200, {"ok": True, "pane": pane, "text": capture(pane, lines), "ts": time.time()})
        if u.path == "/api/stats":
            return self._json(200, STATS.get())
        if u.path == "/api/github":
            return self._json(200, GITHUB.get())
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 8192:
            return self._json(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad json"})
        if urllib.parse.urlparse(self.path).path == "/api/keys":
            try:
                send_keys(body.get("pane", ""), body.get("keys"), body.get("text"), bool(body.get("enter")))
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


def show_config(cfg):
    ip = lan_ip()
    print("AgentDeck agent %s" % VERSION)
    print("  tmux:    %s" % (TMUX or "NOT FOUND (brew install tmux)"))
    print("  github:  %s" % ("token found" if cfg.get("github_token") else "no token (optional)"))
    print("  listen:  %s:%d" % (cfg["bind"], cfg["port"]))
    print("")
    print("Put this in device/agentdeck/config.json on the handheld:")
    print(json.dumps({"host": ip, "port": cfg["port"], "token": cfg["token"]}, indent=2))


def main():
    global CFG, STATS, GITHUB, VERBOSE
    ap = argparse.ArgumentParser(description="AgentDeck Mac agent")
    ap.add_argument("--show-config", action="store_true", help="print connection info and exit")
    ap.add_argument("--port", type=int)
    ap.add_argument("--bind")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    CFG = load_config()
    if args.port:
        CFG["port"] = args.port
    if args.bind:
        CFG["bind"] = args.bind
    VERBOSE = args.verbose

    if args.show_config:
        show_config(CFG)
        return

    STATS = StatsCollector()
    STATS.start()
    GITHUB = GitHubCollector(CFG.get("github_token", ""))
    GITHUB.start()

    show_config(CFG)
    server = ThreadingHTTPServer((CFG["bind"], CFG["port"]), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
