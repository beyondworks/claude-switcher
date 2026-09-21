#!/usr/bin/env python3
"""Keep the Claude desktop Code-tab session lists of several accounts identical.

The app refuses to write into a session folder that is a symlink (it opens it with O_NOFOLLOW),
so every account keeps a real folder and this script copies changes between them:

  - present everywhere but different  -> the most recently modified copy wins
  - missing somewhere:
        present in all folders at the last sync -> it was deleted somewhere -> move it to trash everywhere
        otherwise                               -> it is new -> copy it where it is missing
  - nothing is deleted outright: removed files go to <state>/trash/<date>/
  - if one run would remove more than 20% of all files (and more than 5), it stops and logs instead
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs_config  # noqa: E402

MAX_DELETE_RATIO = 0.2
TMP_PREFIX = ".cs-tmp-"


def _dirs():
    if os.environ.get("CS_SYNC_DIRS"):
        return os.environ["CS_SYNC_DIRS"].split(os.pathsep)
    return cs_config.load()["sync_dirs"]


def _state_dir():
    return os.environ.get("CS_STATE_DIR") or cs_config.STATE_DIR


def log(msg):
    d = _state_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "sync.log"), "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def files(d):
    return {n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)) and not n.startswith(TMP_PREFIX)}


def same(p, q):
    if os.path.getsize(p) != os.path.getsize(q):
        return False
    with open(p, "rb") as x, open(q, "rb") as y:
        return x.read() == y.read()


def copy(src, dst):
    tmp = os.path.join(os.path.dirname(dst), TMP_PREFIX + os.path.basename(dst))
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)  # atomic: the app never sees a half-written file


def trash(path, dirs):
    t = os.path.join(_state_dir(), "trash", time.strftime("%Y%m%d"), str(dirs.index(os.path.dirname(path))))
    os.makedirs(t, exist_ok=True)
    shutil.move(path, os.path.join(t, os.path.basename(path)))


def sync(dirs):
    if len(dirs) < 2:
        return 0
    for d in dirs:
        if not os.path.isdir(d) or os.path.islink(d):
            log(f"stopped: not a real folder: {d}")
            return 1
    state = os.path.join(_state_dir(), "sync-state.json")
    known = None
    if os.path.exists(state):
        with open(state) as f:
            st = json.load(f)
        if st.get("dirs") == dirs:  # a different folder set means a fresh start (merge, no deletions)
            known = set(st["files"])
    have = {d: files(d) for d in dirs}
    names = set().union(*have.values())
    plan = []
    for n in sorted(names):
        present = [d for d in dirs if n in have[d]]
        newest = max(present, key=lambda d: os.path.getmtime(os.path.join(d, n)))
        src = os.path.join(newest, n)
        if len(present) == len(dirs):
            plan += [("copy", src, os.path.join(d, n)) for d in present if d != newest and not same(src, os.path.join(d, n))]
        elif known is not None and n in known:
            plan += [("trash", os.path.join(d, n), None) for d in present]
        else:
            plan += [("copy", src, os.path.join(d, n)) for d in dirs if d not in present]
    removed = {os.path.basename(p[1]) for p in plan if p[0] == "trash"}
    if len(removed) > 5 and len(removed) / max(len(names), 1) > MAX_DELETE_RATIO:
        log(f"stopped: would remove {len(removed)}/{len(names)} files — check manually")
        return 2
    for act, src, dst in plan:
        try:
            copy(src, dst) if act == "copy" else trash(src, dirs)
        except OSError as e:  # Windows: the app may hold the file open; the next run retries
            log(f"skipped {act} {os.path.basename(src)}: {e}")
    os.makedirs(_state_dir(), exist_ok=True)
    common = set.intersection(*(files(d) for d in dirs))
    with open(state + ".tmp", "w") as f:
        json.dump({"dirs": dirs, "files": sorted(common), "at": time.time()}, f)
    os.replace(state + ".tmp", state)
    if plan:
        log(f"synced: copied {sum(1 for p in plan if p[0] == 'copy')}, trashed {len(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(sync(_dirs()))
