"""Tests for ccremote.config env→constant refresh."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import config


def test_max_card_chars_default(monkeypatch):
    monkeypatch.delenv("MAX_CARD_CHARS", raising=False)
    config._refresh()
    assert config.MAX_CARD_CHARS == 8000


def test_max_card_chars_from_env(monkeypatch):
    monkeypatch.setenv("MAX_CARD_CHARS", "12000")
    config._refresh()
    assert config.MAX_CARD_CHARS == 12000
    monkeypatch.delenv("MAX_CARD_CHARS", raising=False)
    config._refresh()  # restore default so other tests see 8000


def test_card_footer_default_on(monkeypatch):
    monkeypatch.delenv("CARD_FOOTER", raising=False)
    config._refresh()
    assert config.CARD_FOOTER is True


def test_card_footer_off_via_env(monkeypatch):
    for v in ("false", "0", "no", "off", "FALSE"):
        monkeypatch.setenv("CARD_FOOTER", v)
        config._refresh()
        assert config.CARD_FOOTER is False, v
    monkeypatch.delenv("CARD_FOOTER", raising=False)
    config._refresh()  # restore default


def test_context_window_size_default(monkeypatch):
    monkeypatch.delenv("CONTEXT_WINDOW_SIZE", raising=False)
    config._refresh()
    assert config.CONTEXT_WINDOW_SIZE == 200000


def test_context_window_size_from_env(monkeypatch):
    monkeypatch.setenv("CONTEXT_WINDOW_SIZE", "1000000")
    config._refresh()
    assert config.CONTEXT_WINDOW_SIZE == 1000000
    monkeypatch.delenv("CONTEXT_WINDOW_SIZE", raising=False)
    config._refresh()  # restore default
