"""Tests for bridge routing resolution and Feishu @-mention stripping.

resolve_session is the heart of the multi-group feature AND the guard on the
'DM untouched' invariant: with no bindings it must equal the legacy
registry.resolve_target for ANY chat_id. strip_mentions lets a command typed as
'@bot /bind web' still parse. Both pure — no tmux, no lark.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bridge
from ccremote import bindings, registry


# ---- resolve_session ----

def test_resolve_session_unbound_chat_uses_active_pointer(tmp_path):
    """DM-untouched invariant: no binding → exactly the legacy active pointer."""
    base = str(tmp_path)
    registry.write_active(base, "cc")
    assert bridge.resolve_session(base, "chat_any", default="def") == "cc"


def test_resolve_session_unbound_no_active_uses_default(tmp_path):
    assert bridge.resolve_session(str(tmp_path), "chat_any", default="def") == "def"


def test_resolve_session_bound_chat_uses_project_session(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    bindings.bind(base, "chat_web", "web")
    assert bridge.resolve_session(base, "chat_web", default="def") == "cc-web"


def test_resolve_session_bound_chat_ignores_active_pointer(tmp_path):
    """Parallel isolation: a bound group routes to its project even when the DM's
    active pointer points elsewhere."""
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    bindings.bind(base, "chat_web", "web")
    registry.write_active(base, "cc")  # DM is on 'cc'
    assert bridge.resolve_session(base, "chat_web", default="def") == "cc-web"


def test_resolve_session_dangling_binding_falls_back(tmp_path):
    """Bound to a since-removed project → fall back to active pointer, never crash."""
    base = str(tmp_path)
    bindings.bind(base, "chat_web", "web")  # 'web' not in registry
    registry.write_active(base, "cc")
    assert bridge.resolve_session(base, "chat_web", default="def") == "cc"


# ---- strip_mentions ----

def test_strip_mentions_removes_leading_user_token():
    assert bridge.strip_mentions("@_user_1 /bind web") == "/bind web"


def test_strip_mentions_removes_at_all():
    assert bridge.strip_mentions("@_all /projects") == "/projects"


def test_strip_mentions_plain_text_unchanged():
    assert bridge.strip_mentions("hello world") == "hello world"


def test_strip_mentions_multiple_tokens():
    assert bridge.strip_mentions("@_user_1 @_user_2 deploy now") == "deploy now"
