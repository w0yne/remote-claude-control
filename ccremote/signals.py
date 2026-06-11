"""Per-command signal files: one signals/<message_id>.json per in-flight remote
command. bridge.py writes them; hook_notify.py reads/consumes them. Keeping the
schema (message_id, chat_id, reaction_id, ts) in one place stops the writer and
reader from drifting.

The signal dir is passed in explicitly so this module has no config import and
is trivially testable against a temp dir.
"""

import json
import os
import time
from datetime import datetime


def signal_path(signal_dir, message_id):
    """Absolute path of the signal file for a message_id (id sanitized)."""
    safe = "".join(c for c in (message_id or "unknown") if c.isalnum() or c in "_-")
    return os.path.join(signal_dir, f"{safe}.json")


def write_signal(signal_dir, message_id, chat_id, reaction_id):
    """Write a signal atomically (tmp + os.replace) so a reader never sees a
    half-written file. Returns the path on success, or "" on failure."""
    try:
        os.makedirs(signal_dir, exist_ok=True)
        path = signal_path(signal_dir, message_id)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "reaction_id": reaction_id,
                    "ts": datetime.now().isoformat(),
                },
                f,
            )
        os.replace(tmp, path)
        return path
    except Exception:
        return ""


def read_signal(path):
    """Parse a signal file. Returns the dict, or None if unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_signals(signal_dir):
    """Paths of all pending signal files, oldest first (by mtime)."""
    try:
        names = [
            os.path.join(signal_dir, n)
            for n in os.listdir(signal_dir)
            if n.endswith(".json")
        ]
    except FileNotFoundError:
        return []
    names.sort(key=_mtime)
    return names


def has_pending(signal_dir):
    """True if any command is awaiting a Stop-hook screenshot."""
    try:
        return any(n.endswith(".json") for n in os.listdir(signal_dir))
    except FileNotFoundError:
        return False


def is_stale(path, ttl_sec, now=None):
    """True if the signal file is older than ttl_sec."""
    now = time.time() if now is None else now
    return now - _mtime(path) > ttl_sec


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0
