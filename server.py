#!/usr/bin/env python3
"""
Butler · 在飞看板 (Claude in-flight board) — v0 thin frontend.

Data engine = onikan27/claude-code-monitor hooks, already registered globally in
~/.claude/settings.json. Those hooks write ~/.claude-monitor/sessions.json on every
Claude activity (verified: writes directly, no `ccm serve` needed).

This server ONLY reads that file, enriches each session from its transcript, and
serves a desktop-first responsive board. No external deps — Python 3 stdlib only.

Run:  python3 server.py            # then open http://localhost:7788
Phone (same Wi-Fi): open http://<this-mac-LAN-IP>:7788
"""
import json
import os
import re
import time
import glob
import calendar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_TRANSCRIPT = 20_000_000   # skip transcript enrichment above this (OOM guard on untrusted jsonl)
MAX_LINE = 500_000            # skip a single oversized jsonl line
MAX_POST = 262_144            # 256KB cap on POST bodies (LAN DoS guard)
SID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")   # sessions come from a 3rd-party file; sanitize the id

HOME = os.path.expanduser("~")
STORE = os.path.join(HOME, ".claude-monitor", "sessions.json")
LIGHT_STATUS = os.path.join(HOME, ".claude-monitor", "butler-light-status.json")
DEMO_MODE = os.path.join(HOME, ".claude-monitor", "demo-mode")
DEMO_EXTRAS = os.path.join(HOME, ".claude-monitor", "demo-extras.json")
PROJECTS_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects.json")
CLAUDE_PROJECTS = os.path.join(HOME, ".claude", "projects")

PORT = int(os.environ.get("BOARD_PORT", "7788"))
BUTLER_LOCALE = os.environ.get("BUTLER_LOCALE", "auto").lower()
_SRC_MTIME = int(os.path.getmtime(os.path.abspath(__file__)))   # /api/health 用:检测旧进程跑旧代码

# ── tuning knobs ──────────────────────────────────────────────────────────────
STALE_HOURS = 48        # sessions untouched longer than this are dropped from the board (48h 才能覆盖 F6 ">24h 搁置摘要")
FRESH_MIN = 30          # a `stopped` session touched within this many minutes = "等你", else "搁置"
# ──────────────────────────────────────────────────────────────────────────────

_projects = None
_transcript_cache = {}  # session_id -> (transcript_mtime, {task, gitBranch})
_fallback_cache = {"ts": 0.0, "sig": None, "cards": []}
_light_status_sig = None

# The desktop app stores a human-readable title per conversation (the name you see in the
# sidebar) under claude-code-sessions/*/*/local_*.json, keyed by cliSessionId (= our card id).
APP_SESSIONS = os.path.join(HOME, "Library", "Application Support", "Claude", "claude-code-sessions")
_titles = {"map": {}, "ts": 0.0}


def load_titles():
    """{cliSessionId -> {title, archived}} from the desktop app's session files. Cached 15s."""
    now = time.time()
    if _titles["map"] and now - _titles["ts"] < 15:
        return _titles["map"]
    m = {}
    try:
        for p in glob.glob(os.path.join(APP_SESSIONS, "*", "*", "local_*.json")):
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                d = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            cid, title = d.get("cliSessionId"), d.get("title")
            if cid and title:
                m[cid] = {"title": title, "archived": bool(d.get("isArchived")),
                          "scheduled": bool(d.get("scheduledTaskId"))}
    except Exception:
        pass
    _titles["map"] = m
    _titles["ts"] = now
    return m

# our own side-store (separate from ccm's sessions.json): manual overrides + notes
EXTRAS = os.path.join(HOME, ".claude-monitor", "board-extras.json")
UI_CMD = os.path.join(HOME, ".claude-monitor", "ui-cmd.json")   # v3: webview→app 命令通道
_extras_lock = __import__("threading").Lock()


def load_extras():
    try:
        return json.load(open(EXTRAS))
    except Exception:
        return {}


def save_extras(d):
    with _extras_lock:
        os.makedirs(os.path.dirname(EXTRAS), exist_ok=True)
        tmp = EXTRAS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, EXTRAS)


def _write_extras(d):
    os.makedirs(os.path.dirname(EXTRAS), exist_ok=True)
    tmp = EXTRAS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, EXTRAS)


def set_extra(session_id, **fields):
    with _extras_lock:
        try:
            d = json.load(open(EXTRAS))
        except Exception:
            d = {}
        cur = d.get(session_id, {})
        cur.update(fields)
        d[session_id] = cur
        _write_extras(d)


def clear_override(session_id):
    # whole read-modify-write under the lock (no TOCTOU against set_extra)
    with _extras_lock:
        try:
            d = json.load(open(EXTRAS))
        except Exception:
            return
        if session_id in d and "override" in d[session_id]:
            d[session_id].pop("override", None)
            _write_extras(d)


def load_demo_extras():
    try:
        return json.load(open(DEMO_EXTRAS))
    except Exception:
        return {}


def _write_demo_extras(d):
    os.makedirs(os.path.dirname(DEMO_EXTRAS), exist_ok=True)
    tmp = DEMO_EXTRAS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DEMO_EXTRAS)


def set_demo_extra(session_id, **fields):
    with _extras_lock:
        d = load_demo_extras()
        cur = d.get(session_id, {})
        cur.update(fields)
        d[session_id] = cur
        _write_demo_extras(d)


def clear_demo_override(session_id):
    with _extras_lock:
        d = load_demo_extras()
        if session_id in d and "override" in d[session_id]:
            d[session_id].pop("override", None)
            _write_demo_extras(d)


def load_projects():
    global _projects
    if _projects is None:
        try:
            _projects = json.load(open(PROJECTS_CFG))
        except Exception:
            _projects = {"buckets": [], "fallback": "其他"}
    return _projects


def find_transcript(session_id, cwd):
    """Transcript lives at ~/.claude/projects/<cwd-slug>/<session_id>.jsonl."""
    if cwd:
        slug = cwd.replace("/", "-")
        p = os.path.join(CLAUDE_PROJECTS, slug, session_id + ".jsonl")
        if os.path.exists(p):
            return p
    # fallback: search every project dir for this session id
    hits = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def _text_of(row):
    m = row.get("message")
    if isinstance(m, dict):
        c = m.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    if isinstance(row.get("content"), str):
        return row["content"]
    return ""


# rows that are wrappers / system noise, not a real human task
_SKIP_PREFIXES = (
    "<command-message>", "<command-name>", "<command-args>", "<local-command",
    "<system-reminder>", "<user-", "<task-", "caveat:", "[request interrupted",
    "this session is being continued", "分析:", "analysis:",
)


def _candidate_task(row):
    """Return a cleaned task string if this row looks like a real human prompt, else None."""
    t = _text_of(row).strip()
    if not t:
        return None
    low = t.lstrip().lower()
    if low.startswith(_SKIP_PREFIXES):
        return None
    t = clean_task(t)
    # after cleaning a slash-command, an XML-wrapper leftover starting with '<' is noise
    if not t or t.startswith("<") or len(t) < 8:
        return None
    return t


def enrich_from_transcript(session_id, cwd):
    """Pull the originating task line + gitBranch from the session transcript (cached by mtime)."""
    path = find_transcript(session_id, cwd)
    if not path:
        return {"task": None, "gitBranch": None, "recent3": []}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {"task": None, "gitBranch": None, "recent3": []}
    cached = _transcript_cache.get(session_id)
    if cached and cached[0] == mtime:
        return cached[1]

    branch = None
    prompts = []   # every real human prompt, in order → first = task, last 3 = 最近3件事
    try:
        # OOM guard: a transcript is untrusted 3rd-party data; a single line can be huge
        # (big tool result / base64). Skip enrichment entirely on oversized files.
        if os.path.getsize(path) > MAX_TRANSCRIPT:
            result = {"task": None, "gitBranch": None, "recent3": []}
            _transcript_cache[session_id] = (mtime, result)
            return result
        with open(path, encoding="utf-8") as f:
            for line in f:
                if len(line) > MAX_LINE or not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if branch is None and row.get("gitBranch"):
                    branch = row["gitBranch"]
                if not row.get("isMeta") and not row.get("isSidechain") and row.get("type") in ("user", "queue-operation"):
                    c = _candidate_task(row)
                    if c and (not prompts or prompts[-1] != c):
                        prompts.append(c)
    except OSError:
        pass

    result = {
        "task": prompts[0] if prompts else None,
        "gitBranch": branch,
        "recent3": prompts[-3:][::-1],   # newest first, for 回顾
    }
    _transcript_cache[session_id] = (mtime, result)
    return result


def _session_id_from_path(path):
    name = os.path.basename(path)
    if not name.endswith(".jsonl"):
        return ""
    sid = name[:-6]
    return sid if SID_RE.match(sid) else ""


def _transcript_cold_summary(path):
    """Read one Claude transcript directly, for first-run installs before ccm has written STORE."""
    sid = _session_id_from_path(path)
    if not sid:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    if time.time() - st.st_mtime > STALE_HOURS * 3600:
        return None
    if st.st_size > MAX_TRANSCRIPT:
        return None

    cwd = ""
    branch = None
    prompts = []
    last_assistant = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if len(line) > MAX_LINE or not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                cwd = cwd or row.get("cwd", "")
                if branch is None and row.get("gitBranch"):
                    branch = row["gitBranch"]
                typ = row.get("type")
                if not row.get("isMeta") and not row.get("isSidechain") and typ in ("user", "queue-operation"):
                    c = _candidate_task(row)
                    if c and (not prompts or prompts[-1] != c):
                        prompts.append(c)
                elif typ == "assistant":
                    txt = _text_of(row)
                    if txt:
                        last_assistant = txt
    except OSError:
        return None

    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime))
    return {
        "id": sid,
        "cwd": cwd,
        "branch": branch or "",
        "task": prompts[0] if prompts else "",
        "recent3": prompts[-3:][::-1],
        "activity": last_assistant,
        "updated": iso,
    }


def build_claude_cold_cards(extras, titles, skip_ids=None):
    """Fallback data path: direct transcript scan when ~/.claude-monitor/sessions.json is absent/empty."""
    skip_ids = skip_ids or set()
    if not os.path.isdir(CLAUDE_PROJECTS):
        return []

    now = time.time()
    paths = []
    try:
        for p in glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*.jsonl")):
            try:
                if now - os.path.getmtime(p) <= STALE_HOURS * 3600:
                    paths.append(p)
            except OSError:
                continue
    except Exception:
        return []
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    # 缓存只缓存贵的部分(transcript 解析);status/override/note 每次现算 —
    # 否则用户点存档后 10s 内读到旧缓存卡,表现为"存档无效"(实测教训)
    sig = tuple((p, int(os.path.getmtime(p))) for p in paths[:200])
    if _fallback_cache["sig"] == sig and now - _fallback_cache["ts"] < 10:
        summaries = _fallback_cache["cards"]
    else:
        summaries = [s for s in (_transcript_cold_summary(p) for p in paths[:200]) if s]
        _fallback_cache.update({"ts": now, "sig": sig, "cards": summaries})

    cards = []
    for s in summaries:
        if s["id"] in skip_ids:
            continue
        title_meta = titles.get(s["id"]) or {}
        ago_str, age_secs = ago(s["updated"])
        status = "running" if age_secs < 90 else "waiting"
        if title_meta.get("scheduled") and status != "running":
            continue
        ex = extras.get(s["id"], {})
        overridden = False
        ov = ex.get("override")
        if ov and ov.get("at") == s["updated"] and ov.get("status") in ("running", "waiting", "idle"):
            status = ov["status"]
            overridden = True
        task = s["task"] or title_meta.get("title") or "(无内容)"
        cards.append({
            "id": s["id"],
            "status": status,
            "overridden": overridden,
            "task": clean_task(task),
            "title_app": title_meta.get("title") or "",
            "note": ex.get("note") or "",
            "title_ov": ex.get("title_ov") or "",
            "priority": ex.get("priority") or "",
            "activity": clean_activity(s["activity"]),
            "recent3": s["recent3"],
            "project": classify_project(title_meta.get("title") or task, s["cwd"]),
            "branch": s["branch"],
            "cwd": s["cwd"].replace(HOME, "~"),
            "ago": ago_str,
            "age": age_secs,
            "deeplink": "claude://resume?session=" + s["id"],
            "updated": s["updated"],
            "engine": "claude",
        })
    return cards


def clean_task(t):
    """First line, strip a leading slash-command word + markdown heading, collapse ws, truncate."""
    t = t.strip()
    # drop a leading slash-command token like "/grill" but keep the argument text
    t = re.sub(r"^/([a-zA-Z0-9_-]+)\s+", "", t)
    first = next((ln.strip() for ln in t.splitlines() if ln.strip()), t)
    first = re.sub(r"^#+\s*", "", first)       # markdown heading marker
    first = re.sub(r"\s+", " ", first)
    return first[:90]


