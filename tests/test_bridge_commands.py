"""Tests for bridge command logic: /switch and /projects.

The pure decision logic is isolated from tmux/Feishu so it's testable offline.
do_switch decides what switching to an alias means (and whether it's allowed);
format_projects renders the listing. A session_exists callable is injected so
tmux liveness can be faked.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bridge
from ccremote import registry


def _alive(*live):
    """Return a session_exists(name)->bool faking the given sessions as alive."""
    s = set(live)
    return lambda name: name in s


def test_switch_to_live_registered_project_sets_active(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/d/web")
    ok, reply, session = bridge.do_switch(base, "web", _alive("cc-web"))
    assert ok is True
    assert session == "cc-web"
    assert registry.read_active(base) == "cc-web"
    assert "web" in reply


def test_switch_to_dead_session_does_not_change_active(tmp_path):
    """Phase A: a dead target is NOT revived; active pointer stays put."""
    base = str(tmp_path)
    registry.add(base, "cc", session="cc", dir="/d/cc")
    registry.write_active(base, "cc")
    registry.add(base, "web", session="cc-web", dir="/d/web")
    ok, reply, session = bridge.do_switch(base, "web", _alive("cc"))  # cc-web dead
    assert ok is False
    assert registry.read_active(base) == "cc"  # unchanged
    assert "setup" in reply.lower()


def test_switch_to_unknown_alias_lists_known(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/d/web")
    ok, reply, session = bridge.do_switch(base, "ghost", _alive("cc-web"))
    assert ok is False
    assert session is None
    assert "web" in reply  # tells the user what aliases exist


def test_format_projects_marks_active_and_liveness(tmp_path):
    base = str(tmp_path)
    registry.add(base, "cc", session="cc", dir="/d/cc")
    registry.add(base, "web", session="cc-web", dir="/d/web")
    registry.write_active(base, "cc")
    out = bridge.format_projects(base, _alive("cc"))  # cc live, cc-web dead
    assert "cc" in out and "web" in out
    # active marker on cc, liveness differs between the two
    assert out.count("\n") >= 1  # multi-line listing


def test_format_projects_empty_registry(tmp_path):
    out = bridge.format_projects(str(tmp_path), _alive())
    assert "setup" in out.lower() or "无" in out


# ---- /bind /unbind /whoami (group-binding commands) ----
from ccremote import bindings


def _rename_ok(record=None):
    """A fake rename(chat_id, name) -> (ok, err) that always succeeds and
    optionally records its (chat_id, name) calls."""
    def rename(chat_id, name):
        if record is not None:
            record.append((chat_id, name))
        return (True, None)
    return rename


def _rename_fail(chat_id, name):
    return (False, "code=99")


def test_bind_known_alias_writes_binding_and_renames(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    calls = []
    ok, reply = bridge.do_bind(base, "chat_web", "web", _rename_ok(calls))
    assert ok is True
    assert bindings.read_binding(base, "chat_web") == "web"
    assert "web" in reply
    assert calls == [("chat_web", "🤖 web")]  # renamed to bot-prefixed alias


def test_bind_rename_failure_still_binds(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    ok, reply = bridge.do_bind(base, "chat_web", "web", _rename_fail)
    assert ok is True  # rename failure does NOT fail the bind
    assert bindings.read_binding(base, "chat_web") == "web"
    assert "⚠️" in reply  # but the reply warns about the rename


def test_bind_unknown_alias_lists_known_and_writes_nothing(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    ok, reply = bridge.do_bind(base, "chat_x", "ghost", _rename_ok())
    assert ok is False
    assert bindings.read_binding(base, "chat_x") is None
    assert "web" in reply  # tells the user what aliases exist


def test_unbind_bound_chat_removes_binding(tmp_path):
    base = str(tmp_path)
    bindings.bind(base, "chat_web", "web")
    ok, reply = bridge.do_unbind(base, "chat_web")
    assert ok is True
    assert bindings.read_binding(base, "chat_web") is None


def test_unbind_unbound_chat_returns_false(tmp_path):
    ok, reply = bridge.do_unbind(str(tmp_path), "chat_none")
    assert ok is False
    assert "未绑定" in reply


def test_whoami_bound_reports_alias_and_session(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    bindings.bind(base, "chat_web", "web")
    out = bridge.do_whoami(base, "chat_web")
    assert "web" in out and "cc-web" in out


def test_whoami_unbound_reports_fallback(tmp_path):
    out = bridge.do_whoami(str(tmp_path), "chat_none")
    assert "未绑定" in out


def test_whoami_dangling_binding_points_to_recovery(tmp_path):
    """Bound to an alias no longer in the registry → tell the user to /unbind
    or re-setup, don't crash."""
    base = str(tmp_path)
    bindings.bind(base, "chat_web", "web")  # 'web' never registered
    out = bridge.do_whoami(base, "chat_web")
    assert "web" in out
    assert "unbind" in out.lower() or "setup" in out.lower()


def test_format_projects_marks_bound_group(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    bindings.bind(base, "chat_web", "web")
    out = bridge.format_projects(base, _alive("cc-web"))
    assert "🔗群" in out  # bound project's line shows the link marker


def test_format_projects_unbound_has_no_link_marker(tmp_path):
    base = str(tmp_path)
    registry.add(base, "web", session="cc-web", dir="/Users/me/dev/web")
    out = bridge.format_projects(base, _alive("cc-web"))
    # The legend header mentions 🔗, but no project LINE carries the 🔗群 marker.
    assert "🔗群" not in out
