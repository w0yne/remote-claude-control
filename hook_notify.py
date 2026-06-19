#!/usr/bin/env python3
"""
Claude Code Stop hook — terminal screenshot + reaction status (single-machine).

On each finished Claude turn, for every pending remote command (one signal file
per command), this sends the turn's reply text + a screenshot of the tmux pane
ONCE PER CHAT and flips each triggering message's reaction. It acts only when
running inside the controlled tmux session (the gate), so a Claude in another
directory doesn't send on behalf of a session it isn't.

Thin entrypoint: Feishu/tmux/signal/screenshot/config mechanics live in the
ccremote package. Invoked by the harness, never blocks — any error exits 0.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ccremote import config, feishu, signals, tmux, screenshot

config.load_env()


def log(msg):
    print(f"[hook_notify] {msg}", file=sys.stderr)


def read_transcript_path():
    """Read the Stop hook's stdin JSON; return transcript_path or ""."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return ""
        return json.loads(raw).get("transcript_path", "") or ""
    except Exception as e:
        log(f"could not read hook stdin: {e}")
        return ""


def extract_last_assistant_text(transcript_path):
    """Full text of Claude's most recent assistant message that has prose — NO
    truncation (callers truncate per output channel). Skips trailing
    tool_use-only records. Returns "" when reply text is disabled
    (MAX_TEXT_CHARS<=0) or nothing is found."""
    if config.MAX_TEXT_CHARS <= 0 or not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log(f"could not read transcript: {e}")
        return ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        texts = [
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip()
        ]
        if not texts:
            continue
        return "\n".join(texts).strip()
    return ""


def _truncate(text, limit):
    """Truncate to `limit` chars, appending a 'see screenshot' notice when cut.
    limit<=0 means no truncation here (the reply-disabled switch is in
    extract_last_assistant_text)."""
    if limit > 0 and len(text) > limit:
        return text[:limit] + "\n…（已截断，完整内容见截图）"
    return text


def _reply_payloads(reply_text):
    """(card_md, text_fallback) for one reply, each truncated to its channel's
    ceiling: the card to MAX_CARD_CHARS, the plain-text fallback to
    MAX_TEXT_CHARS. Cards and text have different limits, so each is cut
    independently — the fallback must fit plain text even when the card holds
    more."""
    return (_truncate(reply_text, config.MAX_CARD_CHARS),
            _truncate(reply_text, config.MAX_TEXT_CHARS))


# Footer (status-line style): model · ctx% · git branch. Mirrors the Claude
# Code statusline so a remote reply shows the same at-a-glance state.
_MODEL_NAMES = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
    "fable": "Fable",
}


def _pretty_model(model_id):
    """'claude-opus-4-8' -> 'Opus 4.8'. Unknown shapes return the raw id so we
    never invent a name (don't guess — show what's there)."""
    if not model_id:
        return model_id
    parts = model_id.split("-")
    # find a known family token and the version tokens right after it
    for i, tok in enumerate(parts):
        if tok in _MODEL_NAMES:
            ver = []
            for v in parts[i + 1:]:
                if v.isdigit() and len(ver) < 2:  # major.minor only; skip date suffixes
                    ver.append(v)
                else:
                    break
            if ver:
                return f"{_MODEL_NAMES[tok]} {'.'.join(ver)}"
            return _MODEL_NAMES[tok]
    return model_id


def _fmt_tokens(n):
    """Mirror the statusline formatter: 1000000->'1M', 1234567->'1.2M',
    190095->'190K', 559->'0.6K'."""
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.0f}M" if v == int(v) else f"{v:.1f}M"
    if n >= 10_000 or n == 0:
        return f"{n / 1000:.0f}K"
    return f"{n / 1000:.1f}K"


def build_footer(meta):
    """Compose the footer string from a turn-meta dict. Each segment is included
    only when its data is present (missing data -> skip the segment, never error
    or show blanks). Segments joined by ' · ':
      🤖 <model> · ctx <pct>% (<used>/<size>) · ⎇ <branch>[*]
    Returns "" when nothing is available."""
    segs = []
    model = meta.get("model")
    if model:
        segs.append(f"🤖 {_pretty_model(model)}")
    ctx = meta.get("ctx_tokens")
    if ctx:
        size = config.CONTEXT_WINDOW_SIZE
        if size > 0:
            pct = round(ctx / size * 100)
            segs.append(f"ctx {pct}% ({_fmt_tokens(ctx)}/{_fmt_tokens(size)})")
    branch = meta.get("gitBranch")
    if branch:
        segs.append(f"⎇ {branch}{'*' if meta.get('dirty') else ''}")
    return " · ".join(segs)