def clean_activity(t):
    """Condense the last assistant message into one short line (what's happening / what it asks)."""
    t = (t or "").strip()
    if not t:
        return ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)          # drop code fences
    t = re.sub(r"[*_`#>|\-]{1,}", " ", t)                   # markdown noise
    t = re.sub(r"https?://\S+", "", t)                      # urls
    first = next((ln.strip() for ln in t.splitlines() if len(ln.strip()) > 4), t)
    first = re.sub(r"\s+", " ", first).strip()
    return first[:130]


def classify_project(task, cwd):
    # Coarse fixed buckets (user-chosen). cwd hint OR keyword-in-task → bucket; else fallback.
    # Deliberately coarse: better an honest "其他" than a confident wrong guess.
    cfg = load_projects()
    text = (task or "").lower()
    cl = (cwd or "").lower()
    for b in cfg.get("buckets", []):
        for h in b.get("cwd", []):
            if h.lower() in cl:
                return b["name"]
        for kw in b.get("keywords", []):
            if kw.lower() in text:
                return b["name"]
    return cfg.get("fallback", "其他")


def ago(iso_ts):
    try:
        # stored ts is UTC (…Z); timegm treats the struct as UTC (DST-safe, no manual offset)
        t = calendar.timegm(time.strptime(iso_ts[:19], "%Y-%m-%dT%H:%M:%S"))
        delta = time.time() - t
    except Exception:
        return "", 1e12
    secs = max(0, int(delta))
    if secs < 60:
        return f"{secs} 秒前", secs
    if secs < 3600:
        return f"{secs // 60} 分钟前", secs
    if secs < 86400:
        return f"{secs // 3600} 小时前", secs
    return f"{secs // 86400} 天前", secs


def display_status(ccm_status, age_secs):
    """跑着/等你 = 事实(agent 状态);搁置 = 决策(仅手动拖拽 override)。
    人要吃饭睡觉——停了多久都算"等你",机器不猜"你大概不管了"(CMO 2026-07-04 定)。"""
    if ccm_status == "running":
        return "running"          # 🟢 跑着
    return "waiting"              # 🟡 停着即等你(48h 窗口由 STALE_HOURS 统一裁掉)


def demo_mode():
    return os.path.exists(DEMO_MODE) or os.environ.get("BUTLER_DEMO") == "1"


def demo_cards():
    """Privacy-safe recording data. Never reads Claude/Codex state."""
    now = time.time()
    extras = load_demo_extras()

    def stamp(seconds_ago):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - seconds_ago))

    def card(i, status, title, task, note, activity, project, engine, age_secs, priority="", recent3=None):
        updated = stamp(age_secs)
        ago_str, _ = ago(updated)
        return {
            "id": f"demo-{i}",
            "status": status,
            "overridden": False,
            "task": task,
            "title_app": title,
            "title_ov": "",
            "note": note,
            "priority": priority,
            "activity": activity,
            "recent3": recent3 or [],
            "project": project,
            "branch": "main" if engine == "claude" else "",
            "cwd": f"~/Demo/{project.replace(' ', '-')}",
            "ago": ago_str,
            "age": age_secs,
            "deeplink": "",
            "updated": updated,
            "engine": engine,
        }

    cards = [
        card(
            1, "waiting", "Release checklist", "Review final launch notes",
            "Confirm README, screenshots, and release checklist before shipping.",
            "Waiting for your approval on the final diff and release notes.",
            "Launch", "claude", 180, "P0",
            ["Updated install copy", "Checked privacy scan", "Prepared release notes"],
        ),
        card(
            2, "waiting", "Docs polish", "Tighten README opener",
            "Make the first screen explain Butler in one sentence.",
            "Waiting for your wording pass on the headline.",
            "Docs", "codex", 420, "P1",
            ["Added language switcher", "Moved install notes up", "Trimmed vague copy"],
        ),
        card(
            3, "waiting", "Demo script", "Record a two-minute walkthrough",
            "Walk through menu badge, popover, mini card, and Butler Light.",
            "Waiting for you to start the recording.",
            "Content", "claude", 900, "P2",
            ["Drafted talking points", "Marked safe fake data", "Opened demo board"],
        ),
        card(
            4, "running", "Test matrix", "Run smoke checks",
            "Keep an eye on native app packaging and status JSON.",
            "Running build checks for Butler Light package.",
            "QA", "codex", 38, "",
            ["Compiled Swift target", "Linted localized strings"],
        ),
        card(
            5, "running", "Icon pass", "Generate companion icon variants",
            "Prepare a clean app icon for the optional light companion.",
            "Rendering icon assets and validating bundle resources.",
            "Design", "claude", 64, "",
            ["Exported iconset", "Bundled AppIcon.icns"],
        ),
        card(
            6, "idle", "Later ideas", "Explore GitHub release assets",
            "Nice-to-have ideas parked until after launch.",
            "Shelved until the first public release is out.",
            "Backlog", "codex", 7200, "",
            ["DMG styling", "Release copy variants"],
        ),
    ]

    for c in cards:
        ex = extras.get(c["id"], {})
        c["note"] = ex.get("note", c["note"]) or ""
        c["title_ov"] = ex.get("title_ov", c["title_ov"]) or ""
        c["priority"] = ex.get("priority", c["priority"]) or ""
        ov = ex.get("override") or {}
        if ov.get("status") in ("running", "waiting", "idle"):
            c["status"] = ov["status"]
            c["overridden"] = True

    order = {"running": 0, "waiting": 1, "idle": 2}
    prio = {"P0": 0, "P1": 1, "P2": 2, "": 3}
    cards.sort(key=lambda c: (order.get(c["status"], 9), prio.get(c.get("priority", ""), 3), c["age"]))
    return cards


def export_light_status(cards):
    """Tiny local bridge consumed by Butler Light companion apps."""
    global _light_status_sig
    waiting = sum(1 for c in cards if c.get("status") == "waiting")
    running = sum(1 for c in cards if c.get("status") == "running")
    shelved = sum(1 for c in cards if c.get("status") == "idle")
    if waiting > 0:
        state = "waiting"
    elif running > 0:
        state = "running"
    elif shelved > 0:
        state = "shelved"
    else:
        state = "idle"

    sig = (waiting, running, shelved, state)
    if sig == _light_status_sig:
        return

    payload = {
        "waiting": waiting,
        "running": running,
        "shelved": shelved,
        "state": state,
        "updatedAt": int(time.time()),
    }
    try:
        os.makedirs(os.path.dirname(LIGHT_STATUS), exist_ok=True)
        tmp = LIGHT_STATUS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, LIGHT_STATUS)
        _light_status_sig = sig
    except OSError:
        pass


CODEX_DIR = os.path.join(HOME, ".codex", "sessions")
CODEX_RUNNING_SECS = 90        # 文件 90s 内有写入 = 跑着 (PRD F1)
CODEX_INTERNAL_TASK = "__codex_internal_session__"


def _codex_tail_events(path, size):
    """末尾 64KB 里最后一个 task_complete 的 last_agent_message(无则 None)。"""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, size - 65536))
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    msg = None
    for line in chunk.splitlines():
        if '"task_complete"' not in line:
            continue
        try:
            p = json.loads(line).get("payload", {})
            if p.get("type") == "task_complete":
                msg = p.get("last_agent_message") or msg
        except Exception:
            continue
    return msg


def _codex_head_meta(path):
    """首 32KB: session_meta 的 cwd + 首条用户消息文本(当任务行)。"""
    cwd, task = "", ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(80):
                line = f.readline()
                if not line:
                    break
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                p = row.get("payload", {})
                if row.get("type") == "session_meta":
                    cwd = cwd or p.get("cwd", "")
                    source = p.get("source")
                    if p.get("thread_source") == "subagent" or (isinstance(source, dict) and source.get("subagent")):
                        return cwd, CODEX_INTERNAL_TASK
                elif not task:
                    # event_msg:user_message 或 response_item:message(role=user)
                    t = ""
                    if p.get("type") == "user_message":
                        t = p.get("message", "")
                    elif p.get("role") == "user":
                        c = p.get("content")
                        if isinstance(c, list):
                            t = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                        elif isinstance(c, str):
                            t = c
                    # 注入内容(<environment_context>/附件清单/# 标题/路径行)非任务 → 行级过滤取第一个人话行
                    for ln in t.splitlines():
                        ln = ln.strip()
                        if not ln or ln[0] in "<#" or ln.startswith("/") or ln.startswith("Files mentioned"):
                            continue
                        task = ln
                        break
                if cwd and task:
                    break
    except OSError:
        pass
    return cwd, task


def build_codex_cards(extras):
    """Codex CLI 会话 → 统一卡片模型(engine=codex)。PRD F1。
    状态: mtime<90s=跑着; 最后 task_complete 且 <FRESH_MIN=等你; 其余=搁置; >STALE_HOURS 不显示。
    """
    cards = []
    if not os.path.isdir(CODEX_DIR):
        return cards
    now = time.time()
    # 目录按"创建日期"组织,但会话可跨多天续用(mtime≫目录日期) → 目录扫 14 天,靠 mtime 过滤
    for off in range(14):
        d = time.localtime(now - off * 86400)
        day_dir = os.path.join(CODEX_DIR, f"{d.tm_year:04d}", f"{d.tm_mon:02d}", f"{d.tm_mday:02d}")
        if not os.path.isdir(day_dir):
            continue
        for name in os.listdir(day_dir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(day_dir, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            age = int(now - st.st_mtime)
            if age > STALE_HOURS * 3600:
                continue
            last_msg = _codex_tail_events(path, st.st_size)
            if age < CODEX_RUNNING_SECS:
                status = "running"
            else:
                status = "waiting"          # 停着即等你;搁置只来自手动拖拽
            cwd, task = _codex_head_meta(path)
            if task == CODEX_INTERNAL_TASK:
                continue
            sid = "codex-" + name.replace("rollout-", "").replace(".jsonl", "")
            ex = extras.get(sid, {})
            task = clean_task(task or "(无内容)")
            iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime))
            ago_str, age_secs = ago(iso)
            # 手动拖拽搁置(与 Claude 同语义): 锚定 mtime,会话有新活动即自动失效
            ov = ex.get("override")
            overridden = False
            if ov and ov.get("at") == iso and ov.get("status") in ("running", "waiting", "idle"):
                status = ov["status"]
                overridden = True
            cards.append({
                "id": sid,
                "status": status,
                "overridden": overridden,
                "task": task,
                "title_app": "",                        # Codex 无会话标题,前端用 task 兜底
                "title_ov": ex.get("title_ov") or "",   # 手动改名(codex 长prompt 尤其需要)
                "note": ex.get("note") or "",
                "priority": ex.get("priority") or "",   # bug: codex 卡此前漏了 → P0/P1 点击失效
                "activity": clean_activity(last_msg or ""),
                "recent3": [],
                "project": classify_project(task, cwd),
                "branch": "",
                "cwd": cwd.replace(HOME, "~"),
                "ago": ago_str,
                "age": age_secs,
                "deeplink": "",
                "updated": iso,
                "engine": "codex",
            })
    return cards


