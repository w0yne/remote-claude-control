"""Tests for hook_notify per-session isolation.

The hook must read ONLY the signals belonging to the tmux session it is firing
inside, so a turn finishing in session A never consumes session B's signals or
sends B's screenshot. The pure decision — "given my current session, which
signal dir do I own?" — is isolated into a testable helper; the side-effecting
main() just calls it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hook_notify
from ccremote import config


def test_hook_owns_only_its_session_signal_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    config.load_env()
    # Pretend this hook is firing inside session 'a'.
    monkeypatch.setattr(hook_notify.tmux, "current_session", lambda: "a")
    sig_dir, shot_dir = hook_notify.resolve_session_dirs()
    assert sig_dir == config.signal_dir("a")
    assert shot_dir == config.screenshot_dir("a")
    # And NOT session b's.
    assert sig_dir != config.signal_dir("b")


def test_hook_not_in_tmux_returns_none(monkeypatch, tmp_path):
    """No tmux session (None) → hook owns nothing → must no-op."""
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    config.load_env()
    monkeypatch.setattr(hook_notify.tmux, "current_session", lambda: None)
    assert hook_notify.resolve_session_dirs() == (None, None)


def test_session_a_hook_cannot_see_session_b_signals(monkeypatch, tmp_path):
    """End-to-end isolation: write a signal into b's dir, then have a's hook
    list its own dir — it must find nothing."""
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    config.load_env()
    from ccremote import signals
    signals.write_signal(config.signal_dir("b"), "msg-b", "chat-b", "react-b")
    # a's hook lists its own (empty) dir
    monkeypatch.setattr(hook_notify.tmux, "current_session", lambda: "a")
    sig_dir, _ = hook_notify.resolve_session_dirs()
    assert signals.list_signals(sig_dir) == []
    # sanity: b's dir really does have the signal
    assert len(signals.list_signals(config.signal_dir("b"))) == 1
