"""Tests for config.py per-session directory derivation (multi-project).

signal/screenshot dirs move from global single dirs to
~/.cc_remote/sessions/<session>/{signals,screenshots} so each tmux session's
hook only ever sees its own signals. TMUX_SESSION stays as the routing
fallback default.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import config


def test_signal_dir_is_per_session_under_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    config.load_env()
    assert config.signal_dir("cc") == os.path.join(
        str(tmp_path), "sessions", "cc", "signals"
    )
    assert config.signal_dir("web") == os.path.join(
        str(tmp_path), "sessions", "web", "signals"
    )


def test_screenshot_dir_is_per_session_under_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    config.load_env()
    assert config.screenshot_dir("cc") == os.path.join(
        str(tmp_path), "sessions", "cc", "screenshots"
    )


def test_two_sessions_get_distinct_signal_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    config.load_env()
    assert config.signal_dir("a") != config.signal_dir("b")


def test_tmux_session_default_preserved(monkeypatch, tmp_path):
    """No TMUX_SESSION env → default 'cc' (back-compat single-session)."""
    monkeypatch.setenv("CC_REMOTE_DIR", str(tmp_path))
    monkeypatch.delenv("TMUX_SESSION", raising=False)
    config.load_env()
    assert config.TMUX_SESSION == "cc"
