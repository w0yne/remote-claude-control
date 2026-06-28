#!/usr/bin/env python3
"""
Feishu → Claude Code bridge (single-machine).

Receives Feishu messages over the lark WebSocket and forwards them to a tmux
session running Claude Code. Slash commands (/read /status /enter /esc /up
/down /ctrl-c) and image messages are handled here; plain text is typed into
the pane. A per-command signal file lets the Stop hook screenshot the result.

This is a thin entrypoint: Feishu/tmux/signal/screenshot mechanics live in the
ccremote package; this file is the WS loop, dedup, and command routing.
"""

import json
import logging
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from ccremote import bindings, chat_pointer, config, feishu, registry, screenshot, signals, tmux, watchdog

config.load_env()
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")

# Module state.
_client = None
# Image paths awaiting the next text message, keyed by chat_id so an image sent
# in one chat is never forwarded with another chat's text (group isolation).
pending_images = {}

# At-least-once WS redelivery dedup (see already_handled).
_seen_messages = OrderedDict()
SEEN_MAX = 1000


def already_handled(message_id):
    """True if this message_id was already processed (a Feishu redelivery).
    The WS handler runs synchronously on one event loop, so calls are
    serialized — no lock needed."""
    if not message_id:
        return False
    now = time.time()
    while _seen_messages:
        _, ts = next(iter(_seen_messages.items()))
        if now - ts > config.SEEN_TTL_SEC or len(_seen_messages) > SEEN_MAX:
            _seen_messages.popitem(last=False)
        else:
            break
    if message_id in _seen_messages:
        return True
    _seen_messages[message_id] = now
    return False


CONTROL_KEYS = {"/enter": "Enter", "/esc": "Escape", "/up": "Up",
                "/down": "Down", "/ctrl-c": "C-c"}


def do_switch(base_dir, alias, session_exists):
    """Decide what `/switch <alias>` means. Pure (no tmux/Feishu) — liveness is
    injected via session_exists(name)->bool. Returns (ok, reply, session):
      - unknown alias        → (False, "<aliases…>", None)
      - known but dead       → (False, "go setup", session)  [Phase A: no revive]
      - known and alive      → (True, "switched", session)   [active pointer set]
    """
    proj = registry.get(base_dir, alias)
    if proj is None:
        known = ", ".join(sorted(registry.load(base_dir).keys())) or "(无)"
        return (False, f"⚠️ 未知项目 '{alias}'。已注册：{known}", None)
    session = proj.get("session")
    if not session_exists(session):
        return (False,
                f"⚠️ 项目 '{alias}' 的 tmux session '{session}' 不在。"
                f"请在电脑上 `cc-remote setup`（目录 {proj.get('dir')}）后再切。",
                session)
    registry.write_active(base_dir, session)
    return (True, f"✅ 已切到 '{alias}'（session {session}，目录 {proj.get('dir')}）", session)


def format_projects(base_dir, session_exists):
    """Render `/projects`: one line per registered project with ★active marker,
    ●live/○dead status, and 🔗 if some chat is bound to it. Pure — liveness
    injected; active pointer and bindings read from base_dir."""
    reg = registry.load(base_dir)
    if not reg:
        return "（无已注册项目）发送前请在电脑上 `cc-remote setup --name <别名>`。"
    active = registry.read_active(base_dir)
    bound = set(bindings.load(base_dir).values())
    lines = []
    for alias in sorted(reg):
        p = reg[alias]
        sess = p.get("session")
        star = "★" if sess == active else "  "
        dot = "●live" if session_exists(sess) else "○dead"
        link = "🔗群" if alias in bound else "   "
        lines.append(f"{star} {alias}  [{dot}] {link}  session={sess}  dir={p.get('dir')}")
    return "项目列表（★=当前，🔗=已绑群）：\n" + "\n".join(lines)


