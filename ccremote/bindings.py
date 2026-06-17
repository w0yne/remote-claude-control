"""Per-chat_id → project binding table for group routing.

A third piece of cc_remote state, alongside the active pointer and registry:
  - bindings.json   a map {chat_id: alias} — which project a Feishu chat routes to

When a group is /bind'd to a project, its chat_id is recorded here. The bridge
consults this BEFORE the active pointer: a bound chat routes to its project, an
unbound chat (a DM, or a group nobody bound) falls back to the active pointer —
so existing single-DM behavior is untouched.

Pure stdlib (no lark, no dotenv), base dir passed in explicitly — same style as
registry.py and signals.py — so it's trivially testable against a temp dir. A
missing or corrupt bindings file degrades to {} and never breaks routing.
"""

import json
import os

BINDINGS_FILE = "bindings.json"


def _bindings_path(base_dir):
    return os.path.join(base_dir, BINDINGS_FILE)


def load(base_dir):
    """The full binding map {chat_id: alias}. Returns {} if missing or corrupt
    (a garbage file must never break routing)."""
    try:
        with open(_bindings_path(base_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _save(base_dir, table):
    """Write the binding map atomically (tmp + os.replace)."""
    try:
        os.makedirs(base_dir, exist_ok=True)
        path = _bindings_path(base_dir)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(table, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def read_binding(base_dir, chat_id):
    """The alias this chat is bound to, or None if unbound."""
    return load(base_dir).get(chat_id)


def bind(base_dir, chat_id, alias):
    """Bind chat_id → alias (overwriting any existing binding for this chat)."""
    table = load(base_dir)
    table[chat_id] = alias
    return _save(base_dir, table)


def unbind(base_dir, chat_id):
    """Remove chat_id's binding. True if it existed, False otherwise."""
    table = load(base_dir)
    if chat_id not in table:
        return False
    del table[chat_id]
    _save(base_dir, table)
    return True
