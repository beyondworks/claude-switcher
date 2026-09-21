# Claude Switcher

**Switch the Claude desktop app between your accounts with one key — and keep the same Code sessions on every account.**

<p>
  <img src="docs/menubar-a.png" width="480" alt="Menu bar showing account A (orange)"><br>
  <img src="docs/menubar-b.png" width="480" alt="Menu bar showing account B (teal)">
</p>

`⌘ Page Down` → the running account quits, the next one opens already logged in, and the sidebar shows the same sessions as before.
No logging out, no logging in, no second copy of your work.

[한국어 README](README.ko.md)

> Unofficial community tool. Not affiliated with or endorsed by Anthropic. macOS only for now.

---

## The idea in three facts

Claude Switcher does not hack the app. It only arranges three things the app already does:

1. **Every data folder keeps its own login.** The desktop app can be started with a different data folder
   (`--user-data-dir`). Each folder remembers the account that logged in there. So one folder per account =
   every account stays logged in.
2. **Conversations are already shared.** Code-tab transcripts live in `~/.claude/projects`, one place for every
   account. What is *not* shared is the sidebar list, which the app keeps per account:
   `<data folder>/claude-code-sessions/<account>/<org>/`.
3. **So we keep those lists identical.** A small background job copies session-list changes between the
   account folders within seconds. Only one account runs at a time, so they never write at once.

<p align="center"><img src="docs/how-it-works.svg" width="720" alt="How it works"></p>

Switching is then just: *quit the running account → sync once → open the next account's data folder.*

## What you get

| | |
|---|---|
| **⌘ Page Down** | Switch to the next account (A → B → C … → A) from anywhere. |
| **Menu bar** | The Claude symbol, in each account's own colour, shows which account is running. The menu lists every account. |
| **`claude-switch`** | The same thing from a terminal or from inside a Claude session. |
| **Busy check** | If a session is still working, you get *"There are N session(s) still working. Switch anyway?"* first. |
| **Any number of accounts** | `claude-switch add` adds C, D, … Each gets its own colour. |
| **Opens the account you used last** | The Dock icon, a login item or a reboot always open the default account (A). If you last used another one, Claude Switcher reopens that one right away. Turn off with `"restore_last": false` in `~/.config/claude-switcher/config.json`. |

<p align="center"><img src="docs/menu.png" width="360" alt="Menu bar menu"></p>

The menu bar symbol is taken at runtime from **your own installed** `/Applications/Claude.app` icon and tinted;
this repository ships no Anthropic artwork. If it cannot be read, a drawn star is used instead.

## Install

Requirements: macOS, the Claude desktop app in `/Applications`, Xcode Command Line Tools (`xcode-select --install`).

```bash
git clone https://github.com/beyondworks/claude-switcher.git
cd claude-switcher
./install.sh
```

The installer puts `claude-switch` in `~/.local/bin`, builds the menu bar app into `~/Applications`,
starts it at login, and detects your current account's session folder.

### Add your second account (once)

```bash
claude-switch add Personal     # opens a second Claude window with its own data folder
```

Log in there once, open the **Code** tab once, then:

```bash
claude-switch setup            # finds the new account's session folder and starts syncing
```

> **Google sign-in gotcha.** While another Claude window is open, the browser hands the Google sign-in back to
> *that* window, which ignores it. Use **email sign-in** in the new window, or quit the other Claude window
> while you sign in. This is needed only the first time — the login is saved in that account's folder.

Name your accounts (shown in the menu):

```bash
claude-switch label a Work
claude-switch label b Personal
```

## Use

```bash
claude-switch            # next account
claude-switch b          # a specific account
claude-switch status     # which one is running
claude-switch profiles   # list accounts
claude-switch doctor     # check folders and the sync job
```

## What is shared and what is not

| Shared across accounts | Not shared |
|---|---|
| Code-tab session list (titles, archive state, deletions) | claude.ai web chats (stored per account on Anthropic's servers) |
| Conversation transcripts (`~/.claude/projects`) | Cowork / local-agent sessions |
| Routines stored with the session list | Usage limits and billing — each account has its own |
| | **Prompt cache** — caches are isolated per organization, so the first message after switching re-reads the conversation without a cache and uses more of that account's quota |

## Safety

- **Nothing is deleted outright.** A session removed on one account is moved to
  `~/Library/Application Support/claude-switcher/trash/<date>/` on the others.
- **Mass-delete guard.** If one sync would remove more than 20% of all files (and more than 5), it stops and logs instead.
- **Real folders only.** The app refuses to save into a session folder that is a symlink (it opens it with `O_NOFOLLOW`),
  so Claude Switcher never links folders; it copies.
- **One account at a time.** Switching refuses to run if more than one account is open, and never force-quits the app
  (it waits up to 30 s for a normal quit).
- A change made in the last few seconds before a switch may not have synced yet; the switch runs one extra sync to catch it.

## Uninstall

```bash
./uninstall.sh
```

Removes the programs and background jobs. Your Claude data folders, logins and sessions are left as they are.

## Limitations

- macOS only. Windows is untested.
- Relies on the desktop app's current folder layout and log format. An app update could change them; `claude-switch doctor`
  will show it.
- Using several accounts is subject to Anthropic's terms. Check the [usage policy](https://www.anthropic.com/legal/aup)
  and [consumer terms](https://www.anthropic.com/legal/consumer-terms) for your plan.

## Development

```bash
python3 -m unittest discover tests      # sync engine and folder detection
swiftc -O menubar/main.swift -o /tmp/ClaudeSwitcher
```

Releases are made by pushing a tag: `git tag v0.1.0 && git push origin v0.1.0`.

## License

MIT