def build_cards():
    if demo_mode():
        cards = demo_cards()
        export_light_status(cards)
        return cards

    extras = load_extras()
    titles = load_titles()
    try:
        data = json.load(open(STORE))
    except Exception:
        data = {"sessions": {}}
    sessions = data.get("sessions", {})
    cards = []
    for sid, s in sessions.items():
        if not isinstance(sid, str) or not SID_RE.match(sid):
            continue   # 3rd-party file → don't let a weird id reach the DOM
        updated = s.get("updated_at", "")
        ago_str, age_secs = ago(updated)
        if age_secs > STALE_HOURS * 3600:
            continue
        cwd = s.get("cwd", "")
        enr = enrich_from_transcript(sid, cwd)
        task = enr["task"] or clean_task(s.get("lastMessage", "") or "(无内容)")
        app_title = (titles.get(sid) or {}).get("title") or ""   # the name shown in the app sidebar
        branch = enr["gitBranch"]
        ccm_status = s.get("status", "")
        # ccm 的 Stop 事件在长轮次里会丢(实测卡死 running 89分钟) → transcript mtime 当心跳二次校验:
        # 说 running 但转录 90s 没写 = 其实停了,降级按 stopped 映射(刚停=等你/久=搁置)
        if ccm_status == "running":
            tp = find_transcript(sid, cwd)
            try:
                hb = time.time() - os.stat(tp).st_mtime if tp else 1e9
            except OSError:
                hb = 1e9
            if hb > 90:
                ccm_status = "stopped"
                # 时间也改用心跳(ccm 的 updated_at 同样停在丢事件那刻)
                ago_str, age_secs = ago(time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - hb)))
        status = display_status(ccm_status, age_secs)

        # 例行任务(scheduledTaskId): 跑着时显示,停了即消失 — cron 跑完≠等你,不产生假待办
        if (titles.get(sid) or {}).get("scheduled") and status != "running":
            continue

        ex = extras.get(sid, {})
        # #1 manual override: sticks until the session sees new activity (updated_at moves)
        ov = ex.get("override")
        overridden = False
        if ov and ov.get("at") == updated and ov.get("status") in ("running", "waiting", "idle"):
            status = ov["status"]
            overridden = True

        cards.append({
            "id": sid,
            "status": status,
            "overridden": overridden,
            "task": task,
            "title_app": app_title,                # 和 App 侧边栏一致的对话名(找会话不再靠猜)
            "note": ex.get("note") or "",          # #6 目的备注 (空=前端用 App名/task 兜底)
            "title_ov": ex.get("title_ov") or "",  # 手动改名
            "priority": ex.get("priority") or "",  # P0/P1/P2 手打优先级(持久任务属性)
            "activity": clean_activity(s.get("lastMessage", "")),   # #4 正在跑什么/需要你什么
            "recent3": enr.get("recent3", []),     # #4 最近3件事,好回顾
            "project": classify_project(app_title or task, cwd),
            "branch": branch or "",
            "cwd": cwd.replace(HOME, "~"),
            "ago": ago_str,
            "age": age_secs,
            "deeplink": "claude://resume?session=" + sid,   # #3 一键跳回对话
            "updated": updated,
            "engine": "claude",
        })
    cards.extend(build_claude_cold_cards(extras, titles, {c["id"] for c in cards}))
    cards.extend(build_codex_cards(extras))    # F1: 双引擎统一进看板
    order = {"running": 0, "waiting": 1, "idle": 2}
    prio = {"P0": 0, "P1": 1, "P2": 2, "": 3}
    cards.sort(key=lambda c: (order.get(c["status"], 9),
                              prio.get(c.get("priority", ""), 3), c["age"]))
    # prune transcript cache to what's live now (prevent slow unbounded growth on long runs)
    live = {c["id"] for c in cards}
    for k in list(_transcript_cache):
        if k not in live:
            _transcript_cache.pop(k, None)
    export_light_status(cards)
    return cards


