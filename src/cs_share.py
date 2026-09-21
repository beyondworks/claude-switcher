#!/usr/bin/env python3
"""Keep the desktop app's own settings identical across the account data folders.

Each data folder has its own copy of a few settings files (desktop MCP servers, preferences such as
starred sessions and session groups, Code-tab worktree records, MCP tool toggles). This merges them
so every account sees the same setup. Files that hold the login (config.json, cookies, tokens) are
never touched: that separation is what keeps every account logged in.

Three-way merge against the result of the previous run (state/share-base/<file>):
  - a key or list item one folder added, changed or removed since then is applied everywhere
  - two folders changed the same key differently: the most recently modified file wins
Only run while no Claude window is open (the app rewrites these files from memory while running).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs_config  # noqa: E402

SHARED_FILES = ["claude_desktop_config.json", "git-worktrees.json", "mcp-user-tool-toggles.json", "developer_settings.json"]
_MISSING = object()


def merge(base, versions):
    """Three-way merge of JSON values. versions are ordered oldest -> newest file; _MISSING = absent."""
    changed = [v for v in versions if _id(v) != _id(base)]
    if not changed:
        return base
    if any(v is _MISSING for v in changed):  # one side removed it: the newest change (removal or edit) decides
        return changed[-1]
    if any(isinstance(v, dict) for v in versions) and all(v is _MISSING or isinstance(v, dict) for v in [base, *versions]):
        b = base if isinstance(base, dict) else {}
        vs = [v if isinstance(v, dict) else {} for v in versions]
        out = {}
        for k in dict.fromkeys([*b, *(k for v in vs for k in v)]):
            r = merge(b.get(k, _MISSING), [v.get(k, _MISSING) for v in vs])
            if r is not _MISSING:
                out[k] = r
        return out
    if all(isinstance(v, list) for v in versions) and (base is _MISSING or isinstance(base, list)):
        b = base if isinstance(base, list) else []
        gone = {_id(x) for x in b} - set.intersection(*({_id(x) for x in v} for v in versions))
        out, seen = [], set()
        for x in [*b, *(x for v in versions for x in v)]:  # union of additions, minus anything one side removed
            if _id(x) not in gone and _id(x) not in seen:
                seen.add(_id(x))
                out.append(x)
        return out
    return changed[-1]  # scalars, type changes, deletions: the newest change wins


def _id(v):
    return "<missing>" if v is _MISSING else json.dumps(v, sort_keys=True)


def _base_dir():
    return os.path.join(os.environ.get("CS_STATE_DIR") or cs_config.STATE_DIR, "share-base")


def _read(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return _MISSING


def _write(p, data):
    tmp = p + ".cs-tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def share(data_dirs):
    """Merge SHARED_FILES across data_dirs. Returns the names of files that changed somewhere."""
    dirs = [d for d in data_dirs if os.path.isdir(d)]
    if len(dirs) < 2:
        return []
    os.makedirs(_base_dir(), exist_ok=True)
    touched = []
    for name in SHARED_FILES:
        paths = sorted((os.path.join(d, name) for d in dirs),
                       key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)  # oldest -> newest
        vals = [_read(p) for p in paths]
        present = [v for v in vals if v is not _MISSING]  # a folder without the file just receives the result
        if not present:
            continue
        bp = os.path.join(_base_dir(), name)
        base = _read(bp)
        if base is _MISSING:  # first run: nothing is "removed" yet, so start from an empty base and union
            base = {}
        result = merge(base, present)
        if result is _MISSING:
            continue
        for p, v in zip(paths, vals):
            if _id(v) != _id(result):
                _write(p, result)
                touched.append(name)
        _write(bp, result)
    if touched:
        with open(os.path.join(os.path.dirname(_base_dir()), "sync.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "shared settings merged: " + ", ".join(sorted(set(touched))) + "\n")
    return sorted(set(touched))


if __name__ == "__main__":
    conf = cs_config.load()
    print(share([p["data_dir"] for p in conf["profiles"].values()]))
