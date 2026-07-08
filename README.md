<p align="center">
  <img src="assets/logo-v3-1024.png" width="140" alt="Butler">
</p>

<h1 align="center">Butler</h1>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a>
</p>

<p align="center"><b>A project manager built for multi-threaded vibecoding.</b><br>
For ADHDers running Claude Code and Codex in parallel — your old-school butler for every agent, thread, and next step.</p>

<p align="center">
  <code>Claude Code</code> · <code>Codex</code> · <code>ADHD-friendly</code> · <code>menu-bar</code> · <code>multi-project</code> · <code>macOS</code>
</p>

<p align="center">
  <a href="assets/demo.mp4?raw=1"><img src="assets/demo-poster.png" width="720" alt="Watch Butler demo video"></a><br>
  <sub>Click the preview to watch the demo video.</sub>
</p>

---

## The problem

When you're running several AI coding agents in parallel (Claude Code, Codex…), the thread slips:

- you **forget which session is waiting on you**,
- you **forget where each one got to**,
- you **can't tell which one matters most**,
- and you wake up **not knowing which project to start**.

A plain reminder isn't enough — it pings you, but you still lose the progress and can't judge priority.

Agent work can feel like delivery work: long quiet gaps while you wait for the next order, then a sudden handoff that needs action now. That slices deep work into tiny fragments, which is especially rough for ADHD brains.

Butler keeps the missing context close: the original purpose of each project, the latest progress, the last three exchanges, and the priority order. The point is not to squeeze more agent credits out of the day. It is to protect the one thing credits cannot buy back: your time.

**Butler is the secretary for your parallel agent work.** It doesn't do your work; it keeps you from dropping the ball.

## What it does

| Surface | What it gives you |
|---|---|
| **▦ Menu-bar badge** | `▦ 2` = 2 sessions waiting on you · `▦ ·` = running · `▦` = all quiet. One glance, whole picture. |
| **Popover** (click ▦) | Waiting cards get an amber breathing glow + a pulse on new ones. Rename, set the project's original purpose, set priority, archive, copy name — right there. Click outside to dismiss. |
| **Desktop mini card** | A 232px card pinned to the desktop (above the wallpaper, below your windows — never in the way) so the highest-priority work stays visible. Pin it on top; drag it anywhere. |
| **System notifications** | The moment an agent goes from *running* → *waiting on you*, Butler nudges you with the agent's last line (your ready-made next step). Native macOS notifications — correct icon, no spam, a daily digest for what's been waiting > 24h. |
| **Full board** | Drag between columns · Claude/Codex tabs · P0/P1/P2 priorities · project purpose · recent-3 recap so you remember what this project was doing. |
| **Butler Light companion** | Optional ELK-BLEDOM LED strip app. Butler writes one tiny local status file; the companion maps Waiting > Running > Shelved to colors. |

### The model: inbox zero for agents

- **Running / Waiting = facts** (the agent's state). Stopped for an hour? Still waiting on you — you're allowed to eat and sleep.
- **Shelved = your decision.** It only leaves your inbox when *you* archive it.
- **Scheduled (cron) sessions** show while running, disappear when done — they don't fake being a to-do.
- **P0/P1/P2** sort your "waiting" list so the first card each morning is the one to start.

## Install

> Butler is not notarized (it's a small open-source tool). macOS will say *"unidentified developer."* That's expected — open it once with **right-click → Open**, then it launches normally forever.

Requires macOS 13+, Xcode Command Line Tools (`xcode-select --install`), and Node (for the Claude session hooks).

```bash
git clone https://github.com/YOUR_USER/agent-butler.git ~/dev/agent-butler
bash ~/dev/agent-butler/native/build.sh          # compiles → /Applications/Butler.app → launches
```

`build.sh` compiles the Swift app, self-packages it, and installs the Claude session hooks. First notification pops a permission prompt — allow it. Turn on **Login at startup** from the menu.

**The only external pieces:** the Claude session hooks (installed automatically) and your system `python3` (runs the stdlib data engine). No pip, no venv, no Homebrew.

## Recording: Demo Mode

For screenshots, demos, and launch videos, right-click the menu-bar `▦` icon and turn on **Demo Mode**.

Demo Mode shows a fixed set of fake Claude/Codex projects and does not read your real sessions, transcripts, paths, project names, or notes. You can still rename cards, edit purpose notes, change priorities, and drag cards between columns; those edits are saved only to `~/.claude-monitor/demo-extras.json`. The menu badge, popover, mini board, full board, and Butler Light status bridge all use the same fake data until you turn Demo Mode off.

## Optional: Butler Light

Butler Light is a separate native macOS companion app for ELK-BLEDOM-compatible LED strips. It is intentionally separate from Butler: Butler stays small and focused, while the Bluetooth permission, device binding, and color controls live in the companion.

```bash
cd ~/dev/agent-butler/butler-light
./scripts/package_app.sh
open "dist/Butler Light.app"
```

Open Butler Light, allow Bluetooth, bind your strip, then choose **Butler Status** mode. It reads:

```text
~/.claude-monitor/butler-light-status.json
```

The priority is always **Waiting > Running > Shelved**. You can change each color in the companion, or switch to **Fixed Color** for manual control.

## Architecture

```
/Applications/Butler.app   (native Swift, self-contained ~270KB)
├─ Butler                  menu bar / popover (WKWebView) / mini / native notifications
│                          / login item (SMAppService) / manages the server subprocess
└─ Resources/
   ├─ server.py            stdlib-only data engine (system python3):
   │                         Claude — session hooks + transcript heartbeat / cold-start fallback
   │                         Codex  — ~/.codex/sessions parsing
   │                         priority / purpose / archive storage · popover / mini / board HTML
   └─ AppIcon.icns

butler-light/              optional native Swift companion:
├─ BLE scan / bind / ELK-BLEDOM RGB write
├─ fixed color mode
└─ Butler status mode via ~/.claude-monitor/butler-light-status.json
```

## Privacy

Butler runs entirely on your machine and reads **your own** local agent data (`~/.claude`, `~/.codex`, session transcripts). Butler Light only uses local Bluetooth and the local status JSON file. Nothing is sent anywhere — there is no server, no telemetry, no account.

## Localization

README is available in **English / 简体中文 / 日本語 / 한국어 / Español**.

The Butler app UI ships in **English** (default, follows your system language) with **中文 / 日本語 / 한국어 / Español** included. The app name localizes too: Butler · 老管家 · バトラー · 집사.

## License

MIT — see [LICENSE](LICENSE).
