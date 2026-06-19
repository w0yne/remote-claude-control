"""Tests for bridge.handle_message dispatch wiring (the /projects rich-text
path). A minimal fake event stands in for P2ImMessageReceiveV1 — no lark, no
network. ALLOWED_USERS is emptied so the auth gate is skipped."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bridge
from ccremote import config, feishu


def _event(text, chat_id="c1", message_id="m-unique-1", chat_type="p2p"):
    sender = types.SimpleNamespace(
        sender_id=types.SimpleNamespace(open_id="ou_test"))
    import json
    msg = types.SimpleNamespace(
        chat_id=chat_id, message_id=message_id, chat_type=chat_type,
        message_type="text", content=json.dumps({"text": text}))
    return types.SimpleNamespace(
        event=types.SimpleNamespace(message=msg, sender=sender))


def test_projects_command_replies_via_send_markdown(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USERS", [])  # skip auth gate
    monkeypatch.setattr(bridge, "_client", object())
    calls = []
    monkeypatch.setattr(feishu, "send_markdown",
                        lambda c, cid, md, fb, **k: calls.append((cid, md, fb, k)) or True)
    # format_projects reads the registry; stub it to a known string.
    monkeypatch.setattr(bridge, "format_projects", lambda base, alive: "项目A ★")

    bridge.handle_message(_event("/projects", message_id="m-proj-1"))

    assert len(calls) == 1
    cid, md, fb, kw = calls[0]
    assert cid == "c1"
    assert md == "项目A ★"        # card carries the listing
    assert fb == "项目A ★"        # fallback is the same short listing
