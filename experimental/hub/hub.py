#!/usr/bin/env python3
"""
Bridge Hub - Central relay that receives Feishu messages
and forwards them to the active remote agent.

Runs on any always-on machine (one of the Macs, a VPS, etc.)
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
from typing import Optional

from dotenv import load_dotenv
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    CreateMessageRequest,
    CreateMessageRequestBody,
)
from aiohttp import web, WSMsgType

load_dotenv()

# Configuration
APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
HUB_PORT = int(os.getenv("HUB_PORT", "9800"))
HUB_TOKEN = os.getenv("HUB_TOKEN")  # Simple auth token for agents (required)
ALLOWED_USERS = [u.strip() for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# Reply "✅ sent" back to Feishu after each successful forward to an agent.
CONFIRM_SEND = os.getenv("CONFIRM_SEND", "true").lower() in ("1", "true", "yes")

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hub")


class AgentRegistry:
    """Manages connected remote agents."""

    def __init__(self):
        self.agents: dict[str, web.WebSocketResponse] = {}  # name -> ws
        self.active: Optional[str] = None
        self.last_seen: dict[str, float] = {}

    def register(self, name: str, ws: web.WebSocketResponse):
        self.agents[name] = ws
        self.last_seen[name] = time.time()
        if self.active is None:
            self.active = name
            log.info(f"Auto-activated first agent: {name}")
        log.info(f"Agent registered: {name} (total: {len(self.agents)})")

    def unregister(self, name: str):
        self.agents.pop(name, None)
        self.last_seen.pop(name, None)
        if self.active == name:
            self.active = next(iter(self.agents), None)
            log.info(f"Active agent disconnected. Switched to: {self.active}")
        log.info(f"Agent unregistered: {name} (total: {len(self.agents)})")

    async def send_to_active(self, text: str) -> bool:
        if not self.active or self.active not in self.agents:
            return False
        ws = self.agents[self.active]
        try:
            await ws.send_json({"type": "command", "text": text})
            self.last_seen[self.active] = time.time()
            return True
        except Exception as e:
            log.error(f"Failed to send to {self.active}: {e}")
            return False

    def switch(self, name: str) -> str:
        if name not in self.agents:
            available = ", ".join(self.agents.keys()) or "(none)"
            return f"❌ Agent '{name}' not found. Available: {available}"
        self.active = name
        return f"✅ Switched to: {name}"

    def status(self) -> str:
        if not self.agents:
            return "No agents connected."
        lines = []
        for name in self.agents:
            marker = " 👈 active" if name == self.active else ""
            ago = int(time.time() - self.last_seen.get(name, 0))
            lines.append(f"• {name} (last seen: {ago}s ago){marker}")
        return "\n".join(lines)


registry = AgentRegistry()
lark_client: Optional[lark.Client] = None

# The event loop that runs the aiohttp WebSocket server. The lark client runs
# in the main thread with its own loop, so cross-thread coroutine submissions
# (registry.send_to_active, _request_read) must target THIS loop explicitly.
agent_loop: Optional[asyncio.AbstractEventLoop] = None


def reply_to_feishu(chat_id: str, text: str):
    """Send a reply back to the user via Feishu."""
    if not lark_client:
        return
    try:
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        lark_client.im.v1.message.create(req)
    except Exception as e:
        log.error(f"Failed to reply to Feishu: {e}")


def handle_message(event: P2ImMessageReceiveV1) -> None:
    """Process incoming Feishu message."""
    msg = event.event.message
    sender = event.event.sender

    # Access control. Always log the sender's open_id so you can read off your
    # own (app-specific) open_id and put it in ALLOWED_USERS.
    sender_id = sender.sender_id.open_id if sender and sender.sender_id else None
    log.info(f"Message from open_id: {sender_id}")
    if ALLOWED_USERS and sender_id not in ALLOWED_USERS:
        log.warning(f"Unauthorized user: {sender_id} (not in ALLOWED_USERS)")
        return

    # Only handle text messages in direct chat
    if msg.message_type != "text":
        return
    if msg.chat_type != "p2p":
        return

    try:
        content = json.loads(msg.content)
        text = content.get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return

    if not text:
        return

    chat_id = msg.chat_id

    # Handle slash commands
    if text.startswith("/"):
        handle_slash_command(text, chat_id)
        return

    # Ignore comments
    if text.startswith("#"):
        return

    # Forward to active agent. handle_message runs in the lark client's thread,
    # so we submit the coroutine to the aiohttp server's loop.
    if agent_loop is None:
        reply_to_feishu(chat_id, "⚠️ Hub not ready yet. Try again in a moment.")
        return

    future = asyncio.run_coroutine_threadsafe(registry.send_to_active(text), agent_loop)
    try:
        success = future.result(timeout=5)
    except Exception as e:
        log.error(f"Failed to forward to agent: {e}")
        success = False

    if success:
        if CONFIRM_SEND:
            reply_to_feishu(chat_id, f"✅ 已发送 → {registry.active}")
    else:
        reply_to_feishu(chat_id, "⚠️ No active agent or send failed. Use /list to check.")


def handle_slash_command(text: str, chat_id: str):
    """Handle /commands."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/use" or cmd == "/switch":
        if not arg:
            reply_to_feishu(chat_id, "Usage: /use <agent_name>")
        else:
            result = registry.switch(arg)
            reply_to_feishu(chat_id, result)

    elif cmd == "/list" or cmd == "/status":
        result = registry.status()
        reply_to_feishu(chat_id, result)

    elif cmd == "/read":
        # Request output from active agent (submit to the aiohttp server loop).
        if agent_loop is None:
            reply_to_feishu(chat_id, "⚠️ Hub not ready yet. Try again in a moment.")
            return
        future = asyncio.run_coroutine_threadsafe(_request_read(chat_id), agent_loop)
        try:
            future.result(timeout=10)
        except Exception as e:
            log.error(f"/read failed: {e}")
            reply_to_feishu(chat_id, "⚠️ Failed to read from active agent.")

    elif cmd == "/help":
        reply_to_feishu(
            chat_id,
            "Commands:\n"
            "/list - Show connected agents\n"
            "/use <name> - Switch active agent\n"
            "/read - Read terminal output from active agent\n"
            "/help - This message",
        )
    else:
        reply_to_feishu(chat_id, f"Unknown command: {cmd}. Try /help")