# ── HTTP ──────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def do_GET(self):
        if self.path.startswith("/api/sessions"):
            body = json.dumps({"cards": build_cards(), "ts": int(time.time()), "demo": demo_mode()}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/" or self.path.startswith("/?"):
            self._serve_html(PAGE)
        elif self.path.startswith("/popover"):
            self._serve_html(PAGE_POPOVER)      # v3 F12: NSPanel 浮窗视图
        elif self.path.startswith("/mini"):
            self._serve_html(PAGE_MINI)         # v3 F13: 桌面 mini 看板
        elif self.path.startswith("/api/health"):
            body = json.dumps({"src_mtime": _SRC_MTIME, "locale": BUTLER_LOCALE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/uistate"):
            # 浮窗底部 toggle 的状态源: mini 开关/层级 + 开机自启(LaunchAgent RunAtLoad)
            st = {}
            try:
                st = json.load(open(os.path.join(HOME, ".claude-monitor", "ui-state.json")))
            except Exception:
                pass
            auto = bool(st.get("autostart"))   # native 版由 Swift 写入 ui-state.json(SMAppService 状态)
            body = json.dumps({"mini_on": bool(st.get("mini_on")), "mini_top": bool(st.get("mini_top")),
                               "autostart": auto, "demo": demo_mode()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self, page):
        body = page_with_i18n(page).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")   # stale frontend JS caused ghost bugs
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except (ValueError, TypeError):
            return {}
        if n <= 0 or n > MAX_POST:      # cap body size (LAN memory-DoS guard)
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _ok(self, obj=None):
        body = json.dumps(obj or {"ok": True}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _demo_post(self, b, sid):
        if not sid or not isinstance(sid, str) or not sid.startswith("demo-"):
            return self._ok({"ok": False, "demo": True, "err": "unknown demo card"})

        if self.path.startswith("/api/override"):
            status = b.get("status")
            if status == "clear":
                clear_demo_override(sid)
                return self._ok({"ok": True, "demo": True})
            if status in ("running", "waiting", "idle"):
                set_demo_extra(sid, override={"status": status})
                return self._ok({"ok": True, "demo": True})
            return self._ok({"ok": False, "demo": True, "err": "bad status"})

        if self.path.startswith("/api/note"):
            set_demo_extra(sid, note=(b.get("note") or "").strip())
            return self._ok({"ok": True, "demo": True})

        if self.path.startswith("/api/title"):
            set_demo_extra(sid, title_ov=(b.get("title") or "").strip())
            return self._ok({"ok": True, "demo": True})

        if self.path.startswith("/api/priority"):
            p = b.get("priority") or ""
            if p in ("", "P0", "P1", "P2"):
                set_demo_extra(sid, priority=p)
                return self._ok({"ok": True, "demo": True})
            return self._ok({"ok": False, "demo": True, "err": "bad priority"})

        return self._ok({"ok": True, "demo": True})

    def do_POST(self):
        b = self._json_body()
        sid = b.get("id")
        if self.path.startswith("/api/ui"):
            # v3: webview(浮窗/mini) → 菜单栏 app 进程的命令通道(app 1s 轮询 UI_CMD 文件)
            cmd = b.get("cmd")
            if cmd in ("board", "mini", "minitop", "quit", "hidepop", "autostart"):
                os.makedirs(os.path.dirname(EXTRAS), exist_ok=True)
                tmp = UI_CMD + ".tmp"
                json.dump({"cmd": cmd, "top": bool(b.get("top")), "ts": time.time()}, open(tmp, "w"))
                os.replace(tmp, UI_CMD)
            return self._ok()
        if demo_mode():
            return self._demo_post(b, sid)
        if self.path.startswith("/api/override") and sid:
            status = b.get("status")
            if status == "clear":
                clear_override(sid)
                return self._ok()
            if status in ("running", "waiting", "idle"):
                # 锚点统一取自 build_cards 输出的 updated — ccm卡/fallback卡/Codex卡 单一事实源
                # (旧版查 ccm STORE: fallback 卡拿不到锚点 → 存档永不生效,实测教训)
                cur = next((c["updated"] for c in build_cards() if c["id"] == sid), "")
                if not cur:
                    return self._ok({"ok": False, "err": "unknown session"})
                set_extra(sid, override={"status": status, "at": cur})
                return self._ok()
            return self._ok({"ok": False, "err": "bad status"})
        if self.path.startswith("/api/note") and sid:
            set_extra(sid, note=(b.get("note") or "").strip())
            return self._ok()
        if self.path.startswith("/api/title") and sid:
            set_extra(sid, title_ov=(b.get("title") or "").strip())   # 手动改名(尤其 Codex 长prompt)
            return self._ok()
        if self.path.startswith("/api/priority") and sid:
            p = b.get("priority") or ""
            if p in ("", "P0", "P1", "P2"):
                set_extra(sid, priority=p)
                return self._ok()
            return self._ok({"ok": False, "err": "bad priority"})
        self.send_response(404)
        self.end_headers()
I18N_SNIPPET = r"""
<script>
(() => {
  const forced = "__BUTLER_LOCALE__";
  const browser = ((navigator.languages && navigator.languages[0]) || navigator.language || "en").toLowerCase();
  const lang = forced && forced !== "auto" ? forced : browser;
  const locale = lang.startsWith("zh") ? "zh" : lang.startsWith("ja") ? "ja" : lang.startsWith("ko") ? "ko" : lang.startsWith("es") ? "es" : "en";
  if (locale === "zh") return;

  const dict = {
    en: {
      "在飞看板": "In-flight board", "谁在等你": "who needs you", "谁在跑": "what is running",
      "连接中": "Connecting", "全部": "All", "加载中": "Loading", "等你下一步": "Waiting for you",
      "正在跑": "Running", "搁置 / 完成": "Shelved / Done", "待回应": "Needs reply",
      "进行中": "In progress", "停在": "Stopped", "未命名会话": "Untitled session",
      "点击填写/编辑目的": "Click to add or edit purpose", "目的": "Purpose", "点击填写": "Click to add",
      "点击切换优先级": "Click to change priority", "手动": "Manual", "最近": "Recent",
      "拖动换列": "Drag to another column", "复制名字": "Copy name",
      "眼下没有在飞的会话": "No active agent sessions right now",
      "去 Claude 里甩个任务，几秒后它会出现在这里。安心走开，回来一眼就知道谁在等你。": "Start a task in Claude or Codex; it will appear here in a few seconds.",
      "已更新": "Updated", "连接断开，重试中": "Disconnected, retrying",
      "这个对话最高优先级的目的（回车保存 · Esc 取消 · 清空=删除）": "Purpose for this session (Enter saves, Esc cancels, empty deletes)",
      "给这个会话起个名(回车存·Esc取消·清空=恢复原名)": "Name this session (Enter saves, Esc cancels, empty restores)",
      "已复制,去App搜索粘贴": "Copied. Paste into the app search.", "Butler 在飞面板": "Butler in-flight panel",
      "显示桌面看板": "Show desktop mini board", "开机自启": "Launch at login",
      "打开完整看板": "Open full board", "退出": "Quit", "搁置(先不管它)": "Shelve for now",
      "复制会话名": "Copy session name", "点击修改目的": "Click to edit purpose",
      "全部安静 — 没有在飞的任务": "All quiet — no in-flight tasks",
      "置顶显示": "Keep on top", "隐藏桌面看板": "Hide desktop mini board", "全部安静": "All quiet",
      "在跑": "running", "等你": "Waiting", "跑着": "Running", "搁置": "Shelved",
      "其他": "Other", "无内容": "No content", "秒前": "s ago", "分钟前": "m ago", "小时前": "h ago", "天前": "d ago"
    },
    es: {
      "在飞看板": "Tablero en curso", "谁在等你": "quién te espera", "谁在跑": "qué está corriendo",
      "连接中": "Conectando", "全部": "Todo", "加载中": "Cargando", "等你下一步": "Esperando por ti",
      "正在跑": "Corriendo", "搁置 / 完成": "Archivado / hecho", "待回应": "Necesita respuesta",
      "进行中": "En curso", "停在": "Detenido en", "未命名会话": "Sesión sin título",
      "点击填写/编辑目的": "Haz clic para añadir o editar propósito", "目的": "Propósito", "点击填写": "Haz clic para añadir",
      "点击切换优先级": "Haz clic para cambiar prioridad", "手动": "Manual", "最近": "Reciente",
      "拖动换列": "Arrastra a otra columna", "复制名字": "Copiar nombre",
      "眼下没有在飞的会话": "No hay sesiones activas ahora",
      "去 Claude 里甩个任务，几秒后它会出现在这里。安心走开，回来一眼就知道谁在等你。": "Inicia una tarea en Claude o Codex; aparecerá aquí en unos segundos.",
      "已更新": "Actualizado", "连接断开，重试中": "Desconectado, reintentando",
      "这个对话最高优先级的目的（回车保存 · Esc 取消 · 清空=删除）": "Propósito de esta sesión (Enter guarda, Esc cancela, vacío elimina)",
      "给这个会话起个名(回车存·Esc取消·清空=恢复原名)": "Nombre de esta sesión (Enter guarda, Esc cancela, vacío restaura)",
      "已复制,去App搜索粘贴": "Copiado. Pégalo en la búsqueda de la app.", "Butler 在飞面板": "Panel en curso de Butler",
      "显示桌面看板": "Mostrar mini tablero de escritorio", "开机自启": "Abrir al iniciar",
      "打开完整看板": "Abrir tablero completo", "退出": "Salir", "搁置(先不管它)": "Archivar por ahora",
      "复制会话名": "Copiar nombre de sesión", "点击修改目的": "Haz clic para editar propósito",
      "全部安静 — 没有在飞的任务": "Todo tranquilo — no hay tareas en curso",
      "置顶显示": "Mantener arriba", "隐藏桌面看板": "Ocultar mini tablero", "全部安静": "Todo tranquilo",
      "在跑": "corriendo", "等你": "Esperando", "跑着": "Corriendo", "搁置": "Archivado",
      "其他": "Otro", "无内容": "Sin contenido", "秒前": "s atrás", "分钟前": "min atrás", "小时前": "h atrás", "天前": "d atrás"
    },
    ja: {
      "在飞看板": "進行中ボード", "谁在等你": "あなた待ち", "谁在跑": "実行中",
      "连接中": "接続中", "全部": "すべて", "加载中": "読み込み中", "等你下一步": "あなたの対応待ち",
      "正在跑": "実行中", "搁置 / 完成": "保留 / 完了", "待回应": "返信待ち",
      "进行中": "進行中", "停在": "停止", "未命名会话": "無題のセッション",
      "点击填写/编辑目的": "クリックして目的を追加/編集", "目的": "目的", "点击填写": "クリックして入力",
      "点击切换优先级": "クリックして優先度を変更", "手动": "手動", "最近": "最近",
      "拖动换列": "ドラッグして列を変更", "复制名字": "名前をコピー",
      "眼下没有在飞的会话": "現在進行中のセッションはありません",
      "去 Claude 里甩个任务，几秒后它会出现在这里。安心走开，回来一眼就知道谁在等你。": "Claude または Codex でタスクを始めると、数秒後にここへ表示されます。",
      "已更新": "更新済み", "连接断开，重试中": "切断されました。再試行中",
      "这个对话最高优先级的目的（回车保存 · Esc 取消 · 清空=删除）": "このセッションの目的 (Enterで保存、Escで取消、空で削除)",
      "给这个会话起个名(回车存·Esc取消·清空=恢复原名)": "セッション名 (Enterで保存、Escで取消、空で元に戻す)",
      "已复制,去App搜索粘贴": "コピーしました。アプリ検索に貼り付けてください。", "Butler 在飞面板": "Butler 進行中パネル",
      "显示桌面看板": "デスクトップミニボードを表示", "开机自启": "ログイン時に起動",
      "打开完整看板": "フルボードを開く", "退出": "終了", "搁置(先不管它)": "いったん保留",
      "复制会话名": "セッション名をコピー", "点击修改目的": "クリックして目的を編集",
      "全部安静 — 没有在飞的任务": "静かです — 進行中のタスクはありません",
      "置顶显示": "常に手前に表示", "隐藏桌面看板": "デスクトップミニボードを隠す", "全部安静": "すべて静か",
      "在跑": "実行中", "等你": "あなた待ち", "跑着": "実行中", "搁置": "保留",
      "其他": "その他", "无内容": "内容なし", "秒前": "秒前", "分钟前": "分前", "小时前": "時間前", "天前": "日前"
    },
    ko: {
      "在飞看板": "진행 보드", "谁在等你": "응답 대기", "谁在跑": "실행 중",
      "连接中": "연결 중", "全部": "전체", "加载中": "불러오는 중", "等你下一步": "사용자 응답 대기",
      "正在跑": "실행 중", "搁置 / 完成": "보류 / 완료", "待回应": "응답 필요",
      "进行中": "진행 중", "停在": "멈춤", "未命名会话": "이름 없는 세션",
      "点击填写/编辑目的": "클릭하여 목적 추가/수정", "目的": "목적", "点击填写": "클릭하여 입력",
      "点击切换优先级": "클릭하여 우선순위 변경", "手动": "수동", "最近": "최근",
      "拖动换列": "드래그하여 열 이동", "复制名字": "이름 복사",
      "眼下没有在飞的会话": "현재 진행 중인 세션이 없습니다",
      "去 Claude 里甩个任务，几秒后它会出现在这里。安心走开，回来一眼就知道谁在等你。": "Claude 또는 Codex에서 작업을 시작하면 몇 초 후 여기에 표시됩니다.",
      "已更新": "업데이트됨", "连接断开，重试中": "연결 끊김, 재시도 중",
      "这个对话最高优先级的目的（回车保存 · Esc 取消 · 清空=删除）": "이 세션의 목적 (Enter 저장, Esc 취소, 비우면 삭제)",
      "给这个会话起个名(回车存·Esc取消·清空=恢复原名)": "세션 이름 (Enter 저장, Esc 취소, 비우면 복원)",
      "已复制,去App搜索粘贴": "복사됨. 앱 검색에 붙여넣으세요.", "Butler 在飞面板": "Butler 진행 패널",
      "显示桌面看板": "데스크톱 미니 보드 보기", "开机自启": "로그인 시 실행",
      "打开完整看板": "전체 보드 열기", "退出": "종료", "搁置(先不管它)": "지금은 보류",
      "复制会话名": "세션 이름 복사", "点击修改目的": "클릭하여 목적 수정",
      "全部安静 — 没有在飞的任务": "조용합니다 — 진행 중인 작업이 없습니다",
      "置顶显示": "항상 위에 표시", "隐藏桌面看板": "데스크톱 미니 보드 숨기기", "全部安静": "모두 조용함",
      "在跑": "실행 중", "等你": "응답 대기", "跑着": "실행 중", "搁置": "보류",
      "其他": "기타", "无内容": "내용 없음", "秒前": "초 전", "分钟前": "분 전", "小时前": "시간 전", "天前": "일 전"
    }
  };
  const table = dict[locale] || dict.en;
  document.documentElement.lang = locale === "zh" ? "zh-Hans" : locale;
  const keys = Object.keys(table).sort((a, b) => b.length - a.length);
  const rx = [
    [/还有 (\d+) 件等你 · 点菜单栏 ▦ 看全部/g, (_, n) => locale === "ja" ? `ほか ${n} 件があなた待ち · メニューバー ▦ で全件表示` : locale === "ko" ? `응답 대기 ${n}개 더 있음 · 메뉴 막대 ▦ 에서 모두 보기` : locale === "es" ? `${n} más esperando · abre ▦ para ver todo` : `${n} more waiting · open ▦ for all`],
    [/还有 (\d+) 件/g, (_, n) => locale === "ja" ? `ほか ${n} 件` : locale === "ko" ? `${n}개 더 있음` : locale === "es" ? `${n} más` : `${n} more`],
    [/(\d+) 件/g, (_, n) => locale === "ja" ? `${n} 件` : locale === "ko" ? `${n}개` : `${n}`]
  ];
  function translate(s) {
    if (!s) return s;
    let out = s;
    for (const [r, f] of rx) out = out.replace(r, f);
    for (const k of keys) out = out.split(k).join(table[k]);
    return out;
  }
  function apply(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      const v = translate(n.nodeValue);
      if (v !== n.nodeValue) n.nodeValue = v;
    }
    for (const el of root.querySelectorAll("[title],[aria-label],[placeholder]")) {
      for (const attr of ["title", "aria-label", "placeholder"]) {
        if (el.hasAttribute(attr)) {
          const v = translate(el.getAttribute(attr));
          if (v !== el.getAttribute(attr)) el.setAttribute(attr, v);
        }
      }
    }
    document.title = translate(document.title);
  }
  let scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; apply(); });
  }
  document.addEventListener("DOMContentLoaded", schedule);
  new MutationObserver(schedule).observe(document.documentElement, {childList: true, subtree: true, characterData: true});
  schedule();
})();
</script>
"""


def page_with_i18n(page):
    snippet = I18N_SNIPPET.replace("__BUTLER_LOCALE__", BUTLER_LOCALE)
    return page.replace("</body>", snippet + "</body>", 1) if "</body>" in page else page + snippet


PAGE = r"""<!doctype html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Butler · 在飞看板</title>
<style>
  /* ── tokens ────────────────────────────────────────────────
     Near-monochrome, Codex/Vercel restraint. One accent (amber),
     used only to mark "等你". Everything else is neutral grayscale.
     Light default; dark via prefers-color-scheme at the semantic layer. */
  :root{
    --bg:#fbfbfa;          /* warm off-white canvas */
    --surface:#ffffff;     /* card surface */
    --surface-2:#f5f5f4;   /* faint fill (chips, expanded rows) */
    --line:#e7e6e2;        /* hairline */
    --line-2:#efeeea;      /* even softer hairline */
    --fg:#1a1a19;          /* off-black primary text */
    --fg-2:#57534e;        /* secondary (7.6:1) */
    --dim:#726d64;         /* metadata / activity text (5.1:1, AA) */
    --faint:#8a857d;       /* timestamps, index, hints (3.7:1) */
    --accent:#b45309;      /* single accent: amber-700, waiting only */
    --accent-soft:#fbf3e6; /* accent tint for the one filled dot bg */
    --focus:#2563eb;       /* focus ring only */
  }
  @media (prefers-color-scheme: dark){
    :root{
      --bg:#0e0e0e;
      --surface:#161616;
      --surface-2:#1d1d1c;
      --line:#282826;
      --line-2:#222221;
      --fg:#eceae6;
      --fg-2:#a8a39b;        /* 7.2:1 */
      --dim:#938e85;         /* metadata / activity text (5.6:1, AA) */
      --faint:#7a756d;       /* timestamps, index, hints (4.0:1) */
      --accent:#e0a153;
      --accent-soft:#2a2013;
      --focus:#5b8bf0;
    }
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    background:var(--bg);
    color:var(--fg);
    font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
    min-height:100vh;
  }
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,"SF Mono",monospace;
    font-variant-numeric:tabular-nums}
  :focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}

  /* ── header ─────────────────────────────────────────────── */
  header{
    position:sticky;top:0;z-index:5;
    padding:18px 28px 15px;
    background:color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line-2);
  }
  .head-row{display:flex;align-items:center;gap:16px;max-width:960px;margin:0 auto}
  .brand{display:flex;align-items:baseline;gap:12px;min-width:0}
  .brand h1{font-size:15px;margin:0;font-weight:600;letter-spacing:-.01em;
    white-space:nowrap;color:var(--fg)}
  .brand .sub{color:var(--dim);font-size:12.5px;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis}
  .live{margin-left:auto;display:flex;align-items:center;gap:7px;color:var(--dim);
    font-size:12px;white-space:nowrap}
  .live .beat{width:6px;height:6px;border-radius:50%;background:var(--dim);opacity:.7}
  .live:not(.stale) .beat{background:var(--fg-2)}
  .live.stale{color:var(--faint)}

  /* summary tally — three quiet counts, mono numerals, no pills */
  .tally-row{display:flex;align-items:center;justify-content:space-between;gap:14px;
    max-width:960px;margin:12px auto 0;flex-wrap:wrap}
  .tally{display:flex;gap:22px;flex-wrap:wrap}
  /* 引擎 tab — CodexBar 式分开看;引擎是属性不配色相,沿用近单色 */
  .engtabs{display:flex;gap:2px;background:var(--surface-2);border:1px solid var(--line);
    border-radius:8px;padding:2px}
  .etab{appearance:none;border:none;background:transparent;color:var(--dim);cursor:pointer;
    font-family:inherit;font-size:11.5px;font-weight:500;padding:3px 11px;border-radius:6px;
    transition:color .12s,background .12s}
  .etab:hover{color:var(--fg-2)}
  .etab.on{background:var(--surface);color:var(--fg);box-shadow:0 1px 2px rgba(0,0,0,.06)}
  .stat{display:flex;align-items:baseline;gap:7px;font-size:12.5px;color:var(--dim)}
  .stat .dot{width:7px;height:7px;border-radius:50%;flex:none;align-self:center}
  .stat b{font-weight:600;font-size:13px;color:var(--fg-2)}
  .stat.wait .dot{background:var(--accent)}
  .stat.wait b{color:var(--accent)}
  .stat.run  .dot{background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}
  .stat.idle .dot{background:transparent;box-shadow:inset 0 0 0 1px var(--line);border-radius:50%}
  .stat.zero{opacity:.42}

  /* ── layout ─────────────────────────────────────────────── */
  .wrap{padding:26px 28px 72px;max-width:960px;margin:0 auto}
  .sect{margin-bottom:34px}
  .sect:last-child{margin-bottom:0}
  .sect-h{display:flex;align-items:center;gap:9px;margin:0 0 10px;padding:0 2px}
  .sect-h .dot{width:7px;height:7px;border-radius:50%;flex:none}
  .sect.wait .sect-h .dot{background:var(--accent)}
  .sect.run  .sect-h .dot{background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}
  .sect.idle .sect-h .dot{background:transparent;box-shadow:inset 0 0 0 1px var(--line)}
  .sect-h .t{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
    color:var(--fg-2)}
  .sect.wait .sect-h .t{color:var(--accent)}
  .sect-h .n{font-size:11.5px;color:var(--dim);font-weight:500}
  .sect-h .rule{flex:1;height:1px;background:var(--line-2)}

  /* ── rows (cards as list rows, hairline separation) ─────── */
  .list{display:flex;flex-direction:column;
    border:1px solid var(--line);border-radius:10px;background:var(--surface);overflow:hidden}
  .card{position:relative;padding:15px 18px;border-top:1px solid var(--line-2);
    transition:background .12s}
  .card:first-child{border-top:none}
  .card:hover{background:var(--surface-2)}

  .card .head{display:flex;align-items:flex-start;gap:11px}
  .card .sdot{width:8px;height:8px;border-radius:50%;flex:none;margin-top:6px}
  .card.waiting .sdot{background:var(--accent)}
  .card.running .sdot{background:transparent;box-shadow:inset 0 0 0 2px var(--dim)}
  .card.idle    .sdot{background:transparent;box-shadow:inset 0 0 0 1.5px var(--line)}
  .card .body{min-width:0;flex:1}
  /* drag handle — only this is draggable, so clicks on the card body always land */
  .card .grip{flex:none;margin:2px -3px 0 -6px;color:var(--faint);cursor:grab;opacity:0;
    transition:opacity .12s;display:flex;align-items:center}
  .card:hover .grip{opacity:.5}
  .card .grip:hover{opacity:1;color:var(--dim)}
  .card .grip svg{width:15px;height:15px}
  .card.dragging{opacity:.45}
  @media(hover:none){.card .grip{opacity:.4}}

  /* goal (#6, editable) — the one strong line */
  .goal{display:block;cursor:text;font-weight:550;font-size:14px;line-height:1.5;
    color:var(--fg);word-break:break-word;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .card.idle .goal{font-weight:450;color:var(--fg-2);-webkit-line-clamp:1}
  .goal .ph{color:var(--faint);font-weight:450}

  /* activity — one dim line under the goal */
  .note-line{margin-top:5px;font-size:13px;line-height:1.5;color:var(--fg);cursor:text;
    display:flex;align-items:baseline}
  .note-line .ntext{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
    overflow:hidden;word-break:break-word;min-width:0}
  .note-line .nlab{color:var(--accent);font-weight:600;font-size:11px;margin-right:7px;
    letter-spacing:.03em}
  .note-line .ntext.ph{color:var(--faint)}
  .note-line:hover .ntext.ph{color:var(--dim)}
  .note-input{flex:1;width:100%;font:inherit;font-size:13px;color:var(--fg);
    background:transparent;border:none;border-bottom:1px solid var(--accent);
    outline:none;padding:0 0 2px;margin-left:2px}
  .note-input::placeholder{color:var(--faint);font-size:12px}
  .title-input{width:100%;font:inherit;font-size:15px;font-weight:600;color:var(--fg);
    background:transparent;border:none;border-bottom:1px solid var(--accent);outline:none;padding:0 0 2px}
  .title-input::placeholder{color:var(--faint);font-size:13px;font-weight:400}
  .goal[data-title]{cursor:text}
  .act-line{margin-top:5px;font-size:12.5px;line-height:1.5;color:var(--dim);
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .act-line .lab{color:var(--faint);font-weight:500;margin-right:6px}
  .card.idle .act-line{-webkit-line-clamp:1}

  /* meta row — faintest layer */
  .meta{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:9px;
    font-size:11.5px;color:var(--dim)}
  .meta .proj{color:var(--fg-2);font-weight:500}
  /* Codex 引擎标识 — meta 行内,仅 Codex 卡渲染(非对称标识:Claude 零标记) */
  .meta .eng{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:var(--fg-2);background:var(--surface-2);
    border:1px solid var(--line);border-radius:4px;padding:1px 5px;line-height:1.4}
  .meta .br{color:var(--dim);font-size:11px}
  /* 优先级 pill — 点击循环 无→P0→P1→P2;墨色系(amber 只属于等你) */
  .meta .prio{font-size:10px;font-weight:700;letter-spacing:.04em;cursor:pointer;
    border-radius:4px;padding:1px 6px;line-height:1.4;border:1px solid transparent;
    user-select:none;transition:opacity .12s}
  .meta .prio.p0{background:var(--fg);color:var(--paper, var(--surface))}
  .meta .prio.p1{border-color:var(--fg-2);color:var(--fg-2)}
  .meta .prio.p2{border-color:var(--line);color:var(--dim)}
  .meta .prio.pnone{border:1px dashed var(--line);color:var(--faint);opacity:0}
  .card:hover .prio.pnone{opacity:1}
  .meta .sep{width:2.5px;height:2.5px;border-radius:50%;background:var(--faint);flex:none}
  .meta .ov{color:var(--faint)}
  .meta .ago{color:var(--faint)}
  .meta .spacer{flex:1}

  /* recent3 — collapsed by default, quiet inline toggle (#4 回顾) */
  .recent-tog{margin-top:9px;font-size:11.5px;color:var(--dim);background:none;border:none;
    padding:0;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:5px}
  .recent-tog:hover{color:var(--fg-2)}
  .recent-tog .cv{width:9px;height:9px;transition:transform .15s;color:var(--faint)}
  .card.open-recent .recent-tog .cv{transform:rotate(90deg)}
  .recent{display:none;margin-top:9px;padding-top:9px;border-top:1px dashed var(--line);
    flex-direction:column;gap:6px}
  .card.open-recent .recent{display:flex}
  .recent .r{display:flex;gap:9px;font-size:12px;line-height:1.5;color:var(--fg-2)}
  .recent .r .i{color:var(--faint);flex:none;font-size:11px;font-variant-numeric:tabular-nums;
    padding-top:1px}
  .recent .r .x{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

  /* actions — appear on hover, ghost buttons */
  .actions{display:flex;gap:4px;margin-top:11px;opacity:0;transition:opacity .12s}
  .card:hover .actions,.card:focus-within .actions{opacity:1}
  .act{appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--fg-2);
    font-size:11.5px;padding:4px 10px;border-radius:7px;cursor:pointer;font-family:inherit;
    display:inline-flex;align-items:center;gap:5px;line-height:1;text-decoration:none;transition:border-color .12s,color .12s}
  .act:hover{border-color:var(--dim);color:var(--fg)}
  .act svg{width:12px;height:12px}
  @media(hover:none){.actions{opacity:1}}

  /* ── empty state ────────────────────────────────────────── */
  .empty{text-align:center;padding:96px 20px;color:var(--dim)}
  .empty svg{width:26px;height:26px;color:var(--faint);margin-bottom:16px}
  .empty .l1{font-size:15px;color:var(--fg-2);font-weight:550;margin-bottom:7px}
  .empty .l2{font-size:12.5px;color:var(--faint);max-width:330px;margin:0 auto;line-height:1.65}

  /* ── drag + drop ────────────────────────────────────────── */
  .card[draggable]{cursor:grab}
  .card.dragging{opacity:.35;cursor:grabbing}
  .sect.drop-ok .list{outline:1.5px solid var(--accent);outline-offset:2px}
  .sect.drop-ok .sect-h .t{color:var(--accent)}
  /* empty columns hidden until a drag begins → become drop targets */
  .sect-empty{display:none}
  body.dragging .sect-empty{display:block}
  .drop-hint{color:var(--faint);font-size:12px;padding:20px;text-align:center;
    border:1px dashed var(--line);border-radius:10px;background:var(--surface)}

  @media(max-width:600px){
    header{padding:14px 16px 12px}
    .brand .sub{display:none}
    .wrap{padding:18px 14px 56px}
    .tally{gap:16px}
    .head-row{gap:10px}
  }
</style></head><body>
<header>
  <div class="head-row">
    <div class="brand">
      <h1>Butler</h1>
      <span class="sub">在飞看板 · 谁在等你 · 谁在跑</span>
    </div>
    <span class="live" id="live"><span class="beat"></span><span id="live-t">连接中</span></span>
  </div>
  <div class="tally-row">
    <div class="tally" id="tally"></div>
    <div class="engtabs" id="engtabs">
      <button class="etab on" data-eng="">全部</button><button class="etab" data-eng="claude">Claude</button><button class="etab" data-eng="codex">Codex</button>
    </div>
  </div>
</header>
<div class="wrap" id="wrap"><div class="empty"><div class="l1">加载中</div></div></div>
<script>
// 等你(the payload) first, then 正在跑, then 搁置(noise floor)
const GROUPS=[
  ["waiting","等你下一步"],
  ["running","正在跑"],
  ["idle","搁置 / 完成"],
];
// status → activity label (what this line means for this state)
const ACT_LAB={waiting:"待回应",running:"进行中",idle:"停在"};
const esc=s=>(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

// inline lucide icons (currentColor), no emoji anywhere
const IC={
  chevron:'<svg class="cv" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  open:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7"/><path d="M7 7h10v10"/></svg>',
  edit:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  grip:'<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>',
  copy:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  empty:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/></svg>',
};

function cardHTML(c){
  // headline = 手动改名 > App对话名 > 首句;可点击改名(尤其 Codex 长prompt)
  const title = c.title_ov || c.title_app || c.task || "";
  const goalHTML = title ? esc(title) : `<span class="ph">未命名会话</span>`;
  // 目的 line is ALWAYS present; click swaps in an inline <input> (no browser prompt)
  const noteLine = `<div class="note-line" data-note="1" title="点击填写/编辑目的">`
    + `<span class="nlab">目的</span>`
    + (c.note ? `<span class="ntext">${esc(c.note)}</span>` : `<span class="ntext ph">点击填写</span>`)
    + `</div>`;
  const lab = ACT_LAB[c.status] || "";
  const actLine = c.activity
    ? `<div class="act-line"><span class="lab">${lab}</span>${esc(c.activity)}</div>` : "";

  const parts=[];
  const pcl=c.priority?c.priority.toLowerCase():"pnone";
  parts.push(`<span class="prio ${pcl}" data-prio="${esc(c.priority)}" title="点击切换优先级">${esc(c.priority||"P?")}</span>`);
  if(c.project) parts.push(`<span class="proj">${esc(c.project)}</span>`);
  if(c.engine==="codex") parts.push(`<span class="eng">Codex</span>`);
  if(c.branch)  parts.push(`<span class="br mono">${esc(c.branch)}</span>`);
  if(c.overridden) parts.push(`<span class="ov">手动</span>`);
  const metaLeft = parts.join('<span class="sep"></span>');
  const ago = c.ago ? `<span class="ago mono">${esc(c.ago)}</span>` : "";
  const meta = `<div class="meta">${metaLeft}<span class="spacer"></span>${ago}</div>`;

  // recent3 — collapsed; only rendered if there are >1 items (the first ≈ the goal)
  const r3 = (c.recent3||[]).filter(Boolean);
  let recent = "";
  if(r3.length){
    const rows = r3.map((t,i)=>`<div class="r"><span class="i mono">${i+1}</span><span class="x">${esc(t)}</span></div>`).join("");
    recent = `<button class="recent-tog" data-recent="1">${IC.chevron}最近 ${r3.length} 件</button>
      <div class="recent">${rows}</div>`;
  }

  const openR = OPEN_RECENT.has(c.id) ? " open-recent" : "";
  // drag only from the grip (whole-card draggable ate real-mouse clicks on goal/buttons);
  // open is a native <a href="claude://…"> for reliable OS hand-off to the local app.
  return `<div class="card ${c.status}${openR}" data-id="${esc(c.id)}">
    <div class="head">
      <span class="grip" draggable="true" data-drag="1" title="拖动换列" aria-hidden="true">${IC.grip}</span>
      <span class="sdot" aria-hidden="true"></span>
      <div class="body">
        <div class="goal" data-title="1" title="点击改名">${goalHTML}</div>
        ${noteLine}
        ${actLine}
        ${meta}
        ${recent}
        <div class="actions">
          <button class="act" data-copy="${esc(title)}">${IC.copy}<span class="cl">复制名字</span></button>
          <button class="act" data-note="1">${IC.edit}目的</button>
        </div>
      </div>
    </div>
  </div>`;
}

let CARDS=[], DRAGGING=false, EDITING=false, ENG_FILTER="";
document.getElementById("engtabs").addEventListener("click",e=>{
  const b=e.target.closest(".etab"); if(!b) return;
  ENG_FILTER=b.dataset.eng;
  document.querySelectorAll(".etab").forEach(x=>x.classList.toggle("on",x===b));
  render(CARDS);
});
const OPEN_RECENT=new Set();   // card ids with 最近3件 expanded — survives the 3s re-render

function render(cards){
  if(ENG_FILTER) cards=cards.filter(c=>c.engine===ENG_FILTER);   // 引擎 tab 过滤(tally 同步跟随)
  const wrap=document.getElementById("wrap");
  const tally=document.getElementById("tally");
  const n={waiting:0,running:0,idle:0};
  for(const c of cards) if(c.status in n) n[c.status]++;

  tally.innerHTML =
    `<span class="stat wait ${n.waiting?"":"zero"}"><span class="dot"></span>等你 <b>${n.waiting}</b></span>`+
    `<span class="stat run ${n.running?"":"zero"}"><span class="dot"></span>跑着 <b>${n.running}</b></span>`+
    `<span class="stat idle ${n.idle?"":"zero"}"><span class="dot"></span>搁置 <b>${n.idle}</b></span>`;

  if(!cards.length){
    wrap.innerHTML=`<div class="empty">
      ${IC.empty}
      <div class="l1">眼下没有在飞的会话</div>
      <div class="l2">去 Claude 里甩个任务，几秒后它会出现在这里。安心走开，回来一眼就知道谁在等你。</div>
    </div>`;
    return;
  }
  let html="";
  for(const [key,label] of GROUPS){
    const g=cards.filter(c=>c.status===key);
    // always emit the section (empty hidden until a drag) so you can drop into an empty column
    html+=`<section class="sect ${key} ${g.length?"":"sect-empty"}" data-drop="${key}">
      <div class="sect-h"><span class="dot"></span><span class="t">${label}</span>`+
      `<span class="n">${g.length}</span><span class="rule"></span></div>`+
      `<div class="list">${g.map(cardHTML).join("") || `<div class="drop-hint">拖到这里 → ${label}</div>`}</div></section>`;
  }
  wrap.innerHTML=html;
}

let LAST_TRIAGE=0;   // 最近一次打优先级的时刻;筛选期(6s内)不重排,免得刚点P0卡就跳走
async function tick(force){
  const triaging = Date.now()-LAST_TRIAGE < 6000;
  if(!force && (DRAGGING||EDITING||triaging)) return;   // don't yank the DOM mid-interaction
  const live=document.getElementById("live"), lt=document.getElementById("live-t");
  try{
    const r=await fetch("/api/sessions",{cache:"no-store"});
    const {cards}=await r.json();
    CARDS=cards||[];
    if(!DRAGGING&&!EDITING&&!(Date.now()-LAST_TRIAGE<6000)) render(CARDS);
    live.classList.remove("stale");
    lt.textContent="已更新 "+new Date().toTimeString().slice(0,8);
  }catch(e){
    live.classList.add("stale");
    lt.textContent="连接断开，重试中";
  }
}

async function post(url,body){
  return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
}

function copyText(t){
  try{ if(navigator.clipboard && window.isSecureContext){ navigator.clipboard.writeText(t); return; } }catch(e){}
  const ta=document.createElement("textarea");   // fallback for http/LAN (insecure context)
  ta.value=t; ta.style.position="fixed"; ta.style.opacity="0";
  document.body.appendChild(ta); ta.select();
  try{ document.execCommand("copy"); }catch(e){}
  document.body.removeChild(ta);
}
function flash(btn,msg){
  const s=btn.querySelector(".cl"); if(!s) return;
  const old=s.textContent; s.textContent=msg;
  setTimeout(()=>{ if(s.isConnected) s.textContent=old; },1400);
}

// inline note editing — an <input> INSIDE the card (no browser prompt dialog)
function openNoteInput(card){
  const id=card.dataset.id, c=CARDS.find(x=>x.id===id); if(!c) return;
  const line=card.querySelector(".note-line"); if(!line || line.querySelector("input")) return;
  closeAnyNoteInput();                     // one editor at a time
  EDITING=true;
  const cur=c.note||"";
  line.innerHTML=`<span class="nlab">目的</span>`;
  const inp=document.createElement("input");
  inp.className="note-input"; inp.type="text"; inp.value=cur;
  inp.placeholder="这个对话最高优先级的目的（回车保存 · Esc 取消 · 清空=删除）";
  inp.maxLength=200;
  line.appendChild(inp); inp.focus(); inp.select();
  let done=false;
  const finish=(save)=>{
    if(done) return; done=true; EDITING=false;
    if(save && inp.value.trim()!==cur){
      post("/api/note",{id,note:inp.value.trim()}).then(()=>tick(true));
    }else{ tick(true); }                    // re-render restores the display line
  };
  inp.addEventListener("keydown",e=>{
    if(e.isComposing||e.keyCode===229) return;   // 中文输入法选词回车 ≠ 提交
    if(e.key==="Enter") finish(true);
    else if(e.key==="Escape") finish(false);
  });
  inp.addEventListener("blur",()=>finish(true));
}
function closeAnyNoteInput(){
  const old=document.querySelector(".note-input");
  if(old) old.blur();                      // triggers its own finish(save)
}

// event delegation on #wrap (survives re-render)
(function bind(){
  const wrap=document.getElementById("wrap");
  wrap.addEventListener("dragstart",e=>{
    const h=e.target.closest("[data-drag]"); if(!h) return;   // only the grip drags
    const card=h.closest(".card"); if(!card) return;
    DRAGGING=true; document.body.classList.add("dragging"); card.classList.add("dragging");
    e.dataTransfer.setData("text/plain",card.dataset.id); e.dataTransfer.effectAllowed="move";
  });
  wrap.addEventListener("dragend",()=>{
    DRAGGING=false; document.body.classList.remove("dragging");
    wrap.querySelectorAll(".dragging,.drop-ok").forEach(x=>x.classList.remove("dragging","drop-ok"));
  });
  wrap.addEventListener("dragover",e=>{
    const sect=e.target.closest(".sect"); if(!sect) return;
    e.preventDefault(); e.dataTransfer.dropEffect="move";
    wrap.querySelectorAll(".drop-ok").forEach(x=>{if(x!==sect)x.classList.remove("drop-ok")});
    sect.classList.add("drop-ok");
  });
  wrap.addEventListener("drop",async e=>{
    const sect=e.target.closest(".sect"); if(!sect) return; e.preventDefault();
    const id=e.dataTransfer.getData("text/plain"), status=sect.dataset.drop;
    sect.classList.remove("drop-ok");
    const c=CARDS.find(x=>x.id===id);
    if(id&&status&&c&&c.status!==status){ await post("/api/override",{id,status}); }
    tick(true);
  });
  wrap.addEventListener("click",e=>{
    const pr=e.target.closest(".prio");
    if(pr){e.stopPropagation();
      const cyc={"":"P0","P0":"P1","P1":"P2","P2":""};
      const np=cyc[pr.dataset.prio||""];
      const id=pr.closest(".card").dataset.id;
      LAST_TRIAGE=Date.now();                       // 冻结重排6s,连打多张不跳
      pr.dataset.prio=np;                            // 原地更新 pill,不重排(卡不跳走)
      pr.textContent=np||"P?";
      pr.className="prio "+(np?np.toLowerCase():"pnone");
      const c=CARDS.find(x=>x.id===id); if(c) c.priority=np;
      post("/api/priority",{id,priority:np});
      return}
    const ti=e.target.closest("[data-title]");
    if(ti && !ti.querySelector("input")){          // 点标题→内联改名
      e.stopPropagation(); EDITING=true;
      const card=ti.closest(".card"), id=card.dataset.id;
      const old=ti.textContent.trim()==="未命名会话"?"":ti.textContent.trim();
      const inp=document.createElement("input"); inp.className="title-input"; inp.value=old;
      inp.placeholder="给这个会话起个名(回车存·Esc取消·清空=恢复原名)";
      ti.innerHTML=""; ti.appendChild(inp); inp.focus(); inp.select();
      let done=false;
      const fin=(save)=>{ if(done)return; done=true; EDITING=false;
        if(save) post("/api/title",{id,title:inp.value.trim()}).then(()=>tick(true));
        else tick(true); };
      inp.addEventListener("keydown",ev=>{ ev.stopPropagation();
        if(ev.isComposing||ev.keyCode===229)return;
        if(ev.key==="Enter")fin(true); if(ev.key==="Escape")fin(false); });
      inp.addEventListener("blur",()=>fin(true));
      return}
    const cp=e.target.closest("[data-copy]");
    if(cp){ e.stopPropagation(); copyText(cp.dataset.copy||""); flash(cp,"已复制,去App搜索粘贴"); return; }
    const tog=e.target.closest("[data-recent]");
    if(tog){ e.stopPropagation();
      const card=tog.closest(".card"), id=card.dataset.id;
      card.classList.toggle("open-recent");
      if(card.classList.contains("open-recent")) OPEN_RECENT.add(id); else OPEN_RECENT.delete(id);
      return; }
    if(e.target.closest(".note-input")) { e.stopPropagation(); return; }  // typing, not a command
    const ed=e.target.closest("[data-note]");
    if(ed){ e.stopPropagation(); openNoteInput(ed.closest(".card")); }
  });
})();

tick(); setInterval(tick,3000);
</script></body></html>"""


# ══ v3 F12: 浮窗面板(NSPanel 内嵌) — 功能简版,待 DESIGN-v4 稿替换 ══════════════
PAGE_POPOVER = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>Butler</title><style>

/* ════════════════════════════════════════════════════════════
   Butler 浮窗面板 · 设计稿 v4(龙哥 2026-07-03)
   信息结构 = DESIGN-v3 方案B(等你3行 / 跑着2行 / 搁置折叠)
   视觉权重 = PRD F14:运动与饱和色只属于「等你」
   工程接线点全部用〔接线〕注释标出;token 与 server.py PAGE 同源。
   ds-allow-hardcode: ① .demo-stage/.demo-label 假壁纸色(预览脚手架,非产品UI)
   ② 系统字体栈字面量(本产品的字体 token 即系统栈) ③ 微间距 px
   (沿用 server.py PAGE 手调字面量惯例;色彩/动效一律走 var())。
   ════════════════════════════════════════════════════════════ */

/* ── tokens(与看板 PAGE 同源 + F14 新增,见 DESIGN-v4.md §3)── */
:root{
  --bg:#fbfbfa;
  --surface:#ffffff;
  --surface-2:#f5f5f4;
  --line:#e7e6e2;
  --line-2:#efeeea;
  --fg:#1a1a19;
  --fg-2:#57534e;
  --dim:#726d64;
  --faint:#8a857d;
  --accent:#b45309;
  --accent-soft:#fbf3e6;
  --focus:#2563eb;
  /* F14 新增 */
  --halo:rgba(180,83,9,.20);          /* 呼吸光晕色(等你专属) */
  --halo-ring:rgba(180,83,9,.40);     /* 新跳变脉冲环起始色 */
  --panel-shadow:0 18px 50px -12px rgba(28,25,20,.28), 0 2px 10px rgba(28,25,20,.10);
  --motion-breathe-dur:5600ms;        /* 呼吸周期:极缓 */
  --motion-breathe-ease:cubic-bezier(.45,.05,.55,.95); /* 近正弦,无顿点 */
  --motion-pulse-dur:2400ms;          /* 新跳变脉冲周期 */
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#161615;                      /* 浮窗底比看板 #0e0e0e 提半档,浮在暗桌面上才有"面"感 */
    --surface:#1d1d1c;
    --surface-2:#242423;
    --line:#31312e;
    --line-2:#292927;
    --fg:#eceae6;
    --fg-2:#a8a39b;
    --dim:#938e85;
    --faint:#7a756d;
    --accent:#e0a153;
    --accent-soft:#2a2013;
    --focus:#5b8bf0;
    --halo:rgba(224,161,83,.26);
    --halo-ring:rgba(224,161,83,.45);
    --panel-shadow:0 18px 50px -10px rgba(0,0,0,.6), 0 2px 10px rgba(0,0,0,.4);
  }
}

*{box-sizing:border-box}
html,body{margin:0}
/* 〔接线〕真实浮窗里 WKWebView 背景设透明(drawsBackground=NO),
   面板圆角与阴影全由 .panel 绘制;NSPanel 自身 hasShadow=NO、无边框。 */
body{
  background:transparent;
  color:var(--fg);
  font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  -webkit-user-select:none;user-select:none;
}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,"SF Mono",monospace;
  font-variant-numeric:tabular-nums}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}

/* ── 面板壳 ─────────────────────────────────────────────── */
.panel{
  width:360px;
  max-height:70vh;                 /* PRD F12:高度上限 70% 屏高 */
  display:flex;flex-direction:column;
  background:var(--bg);
  border:1px solid var(--line);
  border-radius:14px;
  box-shadow:var(--panel-shadow);
  overflow:hidden;
}

/* ── 头部:极薄,只报数 ──────────────────────────────────── */
.p-head{
  flex:none;display:flex;align-items:center;gap:8px;
  padding:11px 16px 10px;border-bottom:1px solid var(--line-2);
}
.p-head .glyph{font-size:13px;color:var(--fg-2);line-height:1}
.p-head .name{font-size:13px;font-weight:600;letter-spacing:-.01em}
.p-head .tally{margin-left:auto;display:flex;gap:12px;font-size:11.5px;color:var(--dim)}
.p-head .tally b{font-weight:600;color:var(--fg-2)}
.p-head .tally .wait b{color:var(--accent)}

/* ── 滚动区 ─────────────────────────────────────────────── */
.p-scroll{flex:1;overflow-y:auto;padding:12px 12px 4px;overscroll-behavior:contain}
.p-scroll::-webkit-scrollbar{width:10px}
.p-scroll::-webkit-scrollbar-thumb{background:var(--line);border:3px solid transparent;
  background-clip:content-box;border-radius:6px}

/* ── 分区头(◐ ● ○ 语言与看板一致)──────────────────────── */
.sect{margin-bottom:14px}
.sect-h{display:flex;align-items:center;gap:8px;margin:2px 4px 7px}
.sect-h .dot{width:7px;height:7px;border-radius:50%;flex:none}
.sect-h .t{font-size:11px;font-weight:600;letter-spacing:.05em;color:var(--fg-2)}
.sect-h .n{font-size:11px;color:var(--dim);font-weight:500}
.sect-h .rule{flex:1;height:1px;background:var(--line-2)}
.sect.wait .sect-h .dot{background:var(--accent)}
.sect.wait .sect-h .t{color:var(--accent)}
.sect.run  .sect-h .dot{background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}

/* ── 卡片(独立圆角卡,留 6px 呼吸间距让光晕有处可去)───── */
.card{
  position:relative;
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:10px;
  padding:10px 12px 10px 14px;
  margin-bottom:6px;
}
.card:last-child{margin-bottom:0}

/* ═══ F14 权重语言 ═══════════════════════════════════════ */
/* 等你卡:amber 左缘(3px,画在 ::before,不动盒模型) */
.card.waiting{border-color:color-mix(in srgb, var(--accent) 26%, var(--line))}
.card.waiting::before{
  content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:3px;
  background:var(--accent);border-radius:10px 0 0 10px;
}
/* 呼吸光晕:独立发光层,只动 opacity(合成器动画,不触发重排) */
.card.waiting::after{
  content:"";position:absolute;inset:-1px;border-radius:10px;pointer-events:none;
  box-shadow:0 0 18px -4px var(--halo), 0 1px 6px -2px var(--halo);
  animation:breathe var(--motion-breathe-dur) var(--motion-breathe-ease) infinite;
}
@keyframes breathe{0%,100%{opacity:.3}50%{opacity:1}}

/* 新跳变脉冲点:卡片状态点外扩一圈涟漪,被看过即消(JS 摘 .fresh) */
.sdot{width:7px;height:7px;border-radius:50%;flex:none;margin-top:5px;position:relative}
.card.waiting .sdot{background:var(--accent)}
.card.running .sdot{background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}
.card.fresh .sdot::after{
  content:"";position:absolute;inset:0;border-radius:50%;
  animation:pulse var(--motion-pulse-dur) cubic-bezier(.25,.6,.35,1) infinite;
}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 var(--halo-ring)}
  70%,100%{box-shadow:0 0 0 9px rgba(0,0,0,0)}
}
/* 铁律兜底:系统减动效时,一切静止,amber 边与点仍在 */
@media (prefers-reduced-motion: reduce){
  .card.waiting::after{animation:none;opacity:.55}
  .card.fresh .sdot::after{animation:none}
}