def extract_turn_meta(transcript_path):
    """Read the last assistant record's model, gitBranch, and current context
    token count (input + cache_read + cache_creation — the instantaneous
    context size, matching the statusline's total_input_tokens). Best-effort:
    any problem -> {} so the footer is simply omitted."""
    if not transcript_path or not os.path.exists(transcript_path):
        return {}
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log(f"could not read transcript for meta: {e}")
        return {}
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        usage = msg.get("usage") or {}
        ctx = (usage.get("input_tokens", 0)
               + usage.get("cache_read_input_tokens", 0)
               + usage.get("cache_creation_input_tokens", 0))
        return {
            "model": msg.get("model"),
            "ctx_tokens": ctx,
            "gitBranch": obj.get("gitBranch"),
        }
    return {}


def resolve_session_dirs():
    """The (signal_dir, screenshot_dir) THIS hook owns — derived from the tmux
    session it's firing inside. Returns (None, None) if not in any tmux session.

    Multi-project isolation: each session's hook only ever touches its own
    sessions/<session>/ subtree, so a turn finishing in one project can't
    consume another project's signals or send its screenshot. This also
    replaces the old single-session gate (== TMUX_SESSION): a non-controlled
    session simply finds an empty signal dir and no-ops."""
    session = tmux.current_session()
    if not session:
        return (None, None)
    return (config.signal_dir(session), config.screenshot_dir(session))


def process_signals(client, signal_paths, image_path, reply_text):
    """Complete all pending commands for this turn. The reply (as a v2 markdown
    card, falling back to plain text) + screenshot are sent ONCE PER CHAT (not
    per signal — multiple messages can collapse into one turn), but each
    triggering message's reaction is flipped individually."""
    by_chat = {}
    for sp in signal_paths:
        sig = signals.read_signal(sp)
        if sig is None:
            log(f"bad/unreadable signal {os.path.basename(sp)}, removing")
            screenshot.safe_remove(sp)
            continue
        by_chat.setdefault(sig.get("chat_id"), []).append(
            (sig.get("message_id"), sig.get("reaction_id"), sp)
        )
    card_md, text_fallback = _reply_payloads(reply_text)
    for chat_id, items in by_chat.items():
        if reply_text:
            feishu.send_markdown(client, chat_id, card_md, text_fallback)
        sent = bool(image_path) and feishu.send_image(client, chat_id, image_path)
        if not sent:
            feishu.send_text(client, chat_id, "⚠️ 命令已执行，但截图生成/发送失败")
        for message_id, reaction_id, sp in items:
            feishu.del_reaction(client, message_id, reaction_id)
            feishu.add_reaction(client, message_id,
                                config.REACTION_DONE if sent else config.REACTION_ERROR)
            screenshot.safe_remove(sp)


def main():
    # Which session are we firing in? That decides which signals we own. Not in
    # tmux → own nothing → no-op (the gate, now via physical dir isolation).
    session = tmux.current_session()
    if not session:
        return
    sig_dir = config.signal_dir(session)
    shot_dir = config.screenshot_dir(session)

    # List + stale-drop this session's OWN signals (read-only, safe for any
    # turn so an idle session can't let its stale signals pile up).
    pending = signals.list_signals(sig_dir)
    if not pending:
        return
    fresh = []
    for sp in pending:
        if signals.is_stale(sp, config.SIGNAL_TTL_SEC):
            log(f"dropping stale signal: {os.path.basename(sp)}")
            screenshot.safe_remove(sp)
        else:
            fresh.append(sp)
    if not fresh:
        return

    if not config.APP_ID or not config.APP_SECRET:
        log("missing Feishu credentials; dropping signals")
        for sp in fresh:
            screenshot.safe_remove(sp)
        return

    client = feishu.build_client(config.APP_ID, config.APP_SECRET)
    reply_text = extract_last_assistant_text(read_transcript_path())
    image_path = None
    try:
        image_path = screenshot.render(session, shot_dir,
                                       config.CAPTURE_LINES, config.WEBP_QUALITY)
    except Exception as e:
        log(f"screenshot render failed: {e}")
    process_signals(client, fresh, image_path, reply_text)
    screenshot.prune_dir(shot_dir, config.KEEP_SCREENSHOTS)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"unexpected error: {e}")
    sys.exit(0)
