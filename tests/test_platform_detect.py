# tests/test_platform_detect.py
"""Tests for platform backend selection and the shared dataclasses.

detect() picks a backend by sys.platform; the dataclasses give the CLI a
uniform view of service state regardless of launchd vs systemd.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote import platform as plat
from ccremote.platform.base import ServiceState, ServiceResult, ServiceBackend


def test_detect_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    b = plat.detect()
    assert b.name == "darwin"
    assert isinstance(b, ServiceBackend)


def test_detect_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    b = plat.detect()
    assert b.name == "linux"
    assert isinstance(b, ServiceBackend)


def test_detect_unknown_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "sunos5")
    try:
        plat.detect()
        assert False, "expected NotImplementedError"
    except NotImplementedError as e:
        assert "sunos5" in str(e)


def test_servicestate_defaults():
    s = ServiceState(loaded=True, running=False)
    assert s.pid is None and s.last_exit is None and s.note == ""


def test_serviceresult_defaults():
    r = ServiceResult(ok=True)
    assert r.message == ""