/* ── 卡片内部三行 ──────────────────────────────────────── */
.c-head{display:flex;align-items:flex-start;gap:9px}
.c-body{min-width:0;flex:1}
.c-title-row{display:flex;align-items:baseline;gap:8px;min-width:0}
.c-title{font-size:13px;font-weight:600;letter-spacing:-.005em;color:var(--fg);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.c-prio{flex:none;font-size:9.5px;font-weight:700;letter-spacing:.04em;border-radius:4px;
  padding:1px 5px;line-height:1.35;align-self:center}
.c-prio.p0{background:var(--fg);color:var(--bg)}
.c-prio.p1{border:1px solid var(--fg-2);color:var(--fg-2)}
.c-prio.p2{border:1px solid var(--line);color:var(--dim)}
.card.running .c-title{font-weight:500}
.c-ago{flex:none;font-size:11px;color:var(--dim)}
/* 复制名字:hover 才现的幽灵按钮 〔接线〕点击=复制会话名到剪贴板 */
.c-copy,.c-idle{flex:none;appearance:none;border:none;background:transparent;color:var(--dim);
  width:22px;height:22px;margin:-3px -6px -3px 0;border-radius:6px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .12s}
.card:hover .c-copy,.card:hover .c-idle,.c-copy:focus-visible,.c-idle:focus-visible{opacity:1}
.c-copy:hover,.c-idle:hover{color:var(--fg-2);background:var(--surface-2)}
.c-copy svg,.c-idle svg{width:13px;height:13px}
.c-copy.done{color:var(--accent);opacity:1}

/* ◦ 目的行(可内联编辑)〔接线〕复用看板 saveNote:提交 PATCH /api/note */
.c-note{display:flex;gap:7px;margin-top:3px;font-size:12.5px;line-height:1.45;
  color:var(--fg-2);cursor:text;border-radius:4px}
.c-note .pfx{color:var(--faint);flex:none}
.c-note .txt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.c-note:hover .txt{color:var(--fg)}
.c-note input{flex:1;min-width:0;font:inherit;color:var(--fg);background:transparent;
  border:none;border-bottom:1px solid var(--accent);padding:0 0 1px;outline:none}
/* ↳ 动态行 */
.c-act{display:flex;gap:7px;margin-top:2px;font-size:12.5px;line-height:1.45;color:var(--dim)}
.c-act .pfx{color:var(--faint);flex:none}
.c-act .txt{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.card.waiting .c-act .txt{color:var(--fg-2)}   /* 等你卡的"要我干嘛"提半档 */

/* ── 搁置区:折叠,近隐形 ───────────────────────────────── */
.idle-fold{margin:0 0 2px}
.idle-fold summary{
  list-style:none;display:flex;align-items:center;gap:8px;cursor:pointer;
  padding:5px 4px;border-radius:6px;color:var(--dim);font-size:11.5px;font-weight:500;
}
.idle-fold summary::-webkit-details-marker{display:none}
.idle-fold summary:hover{color:var(--fg-2);background:var(--surface-2)}
.idle-fold summary .dot{width:7px;height:7px;border-radius:50%;flex:none;
  box-shadow:inset 0 0 0 1px var(--line)}
.idle-fold summary .chev{margin-left:auto;transition:transform .15s;font-size:9px}
.idle-fold[open] summary .chev{transform:rotate(90deg)}
.idle-list{padding:2px 4px 4px 19px}
.idle-row{display:flex;align-items:baseline;gap:8px;padding:3px 0;font-size:12px}
.idle-row .t{color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.idle-row .ago{flex:none;color:var(--dim);font-size:11px}

/* ── 底部操作区:两行,墨色系(amber 不下放到操作件)─────── */
.p-foot{flex:none;border-top:1px solid var(--line-2);background:var(--surface);
  padding:9px 14px 10px}
.f-row{display:flex;align-items:center;gap:14px}
.f-row + .f-row{margin-top:8px;padding-top:8px;border-top:1px solid var(--line-2)}
.f-toggle{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--fg-2);
  cursor:pointer;background:none;border:none;padding:0;font-family:inherit}
.f-toggle .sw{width:30px;height:18px;border-radius:9px;background:var(--line);
  position:relative;transition:background .15s;flex:none}
.f-toggle .sw::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;
  border-radius:50%;background:var(--surface);box-shadow:0 1px 2px rgba(0,0,0,.25);
  transition:transform .15s}
.f-toggle[aria-pressed="true"] .sw{background:var(--fg)}          /* 选中=墨色,非 amber */
.f-toggle[aria-pressed="true"] .sw::after{transform:translateX(12px)}
.f-toggle[aria-pressed="true"]{color:var(--fg)}
.f-link{appearance:none;border:none;background:none;padding:0;cursor:pointer;
  font:inherit;font-size:12.5px;color:var(--fg-2);display:flex;align-items:center;gap:5px}
.f-link:hover{color:var(--fg)}
.f-link .arr{font-size:11px;color:var(--faint)}
.f-quit{margin-left:auto;color:var(--dim);font-size:12px}
.f-quit:hover{color:var(--fg-2)}

/* 真实浮窗补充: body 即面板容器(WKWebView 透明),面板占满 */
body{padding:0}
.panel{width:100%;height:100vh;max-height:100vh}
.empty{color:var(--dim);text-align:center;padding:36px 0;font-size:12.5px}
</style></head>
<body>
<div class="panel" role="dialog" aria-label="Butler 在飞面板">
  <div class="p-head">
    <span class="glyph" aria-hidden="true">▦</span>
    <span class="name">Butler</span>
    <div class="tally mono" id="tally"></div>
  </div>
  <div class="p-scroll" id="scroll"><div class="empty">加载中</div></div>
  <div class="p-foot">
    <div class="f-row">
      <button class="f-toggle" id="tgMini" aria-pressed="false">
        <span class="sw" aria-hidden="true"></span>显示桌面看板</button>
      <button class="f-toggle" id="tgAuto" aria-pressed="false">
        <span class="sw" aria-hidden="true"></span>开机自启</button>
    </div>
    <div class="f-row">
      <button class="f-link" id="btnBoard">打开完整看板 <span class="arr" aria-hidden="true">↗</span></button>
      <button class="f-link f-quit" id="btnQuit">退出</button>
    </div>
  </div>
</div>
<script>
const IDLE='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2.5" y="6.5" width="11" height="6.5" rx="1"/><path d="M2.5 6.5l1.4-3h8.2l1.4 3M6 9.5h4"/></svg>';
const COPY='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5" y="5" width="8" height="8" rx="1.5"/><path d="M11 5V4a1.5 1.5 0 0 0-1.5-1.5h-5A1.5 1.5 0 0 0 3 4v5A1.5 1.5 0 0 0 4.5 10.5H5"/></svg>', CHECK='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3.5 8.5l3 3 6-7"/></svg>';
let EDITING=false, IDLE_OPEN=false;
const seen=new Set(JSON.parse(localStorage.getItem("butler_seen")||"[]"));

function esc(s){return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function tr(s,n){s=(s||"").replace(/\n/g," ").trim();return s.length>n?s.slice(0,n-1)+"…":s}
function ui(cmd,extra){fetch("/api/ui",{method:"POST",body:JSON.stringify(Object.assign({cmd:cmd},extra||{}))})}
function copyText(t){
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t);return}
  const ta=document.createElement("textarea");ta.value=t;ta.style.cssText="position:fixed;opacity:0";
  document.body.appendChild(ta);ta.select();try{document.execCommand("copy")}catch(e){}ta.remove();
}

