#!/usr/bin/env python3
"""Keep the desktop app's own settings identical across the account data folders.

Each data folder has its own copy of a few settings files (desktop MCP servers, preferences such as
starred sessions and session groups, Code-tab worktree records, MCP tool toggles). This merges them
so every account sees the same setup. Files that hold the login (config.json, cookies, tokens) are
never touched: that separation is what keeps every account logged in.

Three-way merge against the result of the previous run (state/share-base/<file>):
  - a key or list item one folder added, changed or removed since then is applied everywhere
  - two folders changed the same key differently: the most recently modified file wins
A folder the previous run did not merge holds the app's defaults, not changes: it adds the keys and list
items it has that the others lack, and never overrides or removes theirs. That covers a newly added account,
and, the first time a file is merged, every folder but the first account's (A, then B, ...) that has it.
A file that is not a JSON object counts as unreadable: its folder just receives the result.
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
MERGED_DIRS = "merged-dirs.json"  # in share-base: {settings file: [data folders the previous run merged]}


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


def fill(result, v):
    """Add the keys and list items v has and result lacks; where both have a value, result's stays."""
    if result is _MISSING:
        return v
    if isinstance(result, dict) and isinstance(v, dict):
        out = dict(result)
        for k, x in v.items():
            out[k] = fill(result.get(k, _MISSING), x)
        return out
    if isinstance(result, list) and isinstance(v, list):
        out, seen = list(result), {_id(x) for x in result}
        for x in v:
            if _id(x) not in seen:
                seen.add(_id(x))
                out.append(x)
        return out
    return result


def _id(v):
    return "<missing>" if v is _MISSING else json.dumps(v, sort_keys=True)


def _base_dir():
    return os.path.join(os.environ.get("CS_STATE_DIR") or cs_config.STATE_DIR, "share-base")


def _read(p):
    """The file's JSON object; _MISSING when it is absent, unreadable or not an object."""
    try:
        with open(p) as f:
            v = json.load(f)
    except (OSError, ValueError):
        return _MISSING
    return v if isinstance(v, dict) else _MISSING


def _created(d):
    """When folder d was created, or None where the platform does not record it."""
    st = os.stat(d)
    return getattr(st, "st_birthtime", st.st_ctime if cs_config.WINDOWS else None)  # Windows st_ctime is creation


def _write(p, data):
    tmp = p + ".cs-tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def share(data_dirs):
    """Merge SHARED_FILES across data_dirs. Returns the names of files that changed somewhere."""
    dirs = list(dict.fromkeys(cs_config._norm(d) for d in data_dirs if os.path.isdir(d)))  # one spelling per folder
    if len(dirs) < 2:
        return []
    os.makedirs(_base_dir(), exist_ok=True)
    record_path = os.path.join(_base_dir(), MERGED_DIRS)
    record = _read(record_path)
    if record is _MISSING:
        record = {}
    touched = []
    for name in SHARED_FILES:
        vals = {d: _read(os.path.join(d, name)) for d in dirs}
        if all(v is _MISSING for v in vals.values()):
            continue
        bp = os.path.join(_base_dir(), name)
        base = _read(bp)
        merged = record.get(name)
        if isinstance(merged, list) and all(isinstance(m, str) for m in merged):
            known = set(dirs) & {cs_config._norm(m) for m in merged}
        elif base is not _MISSING:  # a base without a folder record: the folders that existed when it was written
            written = os.path.getmtime(bp)
            known = {d for d in dirs if (_created(d) or 0) <= written}
        else:  # first merge of this file: the first account (A, then B, ...) that has it is the reference
            known = {next(d for d in dirs if vals[d] is not _MISSING)}
        old = sorted((d for d in dirs if d in known and vals[d] is not _MISSING),
                     key=lambda d: os.path.getmtime(os.path.join(d, name)))  # oldest -> newest
        # first run: nothing is "removed" yet, so start from an empty base and union
        result = merge({} if base is _MISSING else base, [vals[d] for d in old]) if old else base
        for d in dirs:  # a folder that joins only fills gaps, in account order
            if d not in known and vals[d] is not _MISSING:
                result = fill(result, vals[d])
        if result is _MISSING:
            continue
        for d in dirs:  # a folder without the file just receives the result
            if _id(vals[d]) != _id(result):
                _write(os.path.join(d, name), result)
                touched.append(name)
        _write(bp, result)
        record[name] = dirs
    _write(record_path, record)
    if touched:
        with open(os.path.join(os.path.dirname(_base_dir()), "sync.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "shared settings merged: " + ", ".join(sorted(set(touched))) + "\n")
    return sorted(set(touched))


if __name__ == "__main__":
    conf = cs_config.load()
    print(share([p["data_dir"] for p in conf["profiles"].values()]))
