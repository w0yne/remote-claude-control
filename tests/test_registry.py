"""Tests for ccremote.registry — the multi-project registry + active pointer.

Pure-stdlib module; every test runs against a temp dir (no ~/.cc_remote, no
tmux, no Feishu). registry takes the base dir explicitly so it's trivially
isolatable.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import registry


def test_resolve_target_falls_back_to_default_when_no_active(tmp_path):
    """With no active pointer written, resolve_target returns the given default
    (so a fresh install with no /switch ever issued routes to the default cc
    session, preserving current single-session behavior)."""
    assert registry.resolve_target(str(tmp_path), default="cc") == "cc"


def test_write_then_read_active_round_trips(tmp_path):
    registry.write_active(str(tmp_path), "web")
    assert registry.read_active(str(tmp_path)) == "web"


def test_resolve_target_uses_active_pointer_when_set(tmp_path):
    registry.write_active(str(tmp_path), "web")
    assert registry.resolve_target(str(tmp_path), default="cc") == "web"


def test_load_empty_registry_returns_empty_dict(tmp_path):
    assert registry.load(str(tmp_path)) == {}


def test_add_then_get_project(tmp_path):
    registry.add(str(tmp_path), "web", session="cc-web",
                 dir="/Users/me/dev/web", claude_session_id="abc-123")
    proj = registry.get(str(tmp_path), "web")
    assert proj == {
        "session": "cc-web",
        "dir": "/Users/me/dev/web",
        "claude_session_id": "abc-123",
    }


def test_add_is_idempotent_overwrite(tmp_path):
    registry.add(str(tmp_path), "p", session="s1", dir="/a")
    registry.add(str(tmp_path), "p", session="s2", dir="/b")
    assert registry.get(str(tmp_path), "p")["session"] == "s2"
    assert len(registry.load(str(tmp_path))) == 1


def test_get_unknown_alias_returns_none(tmp_path):
    assert registry.get(str(tmp_path), "nope") is None


def test_remove_project(tmp_path):
    registry.add(str(tmp_path), "p", session="s", dir="/a")
    assert registry.remove(str(tmp_path), "p") is True
    assert registry.get(str(tmp_path), "p") is None


def test_remove_unknown_alias_returns_false(tmp_path):
    assert registry.remove(str(tmp_path), "nope") is False


def test_load_corrupt_registry_returns_empty(tmp_path):
    """A garbage projects.json must not break routing/listing — degrade to {}."""
    with open(os.path.join(str(tmp_path), registry.REGISTRY_FILE), "w") as f:
        f.write("{ not valid json ::::")
    assert registry.load(str(tmp_path)) == {}