function cardHTML(c, waiting){
  const eng=c.engine==="codex"?" · Codex":"";
  const title=tr((c.title_ov||c.title_app||c.task||"未命名会话"),waiting?24:26)+eng;
  const fresh=waiting&&!seen.has(c.id)?" fresh":"";
  const pr=c.priority?`<span class="c-prio ${c.priority.toLowerCase()}">${c.priority}</span>`:"";
  let h=`<article class="card ${waiting?"waiting":"running"}${fresh}" data-id="${esc(c.id)}" data-name="${esc(c.title_app||c.task||"")}">`+
    `<div class="c-head"><span class="sdot" aria-hidden="true"></span><div class="c-body">`+
    `<div class="c-title-row">${pr}<span class="c-title">${esc(title)}</span>`+
    `<span class="c-ago mono">${esc(c.ago||"")}</span>`+
    (waiting?`<button class="c-idle" title="搁置(先不管它)">${IDLE}</button>`:"")+
    `<button class="c-copy" title="复制会话名">${COPY}</button></div>`;
  if(waiting||c.note){
    const note=c.note?esc(tr(c.note,34)):`<span style="color:var(--faint)">点击填写目的</span>`;
    h+=`<div class="c-note" data-editable title="点击修改目的"><span class="pfx">◦</span><span class="txt">${note}</span></div>`;
  }
  if(c.activity)h+=`<div class="c-act"><span class="pfx">↳</span><span class="txt">${esc(tr(c.activity,36))}</span></div>`;
  return h+`</div></div></article>`;
}

