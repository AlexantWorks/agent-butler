<p align="center">
  <img src="assets/logo-v3-1024.png" width="140" alt="Butler">
</p>

<h1 align="center">Butler</h1>

<p align="center">
  <a href="README.md">English</a> · 简体中文 · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a>
</p>

<p align="center"><b>一个为多线程 vibecoding 而生的项目管理工具。</b><br>
给同时跑 Claude Code 和 Codex 的 ADHD 大脑：你的老管家，帮你盯住每个 agent、每条线程、每个下一步。</p>

<p align="center">
  <code>Claude Code</code> · <code>Codex</code> · <code>ADHD-friendly</code> · <code>menu-bar</code> · <code>multi-project</code> · <code>macOS</code>
</p>

https://github.com/user-attachments/assets/dcd7e423-e870-434b-8a9f-a94320bc962a

---

## 问题

当你并行跑多个 AI coding agent（Claude Code、Codex……）时，最容易丢的不是代码，而是上下文：

- 你会**忘记哪个会话正在等你**；
- 你会**忘记每个项目推进到哪里**；
- 你会**分不清哪个最重要**；
- 第二天醒来时，你会**不知道该从哪个项目开始**。

普通提醒不够。它只会响一下，但不会帮你保留进度、状态和优先级。

vibecoding 很像送外卖：等单时像是在玩手机，单一到就要马上送。整块的心流时间被切成很碎的片段，对 ADHD 大脑尤其难。

Butler 来自一个很简单的 Fable 原型：给 agent 做一个老管家。它帮你记住每个项目的初心目标、当前进展、最近三次沟通和优先级。重点不是把 agent credit 用到极致，而是提醒你克制：最贵的不是 credit，是买不回来的时间。

**Butler 是你的并行 agent 老管家。** 它不替你工作，它负责让你别把球掉地上。

## 它做什么

| 界面 | 你得到什么 |
|---|---|
| **▦ 菜单栏徽标** | `▦ 2` = 2 个会话等你；`▦ ·` = 有项目在跑；`▦` = 全部安静。扫一眼顶部就知道全局。 |
| **浮窗**（点 ▦） | 等你卡片有 amber 呼吸光晕，新出现的卡片会轻微脉冲。可以直接改名、写项目初心目标、设优先级、归档、复制名字。 |
| **桌面 mini 卡** | 232px 小卡贴在桌面上：在壁纸之上、窗口之下，不挡事；把最优先的任务留在视野里。可以置顶，也可以拖到任意位置。 |
| **系统通知** | agent 从 running 变成 waiting 时，Butler 用最后一句输出提醒你下一步该做什么。原生 macOS 通知，正确图标，不轰炸，还有每日等待摘要。 |
| **完整看板** | 列间拖拽、Claude/Codex tabs、P0/P1/P2 优先级、项目初心目标、最近 3 条沟通回顾，帮你立刻想起这个项目在干什么。 |
| **Butler Light companion** | 可选灯带 companion。Butler 写一个很小的本地状态 JSON，Butler Light 把 Waiting > Running > Shelved 映射成灯带颜色。 |

### 模型：agent 版 inbox zero

- **Running / Waiting = 事实**：这是 agent 当前状态。停了一个小时？仍然是在等你，你可以吃饭睡觉。
- **Shelved = 你的决定**：只有你手动归档，它才离开 inbox。
- **Scheduled / cron 会话**：运行时显示，结束后退场，不伪装成待办。
- **P0/P1/P2**：让等你列表自动排序，早上点开第一张就是最该处理的事。

## 安装

> Butler 目前没有 notarize。macOS 可能提示 “unidentified developer”。这是预期行为：第一次用 **右键 → Open** 打开，之后就能正常启动。

需要 macOS 13+、Xcode Command Line Tools（`xcode-select --install`）和 Node（用于 Claude session hooks）。

```bash
git clone https://github.com/YOUR_USER/agent-butler.git ~/dev/agent-butler
bash ~/dev/agent-butler/native/build.sh          # 编译 → /Applications/Butler.app → 启动
```

`build.sh` 会编译 Swift app、打包、安装 Claude session hooks。第一次通知会弹权限提示，请允许。菜单里可以打开 **Login at startup**。

**唯一外部部件**：Claude session hooks（自动安装）和系统自带 `python3`（运行 stdlib-only 数据引擎）。不需要 pip、venv 或 Homebrew。

## 录屏：演示模式

截图、录 demo、做发布视频时，右键菜单栏 `▦` 图标，打开 **演示模式**。

演示模式会展示一组固定的假 Claude/Codex 项目，不读取你的真实会话、transcripts、路径、项目名或备注。你仍然可以改名、编辑目的、修改优先级、把卡片拖到不同列；这些改动只会保存到 `~/.claude-monitor/demo-extras.json`。菜单栏数字、浮窗、mini 看板、完整看板和 Butler Light 状态桥都会使用同一组假数据，直到你关闭演示模式。

## 可选：Butler Light

Butler Light 是独立的 macOS companion app，用来控制 ELK-BLEDOM 兼容灯带。它刻意和 Butler 分开：Butler 保持小而专注，蓝牙权限、设备绑定、颜色控制都放在 companion 里。

```bash
cd ~/dev/agent-butler/butler-light
./scripts/package_app.sh
open "dist/Butler Light.app"
```

打开 Butler Light，允许 Bluetooth，绑定灯带，然后选择 **Butler Status** 模式。它读取：

```text
~/.claude-monitor/butler-light-status.json
```

优先级永远是 **Waiting > Running > Shelved**。你可以在 companion 里修改三种状态对应的颜色，也可以切到 **Fixed Color** 手动控制。

## 架构

```text
/Applications/Butler.app   原生 Swift，自包含
├─ Butler                  菜单栏 / 浮窗 / mini / 原生通知
│                          / 登录项 / 管理 server subprocess
└─ Resources/
   ├─ server.py            stdlib-only 数据引擎：
   │                         Claude session hooks + transcript heartbeat
   │                         Codex ~/.codex/sessions 解析
   │                         优先级 / 目的 / 归档存储 · 浮窗 / mini / 看板 HTML
   └─ AppIcon.icns

butler-light/              可选 Swift companion：
├─ BLE 扫描 / 绑定 / ELK-BLEDOM RGB 写入
├─ 固定颜色模式
└─ 通过 ~/.claude-monitor/butler-light-status.json 跟随 Butler 状态
```

## 隐私

Butler 完全在你的机器上运行，只读取你自己的本地 agent 数据（`~/.claude`、`~/.codex`、session transcripts）。Butler Light 只使用本地 Bluetooth 和本地状态 JSON 文件。没有服务器、没有 telemetry、没有账号。

## 本地化

README 提供 **English / 简体中文 / 日本語 / 한국어 / Español**。

Butler app UI 默认英文，并内置中文、日文、韩文、西班牙语。App 名称也会本地化：Butler · 老管家 · バトラー · 집사。

## License

AGPL-3.0-only — see [LICENSE](LICENSE)。基于 Butler 的产品必须以同一许可证开放对应源代码。
