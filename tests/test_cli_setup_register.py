"""Test that `cc-remote setup --name <alias>` registers the project.

Uses --no-launch to avoid tmux. A fake installed BIN (hook_notify.py + package
marker) is staged so setup's install-check passes. Verifies the registry gets
the alias, and that omitting --name keeps the old (no-registry) behavior.
"""

import importlib.util
import os
import types

import pytest

CC_REMOTE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cc-remote"
)


def _load_cc_remote():
    spec = importlib.util.spec_from_loader(
        "cc_remote_cli2",
        importlib.machinery.SourceFileLoader("cc_remote_cli2", CC_REMOTE),
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = CC_REMOTE
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli(tmp_path, monkeypatch):
    mod = _load_cc_remote()
    home = tmp_path / "home"
    binp = home / "bin"
    (binp / "ccremote").mkdir(parents=True)
    (binp / "hook_notify.py").write_text("# stub\n")
    (binp / "ccremote" / "__init__.py").write_text("# stub\n")
    monkeypatch.setattr(mod, "HOME", str(home))
    monkeypatch.setattr(mod, "BIN", str(binp))
    monkeypatch.setattr(mod, "ENV_FILE", str(home / ".env"))
    return mod, str(home)


def _setup_args(target, name=None, session=None):
    return types.SimpleNamespace(
        dir=target, claude_cmd="claude", no_launch=True, name=name, session=session
    )


def test_setup_with_name_registers_project(cli, tmp_path):
    mod, home = cli
    from ccremote import registry
    proj = tmp_path / "myproj"
    proj.mkdir()
    rc = mod.cmd_setup(_setup_args(str(proj), name="myproj", session="cc-myproj"))
    assert rc == 0
    entry = registry.get(home, "myproj")
    assert entry["session"] == "cc-myproj"
    assert entry["dir"] == str(proj)


def test_setup_name_defaults_session_to_alias(cli, tmp_path):
    mod, home = cli
    from ccremote import registry
    proj = tmp_path / "p2"
    proj.mkdir()
    mod.cmd_setup(_setup_args(str(proj), name="p2"))  # no --session
    assert registry.get(home, "p2")["session"] == "p2"


def test_setup_without_name_does_not_register(cli, tmp_path):
    mod, home = cli
    from ccremote import registry
    proj = tmp_path / "p3"
    proj.mkdir()
    mod.cmd_setup(_setup_args(str(proj)))  # no --name
    assert registry.load(home) == {}
