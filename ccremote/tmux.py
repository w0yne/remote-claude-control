"""tmux interaction: check a session exists, type text or keys into it, and ask
which session the CURRENT pane belongs to (used by the Stop-hook gate).

Session name is passed in explicitly; no config import here.
"""

import logging
import os
import subprocess

log = logging.getLogger("ccremote.tmux")


def session_exists(session):
    """True if the named tmux session exists."""
    return subprocess.run(
        ["tmux", "has-session", "-t", session], capture_output=True
    ).returncode == 0


def send_text(session, text):
    """Type text into the session literally (-l), then press Enter. The -l flag
    stops tmux from interpreting words like 'Up'/'Enter' in a transcription as
    key names. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "-l", text],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "Enter"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"send_text failed: {e.stderr.decode() if e.stderr else e}")
        return False


def send_key(session, key):
    """Send a tmux key NAME (e.g. 'Enter', 'Escape', 'Up', 'C-c'), NOT literal
    text. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session, key],
            check=True, capture_output=True,
        )
        log.info(f"Sent key to tmux: {key}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"send_key failed: {e.stderr.decode() if e.stderr else e}")
        return False


def current_session():
    """The tmux session name THIS process's pane belongs to, or None.

    Decided by the inherited tmux env, not by directory:
    - No $TMUX → not in any tmux → None. (The env var is the real gate:
      `tmux display-message` with no target falsely resolves to the only session
      when just one exists.)
    - $TMUX set → query by the specific pane id ($TMUX_PANE, server-global-unique
      and deterministic).
    """
    if not os.environ.get("TMUX"):
        return None
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return None
    try:
        out = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#S"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        log.error(f"current_session failed: {e}")
        return None
    return out.stdout.strip() if out.returncode == 0 else None
