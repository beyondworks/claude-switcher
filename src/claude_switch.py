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
  claude-switch share         merge the desktop settings of every account now (Claude must be closed;
                              every switch does this by itself)
  claude-switch restore       if the default account (A) was just opened but you last used another one,
                              switch to that one (the menu bar app runs this for you; disable with
                              "restore_last": false in the config)
  options: --yes (skip the busy-session prompt), --dry-run (print the plan only)
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time

# realpath: ~/.local/bin/claude-switch is a symlink; everything we point launchd at must be the real file.
HERE = os.path.dirname(os.path.realpath(__file__))
SYNC_SCRIPT = os.path.join(HERE, "cs_sync.py")
sys.path.insert(0, HERE)
import json  # noqa: E402

import cs_config as C  # noqa: E402
import cs_share  # noqa: E402
import cs_sync  # noqa: E402

QUIT_TIMEOUT = 30
NO_WINDOW = 0x08000000 if C.WINDOWS else 0  # CREATE_NO_WINDOW: no console flash when the tray runs us
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


def win_processes():
    """[(pid, ppid, name, command line)] of every process (Windows)."""
    ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine"
          " | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    rows = json.loads(out or "[]")
    return [(r["ProcessId"], r["ParentProcessId"], r["Name"] or "", r["CommandLine"] or "") for r in rows]


def win_is_app(name, cmd):
    """The desktop app's main process: claude.exe from the AnthropicClaude install, not a helper (--type=).
    Claude Code's own CLI is also called claude.exe, but it lives elsewhere."""
    return name.lower() == "claude.exe" and "\\anthropicclaude\\" in cmd.lower() and "--type=" not in cmd


def win_data_dir(cmd):
    m = re.search(r'--user-data-dir=(.*?)(?:"|\s--|$)', cmd)
    return m.group(1).strip() if m else C.PRIMARY_DATA


def running(conf):
    """{key: pid} for the main (non-helper) Claude process of each profile."""
    if C.WINDOWS:
        by_dir = {C._norm(p["data_dir"]): k for k, p in conf["profiles"].items()}
        return {by_dir[C._norm(win_data_dir(cmd))]: pid for pid, _, name, cmd in win_processes()
                if win_is_app(name, cmd) and C._norm(win_data_dir(cmd)) in by_dir}
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
    if C.WINDOWS:
        kids = {}
        for pid, ppid, name, cmd in win_processes():
            kids.setdefault(ppid, []).append((pid, name, cmd))
        n, stack = 0, [app_pid]
        while stack:
            for pid, name, cmd in kids.get(stack.pop(), []):
                if name.lower() == "claude.exe" and not win_is_app(name, cmd) and "--type=" not in cmd:
                    n += 1
                else:
                    stack.append(pid)
        return n
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
    if sys.stdin and sys.stdin.isatty():
        return input(msg + " [y/N] ").strip().lower() in ("y", "yes")
    if C.WINDOWS:
        import ctypes
        # MB_OKCANCEL | MB_ICONWARNING | MB_DEFBUTTON2 | MB_TOPMOST; IDOK = 1
        return ctypes.windll.user32.MessageBoxW(None, msg, "Claude Switcher", 0x1 | 0x30 | 0x100 | 0x40000) == 1
    r = subprocess.run(["osascript", "-e",
                        f'display dialog "{msg}" with title "Claude Switcher" buttons {{"Cancel", "Switch"}} '
                        'default button "Cancel" cancel button "Cancel" with icon caution'],
                       capture_output=True, text=True)
    return r.returncode == 0 and "Switch" in r.stdout


def win_wait_ready(pid, data_dir, timeout=30):
    """A quit message that arrives while the app is still starting ends it without its own quit
    cleanup (seen in CI: the log stops mid-startup, no "quitting the app" line). Wait until this run of
    the app has logged "boot: done", or at most `timeout` seconds."""
    # ponytail: keyed on one log line; if a future app stops writing it, this degrades to a 30 s wait
    ps = f"(Get-Process -Id {pid}).StartTime.ToString('yyyy-MM-dd HH:mm:ss')"
    started = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout.strip()
    logs = [f for f in C.log_files([data_dir]) if os.path.exists(f)]
    for n in range(timeout):
        for f in logs:
            with open(f, errors="replace") as fh:
                if any("boot: done" in l and l[:19] >= started for l in fh):
                    return True
        time.sleep(1)
    print(f"  (the app did not report a finished start within {timeout}s; asking it to quit anyway)")
    return False


