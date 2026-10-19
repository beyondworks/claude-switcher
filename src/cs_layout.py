"""Sidebar layout (sections, groups, pinned order) follows you across accounts.

The desktop app keeps these in each data folder's Local Storage, one copy per account, so two accounts drift apart
even though the session list is shared. At a switch, after the old app has quit, cs_layout.js copies the layout of the
account you are leaving into the account you are entering. Only the sidebar entries are copied; logins stay as they are.
Needs node and the `classic-level` package (install.sh installs it next to this file). Without them the switch still
works and this step is skipped with a note.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs_config as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "cs_layout.js")
KEEP_BACKUPS = 5
NODE_CANDIDATES = ["/opt/homebrew/bin/node", "/usr/local/bin/node", os.path.join(C.HOME, "Tools/node/bin/node")]


def find_node():
    return shutil.which("node") or next((p for p in NODE_CANDIDATES if os.path.isfile(p)), None)


def leveldb_dir(data_dir):
    return os.path.join(data_dir, "Local Storage", "leveldb")


def account_key(data_dir, sync_dirs):
    """'<account uuid>/<org uuid>' of the session folder that lives under this data folder."""
    for d in sync_dirs:
        if os.path.normpath(d).startswith(os.path.normpath(data_dir) + os.sep):
            parts = os.path.normpath(d).split(os.sep)
            return "/".join(parts[-2:])
    return None


def _log(msg):
    try:
        os.makedirs(C.STATE_DIR, exist_ok=True)
        with open(os.path.join(C.STATE_DIR, "sync.log"), "a") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def _backup(data_dir, label):
    root = os.path.join(C.STATE_DIR, "layout-backups")
    dst = os.path.join(root, datetime.datetime.now().strftime("%Y%m%d-%H%M%S%f-") + label)
    shutil.copytree(leveldb_dir(data_dir), os.path.join(dst, "leveldb"))
    for old in sorted(os.listdir(root))[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    return dst


def copy_layout(src_dir, dst_dir, src_key, dst_key, label="to", backup=True):
    """Copy the layout from src_dir to dst_dir (both apps closed). Returns (ok, message)."""
    node = find_node()
    if not node:
        return False, "node not found; sidebar layout not synced"
    if not os.path.isdir(os.path.join(HERE, "node_modules", "classic-level")):
        return False, "classic-level is not installed next to cs_layout.js (run install.sh); sidebar layout not synced"
    if not (os.path.isdir(leveldb_dir(src_dir)) and os.path.isdir(leveldb_dir(dst_dir))):
        return False, "Local Storage not found; sidebar layout not synced"
    try:
        if backup:
            _backup(dst_dir, label)
        env = dict(os.environ, NODE_PATH=os.path.join(HERE, "node_modules"))
        r = subprocess.run([node, SCRIPT, leveldb_dir(src_dir), leveldb_dir(dst_dir), src_key, dst_key],
                           capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError, shutil.Error) as e:
        return False, f"sidebar layout not synced: {e}"
    if r.returncode != 0:
        return False, "sidebar layout not synced: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1]
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, "sidebar layout not synced: unreadable result"
    return True, ("sidebar layout synced: " + ", ".join(out["changed"])) if out["changed"] else "sidebar layout already identical"


def sync_switch(conf, cur, target):
    """Called during a switch, after the old app has quit. Never raises, never blocks the switch."""
    if C.WINDOWS or cur not in conf["profiles"] or target not in conf["profiles"]:
        return None
    src, dst = conf["profiles"][cur]["data_dir"], conf["profiles"][target]["data_dir"]
    sk, dk = account_key(src, conf["sync_dirs"]), account_key(dst, conf["sync_dirs"])
    if not (sk and dk):
        ok, msg = False, "session folders not detected; run: claude-switch setup"
    else:
        ok, msg = copy_layout(src, dst, sk, dk, label=conf["profiles"][target]["label"])
    _log(msg)
    return msg
