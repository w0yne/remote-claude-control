"""Tests for `cc-remote projects` subcommand (registry management).

The critical safety property: `projects add` registers a project WITHOUT
touching any project's .claude/settings.json or any tmux session — it just
records an already-running session in the registry, so a live session can be
registered without re-running setup on it.

cc-remote is an extension-less executable; load it via importlib with a
__file__ injected (the loader needs it for the module's own path logic).
"""

import importlib.util
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
    return types.SimpleNamespace(**kw)


def test_projects_add_writes_registry(cli):
    mod, home = cli
    from ccremote import registry
    rc = mod.cmd_projects(_args(action="add", alias="cc", session="cc",
                                dir="/Users/me/dev/x"))
    assert rc == 0
    assert registry.get(home, "cc") == {
        "session": "cc", "dir": "/Users/me/dev/x", "claude_session_id": None,
    }


def test_projects_add_does_not_touch_settings_json(cli, tmp_path):
    """add must NOT create or modify a .claude/settings.json anywhere — it only
    records a running session, so an already-running session can be registered
    without re-running setup on it."""
    mod, home = cli
    proj_dir = tmp_path / "someproj"
    proj_dir.mkdir()
    mod.cmd_projects(_args(action="add", alias="p", session="s",
                           dir=str(proj_dir)))
    assert not (proj_dir / ".claude").exists()
    assert not (proj_dir / ".claude" / "settings.json").exists()


def test_projects_rm(cli):
    mod, home = cli
    from ccremote import registry
    registry.add(home, "p", session="s", dir="/a")
    rc = mod.cmd_projects(_args(action="rm", alias="p"))
    assert rc == 0
    assert registry.get(home, "p") is None


def test_projects_list_runs_clean_on_empty(cli, capsys):
    mod, home = cli
    rc = mod.cmd_projects(_args(action="list"))
    assert rc == 0


def test_registry_summary_reports_count_and_active(cli):
    mod, home = cli
    from ccremote import registry
    registry.add(home, "cc", session="cc", dir="/d/cc")
    registry.add(home, "web", session="cc-web", dir="/d/web")
    registry.write_active(home, "cc")
    summary = mod._registry_summary()
    assert "2" in summary           # two registered projects
    assert "cc" in summary          # active session shown


def test_registry_summary_empty(cli):
    mod, home = cli
    summary = mod._registry_summary()
    assert summary  # non-empty, doesn't crash on empty registry