def win_quit(pid):
    """Closing the window or `taskkill` only hides the app to the tray. What makes it quit normally is the
    log-off message pair Windows itself sends: WM_QUERYENDSESSION, then WM_ENDSESSION(TRUE)
    (verified: the log says "Windows session ending (shutdown) - quitting the app")."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    hwnds = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(h, _):
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(owner))
        if owner.value == pid:
            hwnds.append(h)
        return True
    u.EnumWindows(proc(each), 0)
    r = ctypes.c_size_t()
    for h in hwnds:
        u.SendMessageTimeoutW(h, 0x11, 0, 0, 2, 3000, ctypes.byref(r))  # SMTO_ABORTIFHUNG, 3 s
        u.SendMessageTimeoutW(h, 0x16, 1, 0, 2, 3000, ctypes.byref(r))


def alive(pid):
    if C.WINDOWS:
        return any(p == pid for p, *_ in win_processes())
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def quit_app(pid, data_dir):
    if C.WINDOWS:
        win_wait_ready(pid, data_dir)
        win_quit(pid)
    else:
        os.kill(pid, 15)  # SIGTERM: the app runs its normal quit cleanup
    for _ in range(QUIT_TIMEOUT):
        time.sleep(1)
        if not alive(pid):
            return True
    return False


def open_window(data_dir=None):
    """Start the app (or bring up the running one) with that data folder; None = the default folder."""
    if C.WINDOWS:
        # the stub launcher forwards the argument to the current app-<version>\claude.exe
        subprocess.Popen([C.APP] + ([f"--user-data-dir={data_dir}"] if data_dir else []),
                         creationflags=0x00000008 | NO_WINDOW)  # DETACHED_PROCESS
    elif data_dir:
        subprocess.run(["open", "-n", C.APP, "--args", f"--user-data-dir={data_dir}"], check=True)
    else:
        subprocess.run(["open", "-a", C.APP], check=True)


def launch(conf, who):
    if C.WINDOWS:
        return open_window(None if is_primary(conf, who) else conf["profiles"][who]["data_dir"])
    if is_primary(conf, who):
        cmd = ["open", "-a", C.APP]
    else:
        cmd = ["open", "-n", C.APP, "--args", f"--user-data-dir={conf['profiles'][who]['data_dir']}"]
    subprocess.run(cmd, check=True)


def focus(conf, key):
    if C.WINDOWS:  # a second start with the same folder makes the running app show its window
        return launch(conf, key)
    pid = running(conf)[key]
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
            focus(conf, cur)
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
        print("  [dry-run] quit, sync sessions and shared settings, launch")
        return 0
    if cur != "none" and not quit_app(running(conf)[cur], conf["profiles"][cur]["data_dir"]):
        print(f"The app did not quit within {QUIT_TIMEOUT}s. Not forcing it (it may be saving).")
        return 4
    cs_sync.sync(conf["sync_dirs"])
    share_settings(conf)
    remember(target)  # before launching, so the menu bar's restore check sees the new choice
    launch(conf, target)
    return 0


def share_settings(conf):
    """Desktop MCP servers, preferences, worktree records, tool toggles: the same in every account.
    Only while no Claude window is open; the app rewrites these files from memory while it runs."""
    if running(conf):
        return None
    changed = cs_share.share([p["data_dir"] for p in conf["profiles"].values()])
    if changed:
        print("shared settings merged: " + ", ".join(changed))
    return changed


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
    if C.WINDOWS:
        return  # no launchd: the tray app runs cs_sync every 20 s
    plist = {
        "Label": SYNC_LABEL,
        "ProgramArguments": ["/usr/bin/python3", SYNC_SCRIPT],
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
    open_window(d)
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
    log = os.path.join(C.STATE_DIR, "sync.log")
    last = [l for l in open(log)][-1:] if os.path.exists(log) else []
    if C.WINDOWS:
        print("sync: run by the tray app every 20 s" + (f" (last change: {last[0].strip()})" if last else ""))
        return 0
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SYNC_LABEL}"], capture_output=True, text=True)
    if r.returncode != 0:
        print("sync agent: not loaded (run: claude-switch setup)")
        return 1
    try:
        with open(SYNC_PLIST, "rb") as f:
            script = plistlib.load(f)["ProgramArguments"][1]
    except (OSError, KeyError, IndexError, plistlib.InvalidFileException):
        script = ""
    if not os.path.isfile(script):
        print(f"sync agent: BROKEN — it runs a missing file ({script or 'unknown'}). Run: claude-switch setup")
        return 1
    print("sync agent: running" + (f" (last change: {last[0].strip()})" if last else ""))
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
            print(json.dumps([{"key": k, "label": p["label"], "data_dir": p["data_dir"], "primary": is_primary(conf, k)}
                              for k, p in conf["profiles"].items() if os.path.isdir(p["data_dir"])]))
        else:
            for k, p in conf["profiles"].items():
                print(f"{k}  {p['label']:<12} {'ready' if os.path.isdir(p['data_dir']) else 'not set up'}")
        return 0
    if cmd == "doctor":
        return cmd_doctor(conf)
    if cmd == "_sync-script":  # used by tests
        print(SYNC_SCRIPT)
        return 0
    if cmd == "share":
        if share_settings(conf) is None:
            print("Quit Claude first: settings are merged only while no Claude window is open (every switch does it).")
            return 3
        return 0
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
