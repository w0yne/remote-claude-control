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
