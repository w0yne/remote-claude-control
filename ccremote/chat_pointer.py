"""Per-session chat pointer: sessions/<session>/chat holds the chat_id of the
most recent Feishu chat that drove that tmux session.

bridge.py writes it on every routed message; `cc-remote notify` reads it (via
the session it is running inside) to send a proactive notification back to the
chat that issued the original command — without relying on the Stop hook.

Pure stdlib, base dir passed in explicitly (no config import) — same style as
signals.py / registry.py / bindings.py, so it's trivially testable against a
temp dir. Every operation is best-effort: a write failure never breaks bridge
routing, a read failure degrades to None ('no target')."""

import os


def pointer_path(base_dir, session):
    """Absolute path of the chat pointer file for a tmux session."""
    return os.path.join(base_dir, "sessions", session, "chat")


def write(base_dir, session, chat_id):
    """Record chat_id as the most recent driver of `session`. Atomic
    (tmp + os.replace). Returns True on success, False on any failure
    (never raises — must not break bridge routing)."""
    try:
        path = pointer_path(base_dir, session)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(chat_id)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def read(base_dir, session):
    """The chat_id most recently routed to `session`, or None if the pointer is
    missing, empty, or unreadable."""
    try:
        with open(pointer_path(base_dir, session), encoding="utf-8") as f:
            val = f.read().strip()
        return val or None
    except (FileNotFoundError, OSError):
        return None
