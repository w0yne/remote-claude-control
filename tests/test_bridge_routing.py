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


def test_resolve_session_corrupt_binding_value_falls_back(tmp_path):
    """A bindings.json with a non-string value must NOT crash resolve_session
    (its docstring promises 'never raises'); it falls back to the active pointer
    — the §3 'corrupt bindings -> safe fallback to old logic' invariant."""
    import os as _os
    base = str(tmp_path)
    registry.write_active(base, "cc")
    with open(_os.path.join(base, bindings.BINDINGS_FILE), "w") as f:
        f.write('{"chat_web": ["not", "a", "string"]}')
    assert bridge.resolve_session(base, "chat_web", default="def") == "cc"


# ---- strip_mentions ----
# A Feishu group injects @-mention placeholders only as LEADING tokens of the
# text (when the bot is @'d). strip_mentions must remove those but NEVER touch a
# placeholder-looking substring that appears mid-text (a path, an email, code) —
# else it silently corrupts legitimate content.

def test_strip_mentions_removes_leading_user_token():
    assert bridge.strip_mentions("@_user_1 /bind web") == "/bind web"


def test_strip_mentions_removes_at_all():
    assert bridge.strip_mentions("@_all /projects") == "/projects"


def test_strip_mentions_plain_text_unchanged():
    assert bridge.strip_mentions("hello world") == "hello world"


def test_strip_mentions_multiple_leading_tokens():
    assert bridge.strip_mentions("@_user_1 @_user_2 deploy now") == "deploy now"


def test_strip_mentions_does_not_eat_midtext_email():
    """A literal '@_user_1' inside an email/path must survive — only LEADING
    mention tokens are stripped."""
    assert bridge.strip_mentions("email foo@_user_1.com") == "email foo@_user_1.com"


def test_strip_mentions_does_not_eat_midtext_path():
    assert bridge.strip_mentions("see path/to/@_user_99/file") == "see path/to/@_user_99/file"


def test_strip_mentions_leading_then_midtext_kept():
    """Strip the leading mention, keep a later in-word occurrence verbatim."""
    assert bridge.strip_mentions("@_user_1 grep @_all in logs") == "grep @_all in logs"
