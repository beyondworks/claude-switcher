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

HOME = os.path.expanduser("~")
APP = "/Applications/Claude.app"
APP_BIN = APP + "/Contents/MacOS/Claude"
APP_SUPPORT = os.path.join(HOME, "Library/Application Support")
PRIMARY_DATA = os.path.join(APP_SUPPORT, "Claude")
SECOND_DATA = os.path.join(APP_SUPPORT, "Claude Second")
CLAUDE_LOG = os.path.join(HOME, "Library/Logs/Claude/main.log")

CONF_DIR = os.path.join(HOME, ".config/claude-switcher")
CONF = os.path.join(CONF_DIR, "config.json")
STATE_DIR = os.path.join(APP_SUPPORT, "claude-switcher")

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


_LOADED = re.compile(r"Loaded (\d+) persisted sessions from (.+?/claude-code-sessions/[0-9a-f-]{36}/[0-9a-f-]{36})")


def detect_session_dirs(data_dirs, log_path=CLAUDE_LOG):
    """The app logs every account/org session folder it reads, with a session count. For every
    (data dir, account) pair, return the folder that ever loaded the most sessions (ties: the latest).

    "Most recent" alone is not reliable: while logging out, the app briefly reads another org folder
    of the old account (0 sessions) *after* the real one. A new account's first folder has 0 sessions
    and is the only one it has read, so it is still picked.
    """
    best = {}  # (data_dir, account) -> (count, seq, path)
    seq = 0
    try:
        with open(log_path, errors="replace") as f:
            for line in f:
                m = _LOADED.search(line)
                if not m:
                    continue
                seq += 1
                count, path = int(m.group(1)), m.group(2)
                for d in data_dirs:
                    root = d.rstrip("/") + "/claude-code-sessions/"
                    if path.startswith(root):
                        key = (d, path[len(root):].split("/")[0])
                        if key not in best or (count, seq) >= best[key][:2]:
                            best[key] = (count, seq, path)
    except OSError:
        pass
    return [v[2] for v in best.values()]
