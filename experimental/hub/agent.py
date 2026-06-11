#!/usr/bin/env python3
"""
Remote Agent - Connects to the Bridge Hub and forwards commands to local tmux.

Runs on each remote machine. Connects outbound to the Hub via WebSocket
(no need to open any ports on this machine).
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys

from dotenv import load_dotenv
import aiohttp

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(description="Remote agent for remote-claude-control")
    parser.add_argument("--name", "-n", help="Agent name (e.g. work, home, lab)")
    parser.add_argument("--hub", help="Hub WebSocket URL (e.g. ws://192.168.1.100:9800/ws)")
    parser.add_argument("--token", help="Hub auth token")
    parser.add_argument("--session", "-s", help="tmux session name (default: cc)")
    return parser.parse_args()


args = parse_args()

# Configuration: CLI args > env vars > defaults
HUB_URL = args.hub or os.getenv("HUB_URL", "ws://localhost:9800/ws")
HUB_TOKEN = args.token or os.getenv("HUB_TOKEN")
AGENT_NAME = args.name or os.getenv("AGENT_NAME", "default")
TMUX_SESSION = args.session or os.getenv("TMUX_SESSION", "cc")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
RECONNECT_INTERVAL = int(os.getenv("RECONNECT_INTERVAL", "5"))

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(f"agent:{AGENT_NAME}")


def check_tmux_session() -> bool:
    """Check if the target tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", TMUX_SESSION],
        capture_output=True,
    )
    return result.returncode == 0


def send_to_tmux(text: str) -> bool:
    """Send text to the tmux session as literal characters, then press Enter."""
    try:
        # -l sends the text literally, so voice transcriptions containing words
        # like "Up", "Enter", "Space" or "C-c" are typed as text instead of
        # being interpreted by tmux as key names. Enter is sent separately.
        subprocess.run(
            ["tmux", "send-keys", "-t", TMUX_SESSION, "-l", text],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", TMUX_SESSION, "Enter"],
            check=True,
            capture_output=True,
        )
        log.info(f"→ tmux: {text[:80]}{'...' if len(text) > 80 else ''}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"tmux send failed: {e.stderr.decode()}")
        return False


def read_tmux_output(lines: int = 30) -> str:
    """Capture recent output from the tmux session."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", TMUX_SESSION, "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "(无法读取终端输出)"


async def run_agent():
    """Main agent loop - connect to hub and process commands."""
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                log.info(f"Connecting to hub: {HUB_URL}")
                async with session.ws_connect(HUB_URL, heartbeat=30) as ws:
                    # Register
                    await ws.send_json({
                        "type": "register",
                        "name": AGENT_NAME,
                        "token": HUB_TOKEN,
                    })

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await handle_hub_message(ws, json.loads(msg.data))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            log.error(f"WebSocket error: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            log.warning("Hub closed connection")
                            break

        except aiohttp.ClientError as e:
            log.warning(f"Connection failed: {e}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")

        log.info(f"Reconnecting in {RECONNECT_INTERVAL}s...")
        await asyncio.sleep(RECONNECT_INTERVAL)


async def handle_hub_message(ws: aiohttp.ClientWebSocketResponse, data: dict):
    """Handle a message from the hub."""
    msg_type = data.get("type")

    if msg_type == "registered":
        active = "✅ ACTIVE" if data.get("active") else "standby"
        log.info(f"Registered as '{data.get('name')}' ({active})")

    elif msg_type == "command":
        text = data.get("text", "")
        if not text:
            return

        if not check_tmux_session():
            log.error(f"tmux session '{TMUX_SESSION}' not found!")
            return

        send_to_tmux(text)

    elif msg_type == "read_request":
        chat_id = data.get("chat_id")
        output = read_tmux_output()
        await ws.send_json({
            "type": "read_response",
            "chat_id": chat_id,
            "output": output,
        })

    elif msg_type == "error":
        log.error(f"Hub error: {data.get('message')}")
        sys.exit(1)


def main():
    if not HUB_TOKEN:
        print("Error: set HUB_TOKEN (via --token or .env) — must match the hub's token")
        sys.exit(1)

    if not AGENT_NAME or AGENT_NAME == "default":
        print("⚠️  Set AGENT_NAME in .env (e.g., 'work', 'home', 'lab')")

    if not check_tmux_session():
        log.warning(
            f"tmux session '{TMUX_SESSION}' not found. "
            f"Start it with: tmux new-session -s {TMUX_SESSION}"
        )

    log.info(f"Agent '{AGENT_NAME}' starting (tmux: {TMUX_SESSION})")
    asyncio.run(run_agent())


if __name__ == "__main__":
    main()
