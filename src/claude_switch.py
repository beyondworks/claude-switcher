#!/usr/bin/env python3
"""claude-switch — switch the Claude desktop app between accounts without logging in again.

Each account runs the app with its own data folder (so each stays logged in), and only one runs
at a time. Code-tab session lists are kept identical by cs_sync (launchd).

  claude-switch               switch to the next account (A → B → C … → A; starts A if nothing runs)
  claude-switch <key>         switch to that account (a, b, c, …)
  claude-switch status        show the running account (--short: a / b / … / none / many)
  claude-switch setup         detect session folders from the app log, install/refresh the sync agent
  claude-switch add [label]   add the next account and open its window for the first login
  claude-switch profiles      list accounts (--json for the menu bar)
  claude-switch label a NAME  rename an account in the menu bar / messages
  claude-switch doctor        print config, folders and agent state
  claude-switch restore       if the default account (A) was just opened but you last used another one,
                              switch to that one (the menu bar app runs this for you; disable with
                              "restore_last": false in the config)
  options: --yes (skip the busy-session prompt), --dry-run (print the plan only)
"""
import os
import plistlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json  # noqa: E402

import cs_config as C  # noqa: E402
import cs_sync  # noqa: E402

QUIT_TIMEOUT = 30
SYNC_LABEL = "io.github.claude-switcher.sync"
SYNC_PLIST = os.path.join(C.HOME, "Library/LaunchAgents", SYNC_LABEL + ".plist")
LAST = os.path.join(C.STATE_DIR, "last-account.json")
PENDING = os.path.join(C.STATE_DIR, "pending-setup")  # set by `add`; the menu bar app runs `setup --quiet` while it exists


def last_account():
    try:
        with open(LAST) as f:
            return json.load(f).get("account")
    except (OSError, ValueError):
        return None


def remember(key):
    os.makedirs(C.STATE_DIR, exist_ok=True)
    with open(LAST + ".tmp", "w") as f:
        json.dump({"account": key, "at": time.time()}, f)
    os.replace(LAST + ".tmp", LAST)


# ---------- processes ----------
def is_primary(conf, key):
    return conf["profiles"][key]["data_dir"] == C.PRIMARY_DATA