function render(cards, st){
  if(EDITING)return;
  const w=cards.filter(c=>c.status==="waiting"),r=cards.filter(c=>c.status==="running"),
        i=cards.filter(c=>c.status==="idle");
  document.getElementById("tally").innerHTML=
    `<span class="wait">等你 <b>${w.length}</b></span><span>跑着 <b>${r.length}</b></span><span>搁置 <b>${i.length}</b></span>`;
  let h="";
  if(w.length){h+=`<section class="sect wait"><div class="sect-h"><span class="dot"></span>`+
    `<span class="t">等你</span><span class="n mono">${w.length}</span><span class="rule"></span></div>`;
    for(const c of w)h+=cardHTML(c,true); h+=`</section>`}
  if(r.length){h+=`<section class="sect run"><div class="sect-h"><span class="dot"></span>`+
    `<span class="t">跑着</span><span class="n mono">${r.length}</span><span class="rule"></span></div>`;
    for(const c of r)h+=cardHTML(c,false); h+=`</section>`}
  if(i.length){h+=`<details class="idle-fold"${IDLE_OPEN?" open":""}><summary><span class="dot"></span>搁置 `+
    `<span class="mono">${i.length}</span><span class="chev">▶</span></summary><div class="idle-list">`;
    for(const c of i)h+=`<div class="idle-row"><span class="t">${esc(tr(c.title_app||c.task,20))}</span>`+
      `<span class="ago mono">${esc(c.ago||"")}</span></div>`;
    h+=`</div></details>`}
  if(!h)h=`<div class="empty">全部安静 — 没有在飞的任务</div>`;
  document.getElementById("scroll").innerHTML=h;
  const fold=document.querySelector(".idle-fold");
  if(fold)fold.addEventListener("toggle",()=>{IDLE_OPEN=fold.open});
  document.getElementById("tgMini").setAttribute("aria-pressed",st.mini_on?"true":"false");
  document.getElementById("tgAuto").setAttribute("aria-pressed",st.autostart?"true":"false");
  // fresh 已读: 打开可见 2.5s 后记为 seen(脉冲此次可见,下次打开消失)
  setTimeout(()=>{w.forEach(c=>seen.add(c.id));
    localStorage.setItem("butler_seen",JSON.stringify([...seen]))},2500);
}

