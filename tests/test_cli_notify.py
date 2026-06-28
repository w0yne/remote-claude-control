"""Tests for `cc-remote notify` — the proactive notification command.

Two layers:
 - target resolution (pure): --chat wins; else the current tmux session's chat
   pointer; else an error. No tmux, no lark.
 - content resolution (pure): positional arg wins; else stdin; else error.

cc-remote is loaded via importlib (extension-less executable), same as
test_cli_projects.py."""

import importlib.machinery
import importlib.util
import io
import os
import sys
import types

import pytest

CC_REMOTE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cc-remote"
)


def _load_cc_remote():
    spec = importlib.util.spec_from_loader(
        "cc_remote_cli",
        importlib.machinery.SourceFileLoader("cc_remote_cli", CC_REMOTE),
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = CC_REMOTE
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli(tmp_path, monkeypatch):
    mod = _load_cc_remote()
    home = str(tmp_path / "cc_remote_home")
    os.makedirs(home, exist_ok=True)
    monkeypatch.setattr(mod, "HOME", home)
    return mod, home


def _args(**kw):
    kw.setdefault("message", None)
    kw.setdefault("chat", None)
    kw.setdefault("title", None)
    return types.SimpleNamespace(**kw)


# ---- target resolution ----

def test_target_explicit_chat_wins(cli):
    mod, home = cli
    chat, err = mod._resolve_notify_target(
        _args(chat="oc_explicit"), current_session=lambda: "cc", base_dir=home)
    assert chat == "oc_explicit"
    assert err is None


def test_target_from_pointer(cli):
    mod, home = cli
    from ccremote import chat_pointer
    chat_pointer.write(home, "cc", "oc_from_pointer")
    chat, err = mod._resolve_notify_target(
        _args(), current_session=lambda: "cc", base_dir=home)
    assert chat == "oc_from_pointer"
    assert err is None


def test_target_no_session_errors(cli):
    mod, home = cli
    chat, err = mod._resolve_notify_target(
        _args(), current_session=lambda: None, base_dir=home)
    assert chat is None
    assert err and "tmux" in err.lower()


def test_target_no_pointer_errors(cli):
    mod, home = cli
    chat, err = mod._resolve_notify_target(
        _args(), current_session=lambda: "cc", base_dir=home)
    assert chat is None
    assert err and "cc" in err


# ---- content resolution ----

def test_content_positional_wins(cli):
    mod, _ = cli
    assert mod._resolve_notify_content(_args(message="done"), stdin=io.StringIO("ignored")) == "done"


def test_content_stdin_fallback(cli):
    mod, _ = cli
    assert mod._resolve_notify_content(_args(message=None), stdin=io.StringIO("from stdin\n")) == "from stdin"


def test_content_empty_returns_none(cli):
    mod, _ = cli
    assert mod._resolve_notify_content(_args(message="   "), stdin=io.StringIO("")) is None


# ---- end-to-end cmd_notify (feishu mocked) ----

def test_cmd_notify_sends_card_and_returns_0(cli, monkeypatch):
    mod, home = cli
    from ccremote import chat_pointer
    chat_pointer.write(home, "cc", "oc_target")

    sent = {}

    def fake_send_markdown(client, chat_id, md, fallback, header_title=None, **kw):
        sent.update(chat_id=chat_id, md=md, header=header_title)
        return True

    # Stub the lazy loaders cmd_notify uses so no real lark/creds are needed.
    monkeypatch.setattr(mod, "_notify_deps", lambda: types.SimpleNamespace(
        config=types.SimpleNamespace(
            APP_ID="cli_x", APP_SECRET="sec", CC_REMOTE_DIR=home,
            MAX_CARD_CHARS=8000, MAX_TEXT_CHARS=4000, load_env=lambda: home),
        feishu=types.SimpleNamespace(
            build_client=lambda a, b: object(), send_markdown=fake_send_markdown),
        tmux=types.SimpleNamespace(current_session=lambda: "cc"),
        chat_pointer=chat_pointer,
    ))

    rc = mod.cmd_notify(_args(message="task done"))
    assert rc == 0
    assert sent["chat_id"] == "oc_target"
    assert sent["md"] == "task done"
    assert sent["header"] == "🔔 任务通知"


def test_cmd_notify_no_target_returns_nonzero(cli, monkeypatch):
    mod, home = cli
    monkeypatch.setattr(mod, "_notify_deps", lambda: types.SimpleNamespace(
        config=types.SimpleNamespace(
            APP_ID="cli_x", APP_SECRET="sec", CC_REMOTE_DIR=home,
            MAX_CARD_CHARS=8000, MAX_TEXT_CHARS=4000, load_env=lambda: home),
        feishu=types.SimpleNamespace(build_client=lambda a, b: object(),
                                     send_markdown=lambda *a, **k: True),
        tmux=types.SimpleNamespace(current_session=lambda: "cc"),  # no pointer written
        chat_pointer=__import__("ccremote.chat_pointer", fromlist=["x"]),
    ))
    rc = mod.cmd_notify(_args(message="hi"))
    assert rc != 0