def do_bind(base_dir, chat_id, alias, rename):
    """Decide what `/bind <alias>` (sent in a chat) means. Pure except for the
    injected rename(chat_id, name) -> (ok, err) side effect (the Feishu group
    rename), so it's testable with a fake rename. Returns (ok, reply):
      - unknown alias → (False, "<known aliases…>")   [nothing written]
      - known alias   → (True, "bound + rename note")  [binding written]
    A rename failure NEVER fails the bind — it's appended as a ⚠️ note, so a
    missing im:chat scope degrades gracefully to 'name it yourself'."""
    proj = registry.get(base_dir, alias)
    if proj is None:
        known = ", ".join(sorted(registry.load(base_dir).keys())) or "(无)"
        return (False, f"⚠️ 未知项目 '{alias}'。已注册：{known}")
    bindings.bind(base_dir, chat_id, alias)
    ok, err = rename(chat_id, f"🤖 {alias}")
    note = "" if ok else f"\n⚠️ 自动改名失败（{err}），群名请手动改。"
    return (True,
            f"✅ 本群已绑定 '{alias}'（session {proj.get('session')}，"
            f"目录 {proj.get('dir')}）。{note}")


def do_unbind(base_dir, chat_id):
    """Decide what `/unbind` (sent in a chat) means. Pure. Returns (ok, reply)."""
    alias = bindings.read_binding(base_dir, chat_id)
    if alias is None:
        return (False, "⚠️ 本群未绑定任何项目。")
    bindings.unbind(base_dir, chat_id)
    return (True, f"✅ 已解绑 '{alias}'。本群消息改走默认路由（active 指针）。")


def do_whoami(base_dir, chat_id):
    """Report this chat's binding (for `/whoami`). Pure. Returns a reply string."""
    alias = bindings.read_binding(base_dir, chat_id)
    if alias is None:
        return "本群未绑定项目；消息走默认路由（active 指针 / 默认 session）。"
    proj = registry.get(base_dir, alias)
    if proj is None:
        return (f"本群绑定 '{alias}'，但该项目已不在注册表中。"
                f"请 /unbind，或在电脑上 cc-remote setup --name {alias}。")
    return (f"本群绑定 '{alias}'（session {proj.get('session')}，"
            f"目录 {proj.get('dir')}）。")


# Only LEADING mention tokens — Feishu injects @-placeholders at the very start
# of the text when the bot is @'d. Anchoring to ^ means a placeholder-looking
# substring later in the message (an email, a path, code) is left untouched.
_MENTION_RE = re.compile(r"^(?:@_(?:user_\d+|all)\s*)+")


def strip_mentions(text):
    """Strip leading Feishu @-mention placeholder tokens (@_user_1 … / @_all)
    that the platform prepends to a group message's text when the bot is @'d, so
    a command typed as '@bot /bind web' still parses as '/bind web'. Only leading
    tokens are removed — a literal '@_user_1' mid-text (in an email, path, or
    code) is preserved. Plain text is returned unchanged (modulo trim)."""
    return _MENTION_RE.sub("", text).strip()


def resolve_session(base_dir, chat_id, default):
    """The tmux session a message in `chat_id` routes to. A chat bound to a
    project → that project's session; an unbound chat (a DM, or an unbound
    group) → the active pointer or `default` (the legacy single-DM path,
    untouched). A binding pointing at a since-removed project also falls back.
    Pure; never raises — routing must not depend on bindings/registry integrity."""
    alias = bindings.read_binding(base_dir, chat_id)
    if alias:
        proj = registry.get(base_dir, alias)
        if proj and proj.get("session"):
            return proj["session"]
    return registry.resolve_target(base_dir, default)


def write_pointer_for(base_dir, session, chat_id):
    """Record chat_id as the most recent driver of `session` (for notify).
    Best-effort: a failure only logs, never affects routing."""
    if not chat_pointer.write(base_dir, session, chat_id):
        log.warning(f"chat pointer write failed for session {session}")


def _send_screenshot(chat_id, session):
    """Render `session`'s pane and send it (for /read). True on confirmed send.
    Screenshots go to that session's own per-session dir."""
    shot_dir = config.screenshot_dir(session)
    try:
        img = screenshot.render(session, shot_dir,
                                config.CAPTURE_LINES, config.WEBP_QUALITY)
    except Exception as e:
        log.error(f"screenshot render failed: {e}")
        return False
    try:
        return feishu.send_image(_client, chat_id, img)
    finally:
        screenshot.prune_dir(shot_dir, config.KEEP_SCREENSHOTS)


