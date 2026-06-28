"""Tests for the per-session chat pointer: sessions/<session>/chat holds the
chat_id of the most recent Feishu chat that drove that tmux session, so
`cc-remote notify` can send back to it. Pure stdlib, base dir passed in —
trivially testable against a temp dir, same style as signals/registry."""

import os

from ccremote import chat_pointer


def test_write_then_read_roundtrips(tmp_path):
    base = str(tmp_path)
    assert chat_pointer.write(base, "cc", "oc_chat_abc") is True
    assert chat_pointer.read(base, "cc") == "oc_chat_abc"


def test_read_missing_returns_none(tmp_path):
    assert chat_pointer.read(str(tmp_path), "cc") is None


def test_write_overwrites(tmp_path):
    base = str(tmp_path)
    chat_pointer.write(base, "cc", "oc_first")
    chat_pointer.write(base, "cc", "oc_second")
    assert chat_pointer.read(base, "cc") == "oc_second"


def test_per_session_isolation(tmp_path):
    """Two sessions keep independent pointers."""
    base = str(tmp_path)
    chat_pointer.write(base, "cc", "oc_dm")
    chat_pointer.write(base, "cc-web", "oc_group")
    assert chat_pointer.read(base, "cc") == "oc_dm"
    assert chat_pointer.read(base, "cc-web") == "oc_group"


def test_read_empty_file_returns_none(tmp_path):
    base = str(tmp_path)
    path = chat_pointer.pointer_path(base, "cc")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("   \n")
    assert chat_pointer.read(base, "cc") is None


def test_write_bad_base_returns_false_no_raise(tmp_path):
    """A base_dir that can't be created (a file where a dir must go) → write
    returns False, never raises (best-effort contract)."""
    base_as_file = str(tmp_path / "not_a_dir")
    with open(base_as_file, "w") as f:
        f.write("x")
    # sessions/<s>/chat under a path whose parent is a file → makedirs fails.
    assert chat_pointer.write(base_as_file, "cc", "oc_x") is False
