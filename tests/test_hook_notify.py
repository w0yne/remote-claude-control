"""Tests for hook_notify reply truncation + card-markdown wiring.

The pure truncation helpers are tested directly. process_signals' send path is
tested with monkeypatched feishu/signals so no network or filesystem is needed
— asserting the reply goes out via send_markdown with the card text truncated
to MAX_CARD_CHARS and the fallback to MAX_TEXT_CHARS (the dual-ceiling rule).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hook_notify
from ccremote import config, feishu, signals, screenshot


def test_truncate_under_limit_unchanged():
    assert hook_notify._truncate("short", 100) == "short"


def test_truncate_over_limit_appends_notice():
    out = hook_notify._truncate("x" * 50, 10)
    assert out.startswith("x" * 10)
    assert "已截断" in out


def test_truncate_zero_limit_unchanged():
    # limit<=0 means "no truncation here" (the disable switch lives in extract).
    assert hook_notify._truncate("x" * 50, 0) == "x" * 50


def test_reply_payloads_uses_two_ceilings(monkeypatch):
    monkeypatch.setattr(config, "MAX_CARD_CHARS", 10)
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 5)
    card_md, text_fallback = hook_notify._reply_payloads("y" * 50)
    assert card_md.startswith("y" * 10) and "已截断" in card_md
    assert text_fallback.startswith("y" * 5) and "已截断" in text_fallback


def test_process_signals_replies_via_send_markdown(monkeypatch):
    monkeypatch.setattr(config, "MAX_CARD_CHARS", 10)
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 5)
    calls = []
    monkeypatch.setattr(feishu, "send_markdown",
                        lambda c, cid, md, fb, **k: calls.append((cid, md, fb)) or True)
    monkeypatch.setattr(feishu, "send_image", lambda *a, **k: True)
    monkeypatch.setattr(feishu, "del_reaction", lambda *a, **k: None)
    monkeypatch.setattr(feishu, "add_reaction", lambda *a, **k: None)
    monkeypatch.setattr(signals, "read_signal",
                        lambda sp: {"chat_id": "c1", "message_id": "m1", "reaction_id": "r1"})
    monkeypatch.setattr(screenshot, "safe_remove", lambda *a, **k: None)

    hook_notify.process_signals(object(), ["sig1"], "img.webp", "z" * 50)

    assert len(calls) == 1
    cid, md, fb = calls[0]
    assert cid == "c1"
    assert md.startswith("z" * 10) and "已截断" in md     # card ceiling
    assert fb.startswith("z" * 5) and "已截断" in fb       # text ceiling


def test_process_signals_empty_reply_sends_no_markdown(monkeypatch):
    calls = []
    monkeypatch.setattr(feishu, "send_markdown", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(feishu, "send_image", lambda *a, **k: True)
    monkeypatch.setattr(feishu, "del_reaction", lambda *a, **k: None)
    monkeypatch.setattr(feishu, "add_reaction", lambda *a, **k: None)
    monkeypatch.setattr(signals, "read_signal",
                        lambda sp: {"chat_id": "c1", "message_id": "m1", "reaction_id": "r1"})
    monkeypatch.setattr(screenshot, "safe_remove", lambda *a, **k: None)

    hook_notify.process_signals(object(), ["sig1"], "img.webp", "")  # no reply text

    assert calls == []  # screenshot still sent, but no card/text reply


# ---- footer (status-line style: model · ctx% · git branch) ----
import json


def test_pretty_model_maps_known_ids():
    assert hook_notify._pretty_model("claude-opus-4-8") == "Opus 4.8"
    assert hook_notify._pretty_model("claude-sonnet-4-6") == "Sonnet 4.6"
    assert hook_notify._pretty_model("claude-haiku-4-5-20251001") == "Haiku 4.5"


def test_pretty_model_unknown_returns_raw():
    assert hook_notify._pretty_model("claude-future-9-9") == "claude-future-9-9"
    assert hook_notify._pretty_model("") == ""


def test_fmt_tokens_like_statusline():
    assert hook_notify._fmt_tokens(1000000) == "1M"
    assert hook_notify._fmt_tokens(1234567) == "1.2M"
    assert hook_notify._fmt_tokens(190095) == "190K"
    assert hook_notify._fmt_tokens(559) == "0.6K"


def test_build_footer_full(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_WINDOW_SIZE", 1000000)
    foot = hook_notify.build_footer(
        {"model": "claude-opus-4-8", "ctx_tokens": 190095,
         "gitBranch": "dev-card-markdown", "dirty": True})
    assert "Opus 4.8" in foot
    assert "ctx 19% (190K/1M)" in foot
    assert "⎇ dev-card-markdown*" in foot   # dirty marker
    assert foot.count("·") == 2             # three segments joined by ·


def test_build_footer_skips_missing_segments(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_WINDOW_SIZE", 1000000)
    # only a model, no ctx, no branch
    foot = hook_notify.build_footer({"model": "claude-opus-4-8"})
    assert foot == "🤖 Opus 4.8"


def test_build_footer_clean_branch_no_star(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_WINDOW_SIZE", 1000000)
    foot = hook_notify.build_footer(
        {"gitBranch": "main", "dirty": False})
    assert "⎇ main" in foot and "*" not in foot


def test_build_footer_empty_meta_returns_empty():
    assert hook_notify.build_footer({}) == ""


def test_extract_turn_meta_reads_last_assistant(tmp_path):
    tp = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "gitBranch": "feature-x",
         "message": {"model": "claude-opus-4-8",
                     "usage": {"input_tokens": 5,
                               "cache_read_input_tokens": 100000,
                               "cache_creation_input_tokens": 2000}}},
    ]
    tp.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    meta = hook_notify.extract_turn_meta(str(tp))
    assert meta["model"] == "claude-opus-4-8"
    assert meta["ctx_tokens"] == 102005   # input + cache_read + cache_creation
    assert meta["gitBranch"] == "feature-x"


def test_extract_turn_meta_missing_file_returns_empty():
    assert hook_notify.extract_turn_meta("/no/such/path") == {}