def _handle_image(msg, chat_id):
    try:
        image_key = json.loads(msg.content).get("image_key", "")
    except (json.JSONDecodeError, AttributeError):
        log.error("Failed to parse image content")
        feishu.send_text(_client, chat_id, "⚠️ 图片解析失败")
        return
    os.makedirs(config.IMAGE_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(config.IMAGE_DIR, f"{ts}_{image_key[:8]}.png")
    path = feishu.download_image(_client, msg.message_id, image_key, dest)
    if not path:
        feishu.send_text(_client, chat_id, "⚠️ 图片下载失败")
        return
    queue = pending_images.setdefault(chat_id, [])
    queue.append(path)
    feishu.send_text(_client, chat_id,
                     f"📷 图片已接收 (共 {len(queue)} 张待处理),发文字时一起带给 Claude")


def handle_message(event: P2ImMessageReceiveV1) -> None:
    msg = event.event.message
    sender = event.event.sender
    sender_id = sender.sender_id.open_id if sender and sender.sender_id else None
    log.info(f"Message from open_id: {sender_id}")
    if config.ALLOWED_USERS and sender_id not in config.ALLOWED_USERS:
        log.warning(f"Unauthorized user: {sender_id} (not in ALLOWED_USERS)")
        return

    chat_id = msg.chat_id
    message_id = msg.message_id
    is_dm = msg.chat_type == "p2p"

    # Drop Feishu redeliveries (at-least-once WS) before any side effect.
    if already_handled(message_id):
        log.info(f"Duplicate message {message_id} ignored (Feishu redelivery)")
        return

    if msg.message_type == "image":
        _handle_image(msg, chat_id)
        return
    if msg.message_type != "text":
        return

    try:
        text = json.loads(msg.content).get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return
    # DMs never carry @-mention placeholders, so leave DM text byte-for-byte as
    # before (the legacy single-DM path). Only group text gets mention-stripped,
    # so '@bot /bind web' in a group parses as '/bind web'.
    if not is_dm:
        text = strip_mentions(text)
    if not text or text.startswith("#"):
        return

    # Multi-project commands (don't depend on a routing target).
    if text.startswith("/switch"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            feishu.send_text(_client, chat_id,
                             "用法：/switch <项目别名>。/projects 查看可用项目。")
            return
        _ok, reply, _session = do_switch(config.CC_REMOTE_DIR, parts[1].strip(),
                                         tmux.session_exists)
        feishu.send_text(_client, chat_id, reply)
        return

    if text == "/projects":
        listing = format_projects(config.CC_REMOTE_DIR, tmux.session_exists)
        feishu.send_markdown(_client, chat_id, listing, listing,
                             header_title="项目列表")
        return

    # Group-binding commands. Exact first-token match (not startswith) so a
    # message like '/binding-web' or '/bind these functions' isn't hijacked, and
    # gated to non-DM chats so a DM's /switch + active pointer stay untouched
    # (binding a DM would silently pin it). parts[0] is the command word.
    parts = text.split()
    cmd = parts[0] if parts else ""

    if cmd == "/bind" and not is_dm:
        if len(parts) < 2:
            feishu.send_text(_client, chat_id,
                             "用法：/bind <项目别名>。在该项目对应的群里发送。")
            return
        rename = lambda cid, name: feishu.update_chat_name(_client, cid, name)
        _ok, reply = do_bind(config.CC_REMOTE_DIR, chat_id, parts[1], rename)
        feishu.send_text(_client, chat_id, reply)
        return

    if cmd == "/unbind" and not is_dm:
        _ok, reply = do_unbind(config.CC_REMOTE_DIR, chat_id)
        feishu.send_text(_client, chat_id, reply)
        return

    if cmd == "/whoami" and not is_dm:
        feishu.send_text(_client, chat_id, do_whoami(config.CC_REMOTE_DIR, chat_id))
        return

    # Everything else routes to the chat's bound project, or — for a DM / unbound
    # chat — the currently-active session (active pointer, falling back to
    # TMUX_SESSION). Signals/screenshots are per-session.
    sess = resolve_session(config.CC_REMOTE_DIR, chat_id, config.TMUX_SESSION)
    write_pointer_for(config.CC_REMOTE_DIR, sess, chat_id)
    sig_dir = config.signal_dir(sess)

    if text == "/status":
        ok = tmux.session_exists(sess)
        active = registry.read_active(config.CC_REMOTE_DIR)
        feishu.send_text(_client, chat_id,
                         f"{'✅' if ok else '⚠️'} 当前项目 session '{sess}'"
                         f"{'（active 指针）' if active else '（默认）'} "
                         f"{'在线' if ok else '不在 —— 请 cc-remote setup'}")
        return

    if text == "/read":
        if not tmux.session_exists(sess):
            feishu.send_text(_client, chat_id, f"⚠️ tmux session '{sess}' not found")
        elif not _send_screenshot(chat_id, sess):
            feishu.send_text(_client, chat_id, "⚠️ 截图失败")
        return

    if text in CONTROL_KEYS:
        key = CONTROL_KEYS[text]
        if not tmux.session_exists(sess):
            feishu.send_text(_client, chat_id, f"⚠️ tmux session '{sess}' not found")
            return
        if not tmux.send_key(sess, key):
            feishu.send_text(_client, chat_id, f"⚠️ 按键发送失败: {key}")
            return
        # Only attach a fresh signal if nothing is already awaiting one.
        if signals.has_pending(sig_dir):
            feishu.send_text(_client, chat_id, f"⌨️ 已发送按键: {key}")
        else:
            reaction_id = feishu.add_reaction(_client, message_id, config.REACTION_PROCESSING)
            signals.write_signal(sig_dir, message_id, chat_id, reaction_id)
        return

    if not tmux.session_exists(sess):
        feishu.send_text(_client, chat_id, f"⚠️ tmux session '{sess}' not found. Start it first.")
        return

    queued = pending_images.get(chat_id, [])
    if queued:
        payload = "\n".join(f"[图片] {p}" for p in queued) + "\n" + text
    else:
        payload = text

    # Reaction + signal BEFORE sending, so the signal exists before a trivial
    # turn could finish. On send failure, undo both.
    reaction_id = feishu.add_reaction(_client, message_id, config.REACTION_PROCESSING)
    sig = signals.write_signal(sig_dir, message_id, chat_id, reaction_id)
    if tmux.send_text(sess, payload):
        log.info(f"Sent to tmux[{sess}]: {text[:80]}{'...' if len(text) > 80 else ''}")
        pending_images.pop(chat_id, None)
    else:
        if sig:
            try:
                os.remove(sig)
            except OSError:
                pass
        feishu.del_reaction(_client, message_id, reaction_id)
        feishu.send_text(_client, chat_id, "⚠️ 发送失败")


def main():
    global _client
    if not config.APP_ID or not config.APP_SECRET:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set in .env")
        sys.exit(1)
    _client = feishu.build_client(config.APP_ID, config.APP_SECRET)
    config.ensure_dirs()
    log.info(f"Working dir: {config.CC_REMOTE_DIR} (multi-project: sessions/<s>/)")
    target = registry.resolve_target(config.CC_REMOTE_DIR, config.TMUX_SESSION)
    if not tmux.session_exists(target):
        log.warning(f"active tmux session '{target}' not found. "
                    f"Start it with: tmux new-session -s {target}  (or /switch)")
    handler = (lark.EventDispatcherHandler.builder("", "")
               .register_p2_im_message_receive_v1(handle_message).build())
    client = lark.ws.Client(
        config.APP_ID, config.APP_SECRET, event_handler=handler,
        log_level=lark.LogLevel.INFO if config.LOG_LEVEL == "DEBUG" else lark.LogLevel.WARNING,
    )
    # WS-liveness watchdog: lark's own reconnect sometimes never recovers after a
    # network switch (the link dies, the process lives on, messages stop). We
    # track liveness via lark's public on_reconnecting/on_reconnected hooks (no
    # SDK changes) and let a watchdog thread exit so launchd relaunches with a
    # fresh connection — but only once the link has been down past the threshold
    # AND Feishu is reachable again (never restart into a still-dead network).
    # WATCHDOG_DOWN_THRESHOLD_SEC=0 disables it entirely.
    if config.WATCHDOG_DOWN_THRESHOLD_SEC > 0:
        wd_state = watchdog.WatchdogState()
        client.on_reconnecting = lambda: wd_state.mark_disconnected(time.time())
        client.on_reconnected = wd_state.mark_connected
        watchdog.start_thread(wd_state, config.WATCHDOG_DOWN_THRESHOLD_SEC,
                              config.WATCHDOG_INTERVAL_SEC)
        log.info(f"WS watchdog on (threshold {config.WATCHDOG_DOWN_THRESHOLD_SEC}s, "
                 f"interval {config.WATCHDOG_INTERVAL_SEC}s)")
    log.info(f"Bridge started. Active tmux session: {target} (switch via /switch)")
    log.info("Waiting for messages from Feishu...")
    client.start()


if __name__ == "__main__":
    main()
