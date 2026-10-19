"""Sidebar layout (sections, groups, pinned order) follows you across accounts.

The desktop app keeps the layout per account in `preferences.epitaxyPrefs` of claude_desktop_config.json and
rebuilds its Local Storage from it at every start. cs_share merges that file between accounts, and its list union
mixes two accounts' section lists together. So a switch does this around the shared-settings merge:
  1. before the merge: remember the layout of the account being left (the app has just quit, so the file is current),
  2. after the merge: write that layout into the account being entered (under its own account key), and put it back
     into the account being left, undoing the merge's mixing.
Only the sidebar entries listed below are touched. Never raises: a problem is reported and the switch goes on.
"""
import copy
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs_config as C  # noqa: E402

CONFIG = "claude_desktop_config.json"
PER_ACCOUNT = ["dframe-code-sections", "dframe-group-scopes"]  # epitaxyPrefs[name][<account>/<org>]
WHOLE = ["dframe-local-slice", "starred-local-code-sessions", "starred-session-groups",
         "starred-local-routines", "starred-cowork-spaces", "ccd-sessions-filter"]
KEEP_BACKUPS = 5


def account_key(data_dir, sync_dirs):
    """'<account uuid>/<org uuid>' of the session folder that lives under this data folder."""
    for d in sync_dirs:
        if os.path.normpath(d).startswith(os.path.normpath(data_dir) + os.sep):
            return "/".join(os.path.normpath(d).split(os.sep)[-2:])
    return None


def _path(data_dir):
    return os.path.join(data_dir, CONFIG)


def _load(data_dir):
    with open(_path(data_dir), encoding="utf-8") as f:
        return json.load(f)


def _log(msg):
    try:
        os.makedirs(C.STATE_DIR, exist_ok=True)
        with open(os.path.join(C.STATE_DIR, "sync.log"), "a") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def capture(data_dir, key):
    """The sidebar layout of the account stored in data_dir, or None when there is nothing to copy."""
    try:
        prefs = _load(data_dir).get("preferences", {})
    except (OSError, ValueError):
        return None
    epi = prefs.get("epitaxyPrefs") or {}
    per = {n: copy.deepcopy(epi[n][key]) for n in PER_ACCOUNT if isinstance(epi.get(n), dict) and key in epi[n]}
    whole = {n: copy.deepcopy(epi[n]) for n in WHOLE if n in epi}
    if not per:
        return None
    return {"per": per, "whole": whole, "sidebarMode": prefs.get("sidebarMode")}


def _backup(data_dir, label):
    root = os.path.join(C.STATE_DIR, "layout-backups")
    dst = os.path.join(root, datetime.datetime.now().strftime("%Y%m%d-%H%M%S%f-") + label)
    os.makedirs(dst)
    shutil.copy2(_path(data_dir), os.path.join(dst, CONFIG))
    for old in sorted(os.listdir(root))[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)


def apply(data_dir, key, snap, label="x"):
    """Write snap into data_dir's config under the account key. Returns the names that changed."""
    cfg = _load(data_dir)
    prefs = cfg.setdefault("preferences", {})
    epi = prefs.setdefault("epitaxyPrefs", {})
    changed = []
    for n, v in snap["per"].items():
        cur = epi.setdefault(n, {})
        if cur.get(key) != v:
            cur[key] = copy.deepcopy(v)
            changed.append(n)
    for n, v in snap["whole"].items():
        if epi.get(n) != v:
            epi[n] = copy.deepcopy(v)
            changed.append(n)
    if snap.get("sidebarMode") and prefs.get("sidebarMode") != snap["sidebarMode"]:
        prefs["sidebarMode"] = snap["sidebarMode"]
        changed.append("sidebarMode")
    if changed:
        _backup(data_dir, label)
        tmp = _path(data_dir) + ".cs-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, _path(data_dir))
    return changed


def keys_for(conf, cur, target):
    src, dst = conf["profiles"][cur]["data_dir"], conf["profiles"][target]["data_dir"]
    return src, dst, account_key(src, conf["sync_dirs"]), account_key(dst, conf["sync_dirs"])


def before_share(conf, cur, target):
    """Step 1: remember the layout of the account being left. Returns an opaque token for after_share."""
    if cur not in conf["profiles"] or target not in conf["profiles"]:
        return None
    src, dst, sk, dk = keys_for(conf, cur, target)
    if not (sk and dk):
        _log("sidebar layout not synced: session folders not detected (run: claude-switch setup)")
        return None
    snap = capture(src, sk)
    if snap is None:
        _log("sidebar layout not synced: no layout found for the account being left")
        return None
    return snap


def after_share(conf, cur, target, snap):
    """Step 2: after the settings merge, give both accounts the remembered layout. Returns a one-line note."""
    if snap is None:
        return None
    src, dst, sk, dk = keys_for(conf, cur, target)
    try:
        done = apply(dst, dk, snap, label=conf["profiles"][target]["label"])
        apply(src, sk, snap, label=conf["profiles"][cur]["label"])  # undo the merge's mixing on the side we left
    except (OSError, ValueError) as e:
        msg = f"sidebar layout not synced: {e}"
    else:
        msg = "sidebar layout synced: " + ", ".join(done) if done else "sidebar layout already identical"
    _log(msg)
    return msg