async def _request_read(chat_id: str):
    """Request terminal output from active agent."""
    if not registry.active or registry.active not in registry.agents:
        reply_to_feishu(chat_id, "No active agent.")
        return
    ws = registry.agents[registry.active]
    await ws.send_json({"type": "read_request", "chat_id": chat_id})


# --- WebSocket server for agents ---

async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle incoming WebSocket connections from agents."""
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    agent_name = None

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "register":
                token = data.get("token")
                if token != HUB_TOKEN:
                    await ws.send_json({"type": "error", "message": "Invalid token"})
                    await ws.close()
                    break
                agent_name = data.get("name", "unknown")
                registry.register(agent_name, ws)
                await ws.send_json({
                    "type": "registered",
                    "name": agent_name,
                    "active": registry.active == agent_name,
                })

            elif msg_type == "read_response":
                chat_id = data.get("chat_id")
                output = data.get("output", "")
                if chat_id:
                    reply_to_feishu(chat_id, f"📺 [{agent_name}]:\n{output[-2000:]}")

            elif msg_type == "pong":
                if agent_name:
                    registry.last_seen[agent_name] = time.time()

        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
            break

    if agent_name:
        registry.unregister(agent_name)

    return ws


async def start_hub():
    """Start the WebSocket server for agents (must run inside agent_loop)."""
    app = web.Application()
    app.router.add_get("/ws", ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HUB_PORT)
    await site.start()
    log.info(f"Hub WebSocket server listening on port {HUB_PORT}")


def run_agent_loop(ready: threading.Event):
    """Run the aiohttp WebSocket server loop forever in a dedicated thread.

    The lark client blocks the main thread, so the agent-facing server needs
    its own continuously-running loop. We publish that loop as `agent_loop` so
    the lark callback thread can submit coroutines to it.
    """
    global agent_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agent_loop = loop
    loop.run_until_complete(start_hub())
    ready.set()
    loop.run_forever()


def main():
    global lark_client

    if not APP_ID or not APP_SECRET:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set")
        sys.exit(1)

    if not HUB_TOKEN:
        print("Error: HUB_TOKEN must be set to a strong random string "
              "(agents authenticate with it)")
        sys.exit(1)

    # Create Lark client for sending replies
    lark_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

    # Start the agent-facing WebSocket server on its own thread/loop and wait
    # until it's actually listening before accepting Feishu messages.
    ready = threading.Event()
    server_thread = threading.Thread(target=run_agent_loop, args=(ready,), daemon=True)
    server_thread.start()
    if not ready.wait(timeout=10):
        log.error("Hub WebSocket server failed to start within 10s")
        sys.exit(1)

    # Build Feishu event handler
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_message)
        .build()
    )

    # Start Feishu WebSocket client (blocks)
    client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.INFO if LOG_LEVEL == "DEBUG" else lark.LogLevel.WARNING,
    )

    log.info("Hub started. Waiting for agents and Feishu messages...")
    client.start()


if __name__ == "__main__":
    main()
