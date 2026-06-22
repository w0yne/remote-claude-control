"""Configuration: .env loading and all tunables, in one place.

Pure stdlib + python-dotenv — NO lark_oapi — so the cc-remote CLI can import
this even on a python that lacks the runtime deps (doctor/install must not
crash). load_env() resolves ~/.cc_remote/.env first, then a repo-local .env.

Usage: call load_env() once at process start (entrypoints do this), then read
the module-level constants. They start at historical defaults and load_env()
refreshes them from os.environ via _refresh().
"""

import os

# These are populated by load_env(). Defaults here match the historical
# per-file defaults so behavior is unchanged.
CC_REMOTE_DIR = os.path.expanduser("~/.cc_remote")
IMAGE_DIR = os.path.join(CC_REMOTE_DIR, "images")
# Legacy global signal/screenshot dirs (pre multi-project). Kept until bridge
# and hook are switched to the per-session dirs below; signal_dir()/
# screenshot_dir() are the multi-project replacements.
SIGNAL_DIR = os.path.join(CC_REMOTE_DIR, "signals")
SCREENSHOT_DIR = os.path.join(CC_REMOTE_DIR, "screenshots")
# Multi-project: each tmux session gets its own subtree
# ~/.cc_remote/sessions/<session>/{signals,screenshots} so a session's hook
# only ever sees its own signals (physical isolation, no cross-talk).
SESSIONS_DIR = os.path.join(CC_REMOTE_DIR, "sessions")
TMUX_SESSION = "cc"  # routing fallback when no active pointer is set
APP_ID = None
APP_SECRET = None
ALLOWED_USERS = []
LOG_LEVEL = "INFO"
REACTION_PROCESSING = "OnIt"
REACTION_DONE = "DONE"
REACTION_ERROR = "CrossMark"
CAPTURE_LINES = 0
WEBP_QUALITY = 80
KEEP_SCREENSHOTS = 12
SIGNAL_TTL_SEC = 1800
MAX_TEXT_CHARS = 4000
MAX_CARD_CHARS = 8000
SEEN_TTL_SEC = 300
CARD_FOOTER = True
CONTEXT_WINDOW_SIZE = 200000
WATCHDOG_DOWN_THRESHOLD_SEC = 180
WATCHDOG_INTERVAL_SEC = 60


def _env_bool(name, default):
    """Parse a boolean env var. Truthy unless explicitly false-ish."""
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() not in ("false", "0", "no", "off", "")


def load_env():
    """Load ~/.cc_remote/.env (preferred) or a repo-local .env, then refresh all
    module-level config constants from os.environ. Safe to call more than once.
    Returns the resolved CC_REMOTE_DIR for convenience."""
    try:
        from dotenv import load_dotenv

        home_env = os.path.expanduser("~/.cc_remote/.env")
        # A .env sitting next to the package's parent dir — i.e. the repo root in
        # a dev checkout, or ~/.cc_remote/bin for an installed copy. This mirrors
        # the entrypoints' old HERE/.env fallback, which didn't depend on cwd.
        beside_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(home_env):
            load_dotenv(home_env)
        elif os.path.exists(beside_env):
            load_dotenv(beside_env)
        else:
            load_dotenv()  # last resort: dotenv's cwd-upward search
    except Exception:
        pass
    _refresh()
    return CC_REMOTE_DIR


def _refresh():
    global CC_REMOTE_DIR, IMAGE_DIR, SIGNAL_DIR, SCREENSHOT_DIR, SESSIONS_DIR, TMUX_SESSION
    global APP_ID, APP_SECRET, ALLOWED_USERS, LOG_LEVEL
    global REACTION_PROCESSING, REACTION_DONE, REACTION_ERROR
    global CAPTURE_LINES, WEBP_QUALITY, KEEP_SCREENSHOTS
    global SIGNAL_TTL_SEC, MAX_TEXT_CHARS, MAX_CARD_CHARS, SEEN_TTL_SEC
    global CARD_FOOTER, CONTEXT_WINDOW_SIZE
    global WATCHDOG_DOWN_THRESHOLD_SEC, WATCHDOG_INTERVAL_SEC

    CC_REMOTE_DIR = os.path.expanduser(os.getenv("CC_REMOTE_DIR", "~/.cc_remote"))
    IMAGE_DIR = os.path.join(CC_REMOTE_DIR, "images")
    SIGNAL_DIR = os.path.join(CC_REMOTE_DIR, "signals")
    SCREENSHOT_DIR = os.path.join(CC_REMOTE_DIR, "screenshots")
    SESSIONS_DIR = os.path.join(CC_REMOTE_DIR, "sessions")
    TMUX_SESSION = os.getenv("TMUX_SESSION", "cc")
    APP_ID = os.getenv("FEISHU_APP_ID")
    APP_SECRET = os.getenv("FEISHU_APP_SECRET")
    ALLOWED_USERS = [u.strip() for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()]
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    REACTION_PROCESSING = os.getenv("REACTION_PROCESSING", "OnIt")
    REACTION_DONE = os.getenv("REACTION_DONE", "DONE")
    REACTION_ERROR = os.getenv("REACTION_ERROR", "CrossMark")
    CAPTURE_LINES = int(os.getenv("CAPTURE_LINES", "0"))
    WEBP_QUALITY = int(os.getenv("WEBP_QUALITY", "80"))
    KEEP_SCREENSHOTS = max(1, int(os.getenv("KEEP_SCREENSHOTS", "12")))
    SIGNAL_TTL_SEC = int(os.getenv("SIGNAL_TTL_SEC", "1800"))
    MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "4000"))
    MAX_CARD_CHARS = int(os.getenv("MAX_CARD_CHARS", "8000"))
    SEEN_TTL_SEC = int(os.getenv("SEEN_TTL_SEC", "300"))
    CARD_FOOTER = _env_bool("CARD_FOOTER", True)
    CONTEXT_WINDOW_SIZE = int(os.getenv("CONTEXT_WINDOW_SIZE", "200000"))
    WATCHDOG_DOWN_THRESHOLD_SEC = int(os.getenv("WATCHDOG_DOWN_THRESHOLD_SEC", "180"))
    WATCHDOG_INTERVAL_SEC = int(os.getenv("WATCHDOG_INTERVAL_SEC", "60"))


def signal_dir(session):
    """Per-session signal dir: ~/.cc_remote/sessions/<session>/signals.
    Each tmux session's hook reads only its own, so projects never cross-talk."""
    return os.path.join(SESSIONS_DIR, session, "signals")


def screenshot_dir(session):
    """Per-session screenshot dir: ~/.cc_remote/sessions/<session>/screenshots."""
    return os.path.join(SESSIONS_DIR, session, "screenshots")


def ensure_dirs():
    """Create the global working subdirs (images/signals/screenshots) under
    CC_REMOTE_DIR. Per-session dirs are created lazily by signal/screenshot
    writers via os.makedirs(exist_ok=True)."""
    for d in (IMAGE_DIR, SIGNAL_DIR, SCREENSHOT_DIR):
        os.makedirs(d, exist_ok=True)