async function tick(){
  try{
    const [a,b]=await Promise.all([
      fetch("/api/sessions",{cache:"no-store"}),fetch("/api/uistate",{cache:"no-store"})]);
    render((await a.json()).cards, await b.json());
  }catch(e){}
}
tick();setInterval(tick,3000);

document.body.addEventListener("click",e=>{
  const idl=e.target.closest(".c-idle");
  if(idl){e.stopPropagation();
    const card=idl.closest(".card");
    card.style.opacity=".35";                     // 立即反馈,等 tick 收走
    fetch("/api/override",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({id:card.dataset.id,status:"idle"})}).then(tick);
    return}
  const cp=e.target.closest(".c-copy");
  if(cp){e.stopPropagation();
    copyText(cp.closest(".card").dataset.name);
    const old=cp.innerHTML;cp.innerHTML=CHECK;cp.classList.add("done");cp.style.color="var(--fg)";
    setTimeout(()=>{cp.innerHTML=old;cp.classList.remove("done");cp.style.color=""},900);return}
  const note=e.target.closest(".c-note[data-editable]");
  if(note&&!note.querySelector("input")){
    EDITING=true;
    const card=note.closest(".card"),txt=note.querySelector(".txt"),old=txt.textContent;
    const isPh=/点击填写/.test(old);
    const inp=document.createElement("input");inp.value=isPh?"":old;
    txt.replaceWith(inp);inp.focus();inp.select();
    let done=false;
    const commit=(save)=>{if(done)return;done=true;EDITING=false;
      if(save)fetch("/api/note",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({id:card.dataset.id,note:inp.value.trim()})}).then(tick);
      else tick()};
    inp.addEventListener("keydown",ev=>{ev.stopPropagation();
      if(ev.isComposing||ev.keyCode===229)return;
      if(ev.key==="Enter")commit(true);if(ev.key==="Escape")commit(false)});
    inp.addEventListener("blur",()=>commit(true));
    return}
});
document.getElementById("tgMini").addEventListener("click",()=>ui("mini"));
document.getElementById("tgAuto").addEventListener("click",()=>ui("autostart"));
document.getElementById("btnBoard").addEventListener("click",()=>ui("board"));
document.getElementById("btnQuit").addEventListener("click",()=>ui("quit"));
document.addEventListener("keydown",e=>{if(e.key==="Escape")ui("hidepop")});
</script></body></html>"""

# ══ v3 F13: mini 桌面看板 — 功能简版,待 DESIGN-v4 稿替换 ═══════════════════════
PAGE_MINI = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>Butler mini</title><style>

/* ════════════════════════════════════════════════════════════
   Butler Mini 桌面看板 · 设计稿 v4(龙哥 2026-07-03)
   常驻壁纸层的小卡:232px 宽,最多 4 行(头部 + 3 张等你摘要)。
   材质拍板:94% 不透明纸面,不做 CSS 假毛玻璃——
   WKWebView 的 backdrop-filter 采样不到壁纸,只会得到脏灰片。
   真毛玻璃 = 工程可选增强:NSPanel 里 NSVisualEffectView
   (material=.hudWindow, state=.active)垫在透明 WKWebView 下,
   届时把 --mini-bg 的 alpha 降到 .62 即可,其余 CSS 不动。
   全产品唯一会动的元素 = 头部 amber 点的呼吸(有等你时)。
   ds-allow-hardcode: ① .demo-stage/.demo-label 假壁纸色(预览脚手架,非产品UI)
   ② 系统字体栈字面量 ③ 微间距 px(沿用 server.py PAGE 惯例;色彩/动效走 var())。
   ════════════════════════════════════════════════════════════ */

/* ── tokens(同源 popover-mock / server.py PAGE)───────────── */
:root{
  --surface:#ffffff;
  --line:#e7e6e2;
  --line-2:#efeeea;
  --fg:#1a1a19;
  --fg-2:#57534e;
  --dim:#726d64;
  --faint:#8a857d;
  --accent:#b45309;
  --focus:#2563eb;
  --halo:rgba(180,83,9,.20);
  --mini-bg:rgba(251,251,250,.94);          /* 94% 纸面:壁纸微透但永不脏 */
  --mini-edge:rgba(255,255,255,.55);        /* 顶缘内高光,给"玻璃卡"一丝厚度 */
  --mini-shadow:0 10px 30px -10px rgba(28,25,20,.35), 0 1px 4px rgba(28,25,20,.18);
  --motion-breathe-dur:5600ms;
  --motion-breathe-ease:cubic-bezier(.45,.05,.55,.95);
}
@media (prefers-color-scheme: dark){
  :root{
    --surface:#1d1d1c;
    --line:#31312e;
    --line-2:#292927;
    --fg:#eceae6;
    --fg-2:#a8a39b;
    --dim:#938e85;
    --faint:#7a756d;
    --accent:#e0a153;
    --focus:#5b8bf0;
    --halo:rgba(224,161,83,.26);
    --mini-bg:rgba(24,24,23,.92);
    --mini-edge:rgba(255,255,255,.10);
    --mini-shadow:0 10px 30px -8px rgba(0,0,0,.65), 0 1px 4px rgba(0,0,0,.4);
  }
}

*{box-sizing:border-box}
html,body{margin:0}
/* 〔接线〕真实路由 /mini:body 透明(WKWebView drawsBackground=NO),
   NSPanel 无边框、hasShadow=NO(阴影由 CSS 画)、movableByWindowBackground=YES。 */
body{
  background:transparent;color:var(--fg);
  font:12.5px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;-webkit-user-select:none;user-select:none;
}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,"SF Mono",monospace;
  font-variant-numeric:tabular-nums}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}

/* ── mini 卡壳 ─────────────────────────────────────────── */
.mini{
  width:232px;
  background:var(--mini-bg);
  border:1px solid var(--line);
  border-radius:12px;
  box-shadow:var(--mini-shadow), inset 0 1px 0 var(--mini-edge);
  overflow:hidden;
  position:relative;
}

/* 头部 = 拖动区。〔接线〕整卡 movableByWindowBackground,行内交互元素会自然吃掉点击 */
.m-head{display:flex;align-items:center;gap:7px;padding:8px 10px 7px;cursor:default}
.m-head .glyph{font-size:12px;color:var(--accent);line-height:1}
.m-head .t{font-size:12px;font-weight:600;color:var(--accent);letter-spacing:.01em}
.m-head .n{font-size:12px;font-weight:600;color:var(--accent)}

/* 呼吸点:mini 上唯一会动的元素(有等你时)。光晕独立层,只动 opacity */
.m-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);
  flex:none;position:relative}
.m-dot::after{content:"";position:absolute;inset:-1px;border-radius:50%;
  box-shadow:0 0 8px 1px var(--halo);
  animation:breathe var(--motion-breathe-dur) var(--motion-breathe-ease) infinite}
@keyframes breathe{0%,100%{opacity:.3}50%{opacity:1}}
@media (prefers-reduced-motion: reduce){.m-dot::after{animation:none;opacity:.55}}

/* 图钉 / 关闭:hover 才现 */
.m-tools{margin-left:auto;display:flex;gap:2px;opacity:0;transition:opacity .15s}
.mini:hover .m-tools,.m-tools:focus-within{opacity:1}
.m-btn{appearance:none;border:none;background:transparent;color:var(--dim);
  width:20px;height:20px;border-radius:5px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;padding:0}
.m-btn:hover{color:var(--fg-2);background:var(--line-2)}
.m-btn svg{width:12px;height:12px}
/* 置顶态:图钉实心墨色(非 amber——层级是操作属性,不是等你语义) */
.m-btn.pin[aria-pressed="true"]{color:var(--fg)}
.m-btn.pin[aria-pressed="true"] svg .fill{fill:currentColor}

/* 等你行:名字 + ↳ 动态首句,单行省略;最多 3 行 */
.m-rows{padding:0 4px 4px}
.m-row{display:flex;align-items:baseline;gap:6px;min-width:0;
  padding:5px 6px 6px;border-top:1px solid var(--line-2);border-radius:7px;cursor:default}
.m-row:hover{background:var(--surface)}
.m-row .name{flex:none;max-width:46%;font-size:12px;font-weight:600;color:var(--fg);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.m-row .pfx{flex:none;color:var(--faint);font-size:11px}
.m-row .act{flex:1;min-width:0;font-size:11.5px;color:var(--dim);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 溢出行(等你 >3):最后补一行 “还有 N 件” */
.m-more{padding:4px 10px 7px;font-size:11px;color:var(--dim);
  border-top:1px solid var(--line-2)}

/* ── 极简态:无等你,整卡收成一行 ● N 在跑 ─────────────── */
.mini.quiet .q-row{display:flex;align-items:center;gap:7px;padding:7px 10px}
.mini.quiet .q-dot{width:7px;height:7px;border-radius:50%;flex:none;
  background:transparent;box-shadow:inset 0 0 0 1.5px var(--dim)}
.mini.quiet .q-t{font-size:12px;color:var(--dim)}
.mini.quiet .q-t b{font-weight:600;color:var(--fg-2)}

body{padding:0}
.mini{width:100%;min-height:40px}
</style></head>
<body>
<div class="mini" id="mini" role="status"></div>
<script>
const PIN='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path class="fill" d="M9.5 2.5l4 4-2.2.6-2 2L9 12l-2.4-2.4L3 13.2 2.8 13 6.4 9.4 4 7l2.9-.3 2-2z" fill="none"/></svg>', X='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
let TOP=false;
function esc(s){return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function tr(s,n){s=(s||"").replace(/\n/g," ").trim();return s.length>n?s.slice(0,n-1)+"…":s}
function ui(cmd,extra){fetch("/api/ui",{method:"POST",body:JSON.stringify(Object.assign({cmd:cmd},extra||{}))})}
function tools(){
  return `<div class="m-tools">`+
    `<button class="m-btn pin" aria-pressed="${TOP}" title="置顶显示">${PIN}</button>`+
    `<button class="m-btn close" title="隐藏桌面看板">${X}</button></div>`;
}
function render(cards){
  const w=cards.filter(c=>c.status==="waiting"),r=cards.filter(c=>c.status==="running");
  const m=document.getElementById("mini");
  if(w.length){
    m.className="mini";
    let h=`<div class="m-head"><span class="m-dot"></span><span class="t">等你</span>`+
      `<span class="n mono">${w.length}</span>${tools()}</div><div class="m-rows">`;
    for(const c of w.slice(0,3))
      h+=`<div class="m-row">${c.priority==="P0"?'<span style="font-size:9px;font-weight:700;background:var(--fg);color:var(--surface);border-radius:3px;padding:0 3px;margin-right:4px;flex:none">P0</span>':""}<span class="name">${esc(tr(c.title_ov||c.title_app||c.task,12))}</span>`+
         `<span class="pfx">↳</span><span class="act">${esc(tr(c.activity||c.note||"等你下一步",20))}</span></div>`;
    if(w.length>3)h+=`<div class="m-more">还有 ${w.length-3} 件等你 · 点菜单栏 ▦ 看全部</div>`;
    m.innerHTML=h+`</div>`;
  }else{
    m.className="mini quiet";
    m.innerHTML=`<div class="q-row"><span class="q-dot"></span>`+
      `<span class="q-t">${r.length?`<b class="mono">${r.length}</b> 在跑`:"全部安静"}</span>`+
      `<div style="margin-left:auto" class="m-tools-wrap">${tools()}</div></div>`;
  }
}
async function tick(){
  try{
    const [a,b]=await Promise.all([
      fetch("/api/sessions",{cache:"no-store"}),fetch("/api/uistate",{cache:"no-store"})]);
    TOP=(await b.json()).mini_top;
    render((await a.json()).cards);
  }catch(e){}
}
tick();setInterval(tick,4000);
document.body.addEventListener("click",e=>{
  if(e.target.closest(".pin")){TOP=!TOP;ui("minitop",{top:TOP});tick();return}
  if(e.target.closest(".close")){ui("mini");return}
});
</script></body></html>"""

def main():
    print(f"\n  Butler · 在飞看板 running")
    print(f"  桌面:  http://localhost:{PORT}")
    print(f"  手机(同 WiFi): http://<本机LAN-IP>:{PORT}\n")
    print(f"  数据源: {STORE}")
    print(f"  Ctrl+C 停止\n")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
