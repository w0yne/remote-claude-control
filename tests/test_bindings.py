"""Tests for ccremote.bindings — the per-chat_id → project binding table.

Pure-stdlib module; every test runs against a temp dir (no ~/.cc_remote, no
lark). bindings takes the base dir explicitly so it's trivially isolatable —
same style as test_registry.py. Fake chat_ids use neutral 'chatN' values (not
real 'oc_' ids) so they're obviously placeholders.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import bindings


def test_read_binding_unbound_returns_none(tmp_path):
    assert bindings.read_binding(str(tmp_path), "chat1") is None


def test_load_empty_returns_empty_dict(tmp_path):
    assert bindings.load(str(tmp_path)) == {}


def test_bind_then_read_round_trips(tmp_path):
    base = str(tmp_path)
    assert bindings.bind(base, "chat_web", "web") is True
    assert bindings.read_binding(base, "chat_web") == "web"


def test_bind_overwrites_existing(tmp_path):
    base = str(tmp_path)
    bindings.bind(base, "chat_web", "web")
    bindings.bind(base, "chat_web", "api")
    assert bindings.read_binding(base, "chat_web") == "api"
    assert len(bindings.load(base)) == 1


def test_two_chats_bind_independently(tmp_path):
    base = str(tmp_path)
    bindings.bind(base, "chat_web", "web")
    bindings.bind(base, "chat_api", "api")
    assert bindings.read_binding(base, "chat_web") == "web"
    assert bindings.read_binding(base, "chat_api") == "api"


def test_unbind_existing_returns_true_and_removes(tmp_path):
    base = str(tmp_path)
    bindings.bind(base, "chat_web", "web")
    assert bindings.unbind(base, "chat_web") is True
    assert bindings.read_binding(base, "chat_web") is None


def test_unbind_missing_returns_false(tmp_path):
    assert bindings.unbind(str(tmp_path), "chat_nope") is False


def test_load_corrupt_returns_empty(tmp_path):
    """A garbage bindings.json must not break routing — degrade to {}."""
    with open(os.path.join(str(tmp_path), bindings.BINDINGS_FILE), "w") as f:
        f.write("{ not valid json ::::")
    assert bindings.load(str(tmp_path)) == {}


def test_load_drops_non_string_entries(tmp_path):
    """A hand-corrupted bindings.json with non-string values is a valid dict but
    would make registry.get(base, <list>) raise TypeError. load() must drop such
    entries so read_binding/resolve_session stay total (never raise)."""
    with open(os.path.join(str(tmp_path), bindings.BINDINGS_FILE), "w") as f:
        f.write('{"chat_bad": ["a", "b"], "chat_ok": "web", "chat_num": 4}')
    assert bindings.load(str(tmp_path)) == {"chat_ok": "web"}


def test_read_binding_ignores_corrupt_value(tmp_path):
    """read_binding on a chat whose stored value is non-string returns None."""
    with open(os.path.join(str(tmp_path), bindings.BINDINGS_FILE), "w") as f:
        f.write('{"chat_bad": ["a", "b"]}')
    assert bindings.read_binding(str(tmp_path), "chat_bad") is None
