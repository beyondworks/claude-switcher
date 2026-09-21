"""Claude Switcher shared paths and config.

Config lives at ~/.config/claude-switcher/config.json:
{
  "profiles": {"a": {"label": "A", "data_dir": ".../Claude"},
               "b": {"label": "B", "data_dir": ".../Claude Second"}},
  "sync_dirs": ["<data_dir>/claude-code-sessions/<account>/<org>", ...]
}
"""
import json
import os
import re

WINDOWS = os.name == "nt"
HOME = os.path.expanduser("~")

if WINDOWS:
    # Verified on a Windows runner with the per-user (Squirrel) install: the stub launcher forwards
    # --user-data-dir to the current app-<version>\claude.exe, and each data folder has its own logs\main.log.
    _LOCAL = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
    _ROAMING = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
    APP = os.path.join(_LOCAL, "AnthropicClaude", "claude.exe")          # stub launcher, survives self-updates
    APP_BIN = "claude.exe"                                                 # process name to look for
    APP_SUPPORT = _ROAMING
    STATE_DIR = os.path.join(_LOCAL, "claude-switcher")
else:
    APP = "/Applications/Claude.app"
    APP_BIN = APP + "/Contents/MacOS/Claude"
    APP_SUPPORT = os.path.join(HOME, "Library/Application Support")
    STATE_DIR = os.path.join(APP_SUPPORT, "claude-switcher")

PRIMARY_DATA = os.path.join(APP_SUPPORT, "Claude")
SECOND_DATA = os.path.join(APP_SUPPORT, "Claude Second")
CLAUDE_LOG = os.path.join(HOME, "Library/Logs/Claude/main.log")  # macOS: one log for every data folder


def log_files(data_dirs):
    """macOS writes one shared main.log; Windows writes <data dir>\logs\main.log per data folder."""
    if WINDOWS:
        return [os.path.join(d, "logs", "main.log") for d in data_dirs]
    return [CLAUDE_LOG]

CONF_DIR = os.path.join(HOME, ".config/claude-switcher")
CONF = os.path.join(CONF_DIR, "config.json")

DEFAULT = {
    "profiles": {
        "a": {"label": "A", "data_dir": PRIMARY_DATA},
        "b": {"label": "B", "data_dir": SECOND_DATA},
    },
    "sync_dirs": [],
}


def load():
    try:
        with open(CONF) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT))
    for k, v in DEFAULT.items():
        c.setdefault(k, json.loads(json.dumps(v)))
    return c


def save(c):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONF)


_LOADED = re.compile(r"Loaded (\d+) persisted sessions from (.+?[/\\]claude-code-sessions[/\\][0-9a-f-]{36}[/\\][0-9a-f-]{36})")


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def detect_session_dirs(data_dirs, log_path=None):
    """For every (data dir, account) pair, return the org session folder the app uses.

    First source: the app log, which records every folder it reads with a session count. We keep the
    folder that ever loaded the most sessions (ties: the latest) — "most recent" alone is not reliable,
    because while logging out the app briefly reads another org folder (0 sessions) *after* the real one.
    Fallback for a data dir the log says nothing about: look at the folders on disk and take, per
    account, the org folder with the most session files (ties: most recently modified).
    """
    logs = [log_path] if log_path else log_files(data_dirs)
    best = {}  # (data_dir, account) -> (count, seq, path)
    seq = 0
    for lp in logs:
        try:
            with open(lp, errors="replace") as f:
                for line in f:
                    m = _LOADED.search(line)
                    if not m:
                        continue
                    seq += 1
                    count, path = int(m.group(1)), m.group(2)
                    for d in data_dirs:
                        root = os.path.join(d, "claude-code-sessions")
                        if _norm(path).startswith(_norm(root) + os.sep) or path.replace("\\", "/").startswith(root.replace("\\", "/") + "/"):
                            account = re.split(r"[/\\]", path[len(root) + 1:])[0]
                            key = (d, account)
                            if key not in best or (count, seq) >= best[key][:2]:
                                best[key] = (count, seq, os.path.join(root, account, re.split(r"[/\\]", path)[-1]))
        except OSError:
            continue
    seen = {d for d, _ in best}
    for d in data_dirs:
        if d in seen:
            continue
        root = os.path.join(d, "claude-code-sessions")
        if not os.path.isdir(root):
            continue
        for account in sorted(os.listdir(root)):
            adir = os.path.join(root, account)
            if not os.path.isdir(adir) or os.path.islink(adir):
                continue
            orgs = [os.path.join(adir, o) for o in os.listdir(adir) if os.path.isdir(os.path.join(adir, o))]
            if orgs:
                pick = max(orgs, key=lambda o: (sum(n.startswith("local_") for n in os.listdir(o)), os.path.getmtime(o)))
                best[(d, account)] = (0, 0, pick)
    return [v[2] for v in best.values()]
