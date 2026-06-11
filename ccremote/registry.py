"""Multi-project registry + active routing pointer.

Two pieces of state under the cc_remote home dir:
  - active        a flat file holding the tmux session name currently routed to
  - projects.json a registry mapping alias -> {session, dir, claude_session_id}

Pure stdlib (no lark, no dotenv) so the cc-remote CLI can import it before
anything is installed. The base dir is passed in explicitly — no config import
here — so it's trivially testable against a temp dir, same style as signals.py.

bridge routing depends ONLY on resolve_target() (active pointer + fallback); the
registry proper just backs the /switch and /projects alias lookup/display, so a
missing or corrupt registry never breaks routing.
"""

import json
import os

ACTIVE_FILE = "active"
REGISTRY_FILE = "projects.json"


def _active_path(base_dir):
    return os.path.join(base_dir, ACTIVE_FILE)


def read_active(base_dir):
    """The session name currently routed to, or None if no pointer is set."""
    try:
        with open(_active_path(base_dir), encoding="utf-8") as f:
            val = f.read().strip()
        return val or None
    except (FileNotFoundError, OSError):
        return None


def write_active(base_dir, session):
    """Point routing at `session`. Atomic (tmp + os.replace)."""
    try:
        os.makedirs(base_dir, exist_ok=True)
        path = _active_path(base_dir)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(session)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def resolve_target(base_dir, default):
    """The tmux session bridge should route to: the active pointer if set, else
    `default` (config.TMUX_SESSION). Never raises — routing must not depend on
    registry integrity."""
    return read_active(base_dir) or default


def _registry_path(base_dir):
    return os.path.join(base_dir, REGISTRY_FILE)


def load(base_dir):
    """The full registry dict {alias: {...}}. Returns {} if missing or corrupt
    (a garbage file must never break /switch, /projects, or routing)."""
    try:
        with open(_registry_path(base_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def save(base_dir, reg):
    """Write the registry atomically (tmp + os.replace)."""
    try:
        os.makedirs(base_dir, exist_ok=True)
        path = _registry_path(base_dir)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def add(base_dir, alias, session, dir, claude_session_id=None):
    """Register (or overwrite) a project. `dir` is the project's working dir
    (absolute path); identity is alias + dir + session — never git remote/repo,
    so the tool stays usable on any folder, git or not."""
    reg = load(base_dir)
    reg[alias] = {
        "session": session,
        "dir": dir,
        "claude_session_id": claude_session_id,
    }
    save(base_dir, reg)
    return reg[alias]


def get(base_dir, alias):
    """The project dict for `alias`, or None if not registered."""
    return load(base_dir).get(alias)


def remove(base_dir, alias):
    """Drop `alias` from the registry. True if it existed, False otherwise."""
    reg = load(base_dir)
    if alias not in reg:
        return False
    del reg[alias]
    save(base_dir, reg)
    return True
