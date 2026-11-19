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
import copy
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cs_config  # noqa: E402

SHARED_FILES = ["claude_desktop_config.json", "git-worktrees.json", "mcp-user-tool-toggles.json", "developer_settings.json"]
_MISSING = object()

# Account-keyed values the app reads only for the signed-in account ("account unify", 2026-11-19).
# After the merge, the base account's value is copied onto every target account's key, so the sidebar
# sections, session groups, per-folder permission modes, the bypass-permissions gate and MCP tool toggles
# look the same whichever account is open. Set in config.json: "unify_from": "<account uuid>",
# "unify_to": ["<account uuid>", ...]. A key that is missing or shaped differently is skipped and logged.
EPI_MAPS = ["dframe-code-sections", "dframe-group-scopes"]          # epitaxyPrefs[name]["<account>/<org>"]
EPI_PREFIX = "epitaxy-folder-permission-mode-v2."                    # epitaxyPrefs[prefix + "<account>"]
PREF_MAPS = ["bypassPermissionsGateByAccount", "bypassPermissionsOptInByAccount"]  # preferences[name]["<account>"]


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


def unify(name, data, base, targets, notes, source=None):
    """Copy the base account's account-keyed values onto the target accounts. Returns a new value; never raises.
    source: the base account's own file as it was on disk before the merge. Its values are the ones copied (and put
    back on the base account too), because the merge's list union keeps the old order and mixes reorderings away."""
    if not base or not targets or not isinstance(data, dict):
        return data
    out = copy.deepcopy(data)
    src_all = source if isinstance(source, dict) else data

    def account_map(m, sm, label):
        if not isinstance(m, dict) or not isinstance(sm, dict):
            notes.append(f"{name}: {label} missing or not an object, skipped")
            return
        if base not in sm:
            notes.append(f"{name}: {label} has no value for the base account, skipped")
            return
        for t in [base, *targets]:
            m[t] = copy.deepcopy(sm[base])

    if name == "claude_desktop_config.json":
        prefs = out.get("preferences")
        sprefs = src_all.get("preferences") if isinstance(src_all.get("preferences"), dict) else {}
        if not isinstance(prefs, dict):
            notes.append(f"{name}: preferences missing, skipped")
            return out
        epi, sepi = prefs.get("epitaxyPrefs"), sprefs.get("epitaxyPrefs")
        if isinstance(epi, dict) and isinstance(sepi, dict):
            for m in EPI_MAPS:
                mp, smp = epi.get(m), sepi.get(m)
                if not isinstance(mp, dict) or not isinstance(smp, dict):
                    notes.append(f"{name}: {m} missing, skipped")
                    continue
                src = [k for k in smp if k.split("/")[0] == base]
                if len(src) != 1:
                    notes.append(f"{name}: {m} has {len(src)} keys for the base account, skipped")
                    continue
                for t in [base, *targets]:
                    dst = [k for k in mp if k.split("/")[0] == t]
                    if len(dst) != 1:
                        notes.append(f"{name}: {m} has {len(dst)} keys for account {t[:8]}, skipped")
                        continue
                    mp[dst[0]] = copy.deepcopy(smp[src[0]])
            if isinstance(sepi.get(EPI_PREFIX + base), dict):
                for t in [base, *targets]:
                    epi[EPI_PREFIX + t] = copy.deepcopy(sepi[EPI_PREFIX + base])
            else:
                notes.append(f"{name}: {EPI_PREFIX}<base> missing, skipped")
        else:
            notes.append(f"{name}: epitaxyPrefs missing or not an object, skipped")
        for m in PREF_MAPS:
            account_map(prefs.get(m), sprefs.get(m), m)
    elif name == "mcp-user-tool-toggles.json":
        account_map(out.get("owners"), src_all.get("owners"), "owners")
    return out


def _backup(paths, tag):
    """Copy the files about to be overwritten into a dated folder that Spotlight does not index."""
    root = os.path.join(os.path.dirname(_base_dir()), "unify-backups.noindex", tag)
    for p in paths:
        if os.path.exists(p):
            dst = os.path.join(root, os.path.basename(os.path.dirname(p)))
            os.makedirs(dst, exist_ok=True)
            shutil.copy2(p, os.path.join(dst, os.path.basename(p)))
    return root


def share(data_dirs, unify_from=None, unify_to=None):
    """Merge SHARED_FILES across data_dirs, then unify account-keyed values. Returns the names of files that changed."""
    if unify_from is None and unify_to is None:
        conf = cs_config.load()
        unify_from, unify_to = conf.get("unify_from"), conf.get("unify_to")
    targets = [t for t in (unify_to or []) if t and t != unify_from]
    notes, tag = [], time.strftime("%Y%m%d-%H%M%S")
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
        home = [d for d in dirs if unify_from and os.path.isdir(os.path.join(d, "claude-code-sessions", unify_from))]
        source = _read(os.path.join(home[0], name)) if len(home) == 1 else None  # the base account's own copy, before the merge
        unified = unify(name, result, unify_from, targets, notes, None if source is _MISSING else source)
        if _id(unified) != _id(result):
            _backup([p for p in paths if os.path.exists(p)], tag)
            result = unified
        for p, v in zip(paths, vals):
            if _id(v) != _id(result):
                _write(p, result)
                touched.append(name)
        _write(bp, result)
    if notes or touched:
        with open(os.path.join(os.path.dirname(_base_dir()), "sync.log"), "a") as f:
            for n in notes:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "account unify: " + n + "\n")
    if touched:
        with open(os.path.join(os.path.dirname(_base_dir()), "sync.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "shared settings merged: " + ", ".join(sorted(set(touched))) + "\n")
    return sorted(set(touched))


if __name__ == "__main__":
    conf = cs_config.load()
    print(share([p["data_dir"] for p in conf["profiles"].values()]))  # unify_from/unify_to come from the same config
