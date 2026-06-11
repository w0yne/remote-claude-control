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
import sys
import time
from collections import OrderedDict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from ccremote import config, feishu, signals, tmux, screenshot, registry

config.load_env()
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")

# Module state.
_client = None
pending_images = []  # image paths awaiting the next text message

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
    """Render `/projects`: one line per registered project with ★active marker
    and ●live/○dead status. Pure — liveness injected."""
    reg = registry.load(base_dir)
    if not reg:
        return "（无已注册项目）发送前请在电脑上 `cc-remote setup --name <别名>`。"
    active = registry.read_active(base_dir)
    lines = []
    for alias in sorted(reg):
        p = reg[alias]
        sess = p.get("session")
        star = "★" if sess == active else "  "
        dot = "●live" if session_exists(sess) else "○dead"
        lines.append(f"{star} {alias}  [{dot}]  session={sess}  dir={p.get('dir')}")
    return "项目列表（★=当前）：\n" + "\n".join(lines)


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
    pending_images.append(path)
    feishu.send_text(_client, chat_id,
                     f"📷 图片已接收 (共 {len(pending_images)} 张待处理),发文字时一起带给 Claude")


def handle_message(event: P2ImMessageReceiveV1) -> None:
    msg = event.event.message
    sender = event.event.sender
    sender_id = sender.sender_id.open_id if sender and sender.sender_id else None
    log.info(f"Message from open_id: {sender_id}")
    if config.ALLOWED_USERS and sender_id not in config.ALLOWED_USERS:
        log.warning(f"Unauthorized user: {sender_id} (not in ALLOWED_USERS)")
        return
    if msg.chat_type != "p2p":
        return

    chat_id = msg.chat_id
    message_id = msg.message_id

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
        feishu.send_text(_client, chat_id,
                         format_projects(config.CC_REMOTE_DIR, tmux.session_exists))
        return

    # Everything else routes to the currently-active session (active pointer,
    # falling back to TMUX_SESSION). Signals/screenshots are per-session.
    sess = registry.resolve_target(config.CC_REMOTE_DIR, config.TMUX_SESSION)
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

    if pending_images:
        payload = "\n".join(f"[图片] {p}" for p in pending_images) + "\n" + text
    else:
        payload = text

    # Reaction + signal BEFORE sending, so the signal exists before a trivial
    # turn could finish. On send failure, undo both.
    reaction_id = feishu.add_reaction(_client, message_id, config.REACTION_PROCESSING)
    sig = signals.write_signal(sig_dir, message_id, chat_id, reaction_id)
    if tmux.send_text(sess, payload):
        log.info(f"Sent to tmux[{sess}]: {text[:80]}{'...' if len(text) > 80 else ''}")
        pending_images.clear()
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
    log.info(f"Bridge started. Active tmux session: {target} (switch via /switch)")
    log.info("Waiting for messages from Feishu...")
    client.start()


if __name__ == "__main__":
    main()