def running(conf):
    """{key: pid} for the main (non-helper) Claude process of each profile."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    by_dir = {p["data_dir"]: k for k, p in conf["profiles"].items()}
    found = {}
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if not cmd.startswith(C.APP_BIN):
            continue
        rest = cmd[len(C.APP_BIN):]
        if "--user-data-dir=" not in rest:
            d = C.PRIMARY_DATA
        else:
            d = rest.split("--user-data-dir=", 1)[1].strip()
        if d in by_dir:
            found[by_dir[d]] = int(pid)
    return found


def current(conf):
    p = running(conf)
    return "many" if len(p) > 1 else next(iter(p), "none")


def busy_sessions(app_pid):
    """Number of `claude` CLI processes under the app = sessions that are working right now."""
    rows = [l.split(None, 2) for l in subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout.splitlines()]
    kids = {}
    for pid, ppid, *cmd in rows:
        kids.setdefault(ppid, []).append((pid, cmd[0] if cmd else ""))
    n, stack = 0, [str(app_pid)]
    while stack:
        for pid, cmd in kids.get(stack.pop(), []):
            if "/claude-code/" in cmd and "/MacOS/claude" in cmd:
                n += 1
            else:
                stack.append(pid)
    return n


def confirm(n):
    msg = f"There are {n} session(s) still working. Switch anyway? The running work will stop."
    if sys.stdin.isatty():
        return input(msg + " [y/N] ").strip().lower() in ("y", "yes")
    r = subprocess.run(["osascript", "-e",
                        f'display dialog "{msg}" with title "Claude Switcher" buttons {{"Cancel", "Switch"}} '
                        'default button "Cancel" cancel button "Cancel" with icon caution'],
                       capture_output=True, text=True)
    return r.returncode == 0 and "Switch" in r.stdout


def quit_app(pid):
    os.kill(pid, 15)  # SIGTERM: the app runs its normal quit cleanup
    for _ in range(QUIT_TIMEOUT * 2):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
    return False


def launch(conf, who):
    if is_primary(conf, who):
        cmd = ["open", "-a", C.APP]
    else:
        cmd = ["open", "-n", C.APP, "--args", f"--user-data-dir={conf['profiles'][who]['data_dir']}"]
    subprocess.run(cmd, check=True)


def focus(pid):
    subprocess.run(["osascript", "-e", f'tell application "System Events" to set frontmost of (first process whose unix id is {pid}) to true'])


# ---------- commands ----------
def cmd_switch(conf, target, yes, dry):
    lab = {k: v["label"] for k, v in conf["profiles"].items()}
    cur = current(conf)
    if cur == "many":
        print("More than one account is running. Quit all but one first.")
        return 3
    keys = list(conf["profiles"])
    target = target or (keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0])
    if target == cur:
        print(f"Already on {lab[target]}.")
        if not dry:
            focus(running(conf)[cur])
        return 0
    if not os.path.isdir(conf["profiles"][target]["data_dir"]):
        print(f"Account {lab[target]} is not set up yet. Run: claude-switch add")
        return 6
    if cur != "none":
        n = busy_sessions(running(conf)[cur])
        if n and not yes:
            if dry:
                print(f"  [dry-run] {n} busy session(s) -> would ask for confirmation")
            elif not confirm(n):
                print("Cancelled.")
                return 5
    print(f"{lab.get(cur, 'nothing')} -> {lab[target]}")
    if dry:
        print("  [dry-run] quit, sync, launch")
        return 0
    if cur != "none" and not quit_app(running(conf)[cur]):
        print(f"The app did not quit within {QUIT_TIMEOUT}s. Not forcing it (it may be saving).")
        return 4
    cs_sync.sync(conf["sync_dirs"])
    remember(target)  # before launching, so the menu bar's restore check sees the new choice
    launch(conf, target)
    return 0


def cmd_restore(conf):
    """The Dock icon and login items always open the default data folder (account A). If A was just
    opened but another account was used last, switch to that one. Fresh app → nothing busy → no prompt."""
    if not conf.get("restore_last", True):
        return 0
    keys = list(conf["profiles"])
    primary = next((k for k in keys if is_primary(conf, k)), keys[0])
    last = last_account()
    if current(conf) != primary or not last or last == primary or last not in conf["profiles"]:
        return 0
    if not os.path.isdir(conf["profiles"][last]["data_dir"]):
        return 0
    print(f"restoring last account: {conf['profiles'][last]['label']}")
    return cmd_switch(conf, last, yes=True, dry=False)


def write_sync_agent(dirs):
    here = os.path.dirname(os.path.abspath(__file__))
    plist = {
        "Label": SYNC_LABEL,
        "ProgramArguments": ["/usr/bin/python3", os.path.join(here, "cs_sync.py")],
        "WatchPaths": dirs,
        "StartInterval": 20,
        "RunAtLoad": True,
        "ThrottleInterval": 3,
        "StandardErrorPath": os.path.join(C.STATE_DIR, "sync.err.log"),
    }
    os.makedirs(os.path.dirname(SYNC_PLIST), exist_ok=True)
    os.makedirs(C.STATE_DIR, exist_ok=True)
    uid = os.getuid()
    target = f"gui/{uid}/{SYNC_LABEL}"
    subprocess.run(["launchctl", "bootout", target], capture_output=True)
    for _ in range(20):  # launchd refuses a bootstrap while the old copy is still unloading
        if subprocess.run(["launchctl", "print", target], capture_output=True).returncode != 0:
            break
        time.sleep(0.25)
    with open(SYNC_PLIST, "wb") as f:
        plistlib.dump(plist, f)
    if subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", SYNC_PLIST], capture_output=True).returncode != 0:
        time.sleep(1)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", SYNC_PLIST], check=True)


def cmd_setup(conf, quiet=False):
    data_dirs = [p["data_dir"] for p in conf["profiles"].values()]
    dirs = C.detect_session_dirs(data_dirs)
    new = [d for d in dirs if d not in conf["sync_dirs"]]
    if quiet and not new:
        return 0  # menu bar polling after "Add account…": nothing new yet
    if not dirs:
        print("No session folders found in the Claude log yet. Open the Claude app once (Code tab), then run setup again.")
        return 7
    for d in dirs:
        if os.path.islink(d):  # the app will not write into a symlink; replace it with a real folder
            target = os.path.realpath(d)
            os.unlink(d)
            shutil.copytree(target, d) if os.path.isdir(target) else os.makedirs(d)
            print(f"replaced symlink with a real folder: {d}")
        os.makedirs(d, exist_ok=True)
    conf["sync_dirs"] = dirs
    C.save(conf)
    rc = cs_sync.sync(dirs)  # first run merges everything (no deletions)
    write_sync_agent(dirs)
    if new:
        print(f"added {len(new)} session folder(s)")
        if os.path.exists(PENDING):
            os.remove(PENDING)
    print(f"sync folders ({len(dirs)}):")
    for d in dirs:
        print("  " + d.replace(C.HOME, "~"))
    print("sync agent:", "installed" if rc == 0 else f"installed, but first sync returned {rc} (see sync.log)")
    return 0


def cmd_add(conf, label):
    # first account without a data folder yet (B exists in the defaults), otherwise the next letter
    key = next((k for k, p in conf["profiles"].items() if not is_primary(conf, k) and not os.path.isdir(p["data_dir"])), None)
    if key is None:
        key = chr(ord(max(conf["profiles"])) + 1)
        conf["profiles"][key] = {"label": key.upper(), "data_dir": os.path.join(C.APP_SUPPORT, f"Claude {key.upper()}")}
    if label:
        conf["profiles"][key]["label"] = label
    C.save(conf)
    d = conf["profiles"][key]["data_dir"]
    os.makedirs(d, exist_ok=True)
    os.makedirs(C.STATE_DIR, exist_ok=True)
    open(PENDING, "w").close()
    subprocess.run(["open", "-n", C.APP, "--args", f"--user-data-dir={d}"], check=True)
    print(f"A new Claude window opened for account {conf['profiles'][key]['label']} ({key}). Log in there once.\n"
          "Note: Google sign-in returns to the first Claude window and is ignored. Either use\n"
          "email sign-in, or quit the other Claude window while you sign in.\n"
          "After logging in, open the Code tab once. The menu bar app then adds the account by itself\n"
          "(without the menu bar app, run: claude-switch setup).")
    return 0


def cmd_doctor(conf):
    print("config:", C.CONF.replace(C.HOME, "~"))
    for k, p in conf["profiles"].items():
        print(f"  {k}: {p['label']}  data={p['data_dir'].replace(C.HOME, '~')}  exists={os.path.isdir(p['data_dir'])}")
    print("running:", current(conf), "| last used:", last_account(), "| restore_last:", conf.get("restore_last", True))
    for d in conf["sync_dirs"]:
        ok = os.path.isdir(d) and not os.path.islink(d)
        n = len([x for x in os.listdir(d) if x.startswith("local_")]) if ok else 0
        print(f"  {'ok ' if ok else 'BAD'} {n:4d} sessions  {d.replace(C.HOME, '~')}")
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SYNC_LABEL}"], capture_output=True, text=True)
    print("sync agent:", "loaded" if r.returncode == 0 else "not loaded (run: claude-switch setup)")
    return 0


def main(argv):
    conf = C.load()
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    cmd = args[0] if args else ""
    if cmd == "status":
        cur = current(conf)
        print(cur if "--short" in flags else {"none": "not running", "many": "several running"}.get(cur, conf["profiles"].get(cur, {}).get("label", cur)))
        return 0
    if cmd == "setup":
        return cmd_setup(conf, "--quiet" in flags)
    if cmd == "add":
        return cmd_add(conf, " ".join(args[1:]))
    if cmd == "profiles":
        if "--json" in flags:
            import json
            print(json.dumps([{"key": k, "label": p["label"]} for k, p in conf["profiles"].items() if os.path.isdir(p["data_dir"])]))
        else:
            for k, p in conf["profiles"].items():
                print(f"{k}  {p['label']:<12} {'ready' if os.path.isdir(p['data_dir']) else 'not set up'}")
        return 0
    if cmd == "doctor":
        return cmd_doctor(conf)
    if cmd == "restore":
        return cmd_restore(conf)
    if cmd == "label" and len(args) >= 3 and args[1] in conf["profiles"]:
        conf["profiles"][args[1]]["label"] = " ".join(args[2:])
        C.save(conf)
        return 0
    if cmd == "" or cmd in conf["profiles"]:
        return cmd_switch(conf, cmd or None, "--yes" in flags, "--dry-run" in flags)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
