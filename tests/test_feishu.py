"""Tests for ccremote.feishu pure logic — update_chat_name's success/failure/
exception contract — using a fake lark client (no network). Other feishu
functions wrap lark calls 1:1 and are covered by integration, not here.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import feishu


class _Resp:
    def __init__(self, ok, code=0):
        self._ok, self.code = ok, code

    def success(self):
        return self._ok


def _client(behavior):
    """A minimal stand-in for the lark client whose chat.update calls
    `behavior(req)` — returns a _Resp or raises."""
    chat = types.SimpleNamespace(update=behavior)
    v1 = types.SimpleNamespace(chat=chat)
    return types.SimpleNamespace(im=types.SimpleNamespace(v1=v1))


def test_update_chat_name_success():
    calls = []

    def behavior(req):
        calls.append(req)
        return _Resp(True)

    ok, err = feishu.update_chat_name(_client(behavior), "chat_web", "🤖 web")
    assert ok is True
    assert err is None
    assert len(calls) == 1  # the API was actually invoked


def test_update_chat_name_api_failure_reports_code():
    ok, err = feishu.update_chat_name(_client(lambda req: _Resp(False, code=99)),
                                      "chat_web", "🤖 web")
    assert ok is False
    assert "99" in err


def test_update_chat_name_exception_is_caught():
    def boom(req):
        raise RuntimeError("kapow")

    ok, err = feishu.update_chat_name(_client(boom), "chat_web", "🤖 web")
    assert ok is False
    assert "kapow" in err


def test_update_chat_name_no_client_returns_false():
    ok, err = feishu.update_chat_name(None, "chat_web", "🤖 web")
    assert ok is False
    assert err


# ---- build_markdown_card (v2 schema) ----

def test_build_markdown_card_is_v2_with_body_elements():
    card = feishu.build_markdown_card("**hi**")
    assert card["schema"] == "2.0"
    elems = card["body"]["elements"]
    assert elems == [{"tag": "markdown", "content": "**hi**"}]


def test_build_markdown_card_no_header_by_default():
    card = feishu.build_markdown_card("x")
    assert "header" not in card


def test_build_markdown_card_with_header_title_and_template():
    card = feishu.build_markdown_card("x", header_title="项目列表",
                                      header_template="blue")
    assert card["header"]["title"] == {"tag": "plain_text", "content": "项目列表"}
    assert card["header"]["template"] == "blue"


def test_build_markdown_card_header_without_template_omits_template():
    card = feishu.build_markdown_card("x", header_title="标题")
    assert "template" not in card["header"]


# ---- send_card ----

def _msg_client(behavior):
    """Stand-in lark client whose im.v1.message.create calls behavior(req)."""
    message = types.SimpleNamespace(create=behavior)
    v1 = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(im=types.SimpleNamespace(v1=v1))


def test_send_card_success():
    calls = []
    ok = feishu.send_card(_msg_client(lambda req: calls.append(req) or _Resp(True)),
                          "chat_web", {"schema": "2.0"})
    assert ok is True
    assert len(calls) == 1


def test_send_card_api_failure_returns_false():
    ok = feishu.send_card(_msg_client(lambda req: _Resp(False, code=99)),
                          "chat_web", {"schema": "2.0"})
    assert ok is False


def test_send_card_exception_is_caught():
    def boom(req):
        raise RuntimeError("kapow")
    ok = feishu.send_card(_msg_client(boom), "chat_web", {"schema": "2.0"})
    assert ok is False


def test_send_card_no_client_returns_false():
    assert feishu.send_card(None, "chat_web", {"schema": "2.0"}) is False
    assert feishu.send_card(_msg_client(lambda req: _Resp(True)), "", {}) is False
