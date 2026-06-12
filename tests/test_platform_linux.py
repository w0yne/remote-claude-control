# tests/test_platform_linux.py
"""Tests for the Linux systemd backend. /etc/os-release reading, unit-file
rendering, and systemctl parsing are split into pure functions so these run
offline on macOS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote.platform.linux import SystemdBackend, _parse_os_release, _render_unit, _parse_systemctl_show, UNIT_NAME


def test_parse_os_release_amzn():
    text = 'NAME="Amazon Linux"\nID="amzn"\nVERSION_ID="2023"\n'
    assert _parse_os_release(text) == "amzn"


def test_parse_os_release_ubuntu():
    text = 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n'
    assert _parse_os_release(text) == "ubuntu"


def test_parse_os_release_missing_id():
    assert _parse_os_release("NAME=Whatever\n") == ""


def test_extra_path_dirs_are_standard_linux():
    b = SystemdBackend()
    assert b.extra_path_dirs() == ["/usr/local/bin", "/usr/bin", "/bin"]


def test_daemon_path_is_standard_linux():
    assert SystemdBackend().daemon_path() == "/usr/local/bin:/usr/bin:/bin"


def test_service_label_is_unit_name():
    assert SystemdBackend().service_label == "ccremote-bridge.service"


def test_render_unit_has_required_fields():
    unit = _render_unit(
        user="ec2-user", pybin="/home/ec2-user/.cc_remote/venv/bin/python",
        bridge_py="/home/ec2-user/.cc_remote/bin/bridge.py",
        workdir="/home/ec2-user/.cc_remote",
        env_file="/home/ec2-user/.cc_remote/.env",
        log_path="/home/ec2-user/.cc_remote/bridge.log",
        daemon_path="/usr/local/bin:/usr/bin:/bin",
    )
    # User= is mandatory (else root) — the single biggest systemd gotcha.
    assert "User=ec2-user" in unit
    # ExecStart uses ABSOLUTE interpreter (no PATH lookup for arg0).
    assert "ExecStart=/home/ec2-user/.cc_remote/venv/bin/python /home/ec2-user/.cc_remote/bin/bridge.py" in unit
    # KeepAlive{SuccessfulExit:false} == Restart=on-failure; ThrottleInterval=10 == RestartSec=10
    assert "Restart=on-failure" in unit
    assert "RestartSec=10" in unit
    assert "WorkingDirectory=/home/ec2-user/.cc_remote" in unit
    assert "Environment=PATH=/usr/local/bin:/usr/bin:/bin" in unit
    assert "Environment=LANG=en_US.UTF-8" in unit
    assert "Environment=LC_ALL=en_US.UTF-8" in unit
    assert "EnvironmentFile=-/home/ec2-user/.cc_remote/.env" in unit
    assert "StandardOutput=append:/home/ec2-user/.cc_remote/bridge.log" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "Wants=network-online.target" in unit


def test_parse_systemctl_active_running():
    text = ("ActiveState=active\nSubState=running\nMainPID=4242\n"
            "ExecMainStatus=0\nResult=success\nLoadState=loaded\n"
            "UnitFileState=enabled\nNRestarts=0\n")
    st = _parse_systemctl_show(text)
    assert st.loaded is True
    assert st.running is True
    assert st.pid == 4242
    assert st.last_exit == 0


def test_parse_systemctl_auto_restart_is_transient_not_down():
    text = ("ActiveState=activating\nSubState=auto-restart\nMainPID=0\n"
            "ExecMainStatus=1\nResult=exit-code\nLoadState=loaded\n"
            "UnitFileState=enabled\nNRestarts=3\n")
    st = _parse_systemctl_show(text)
    assert st.loaded is True
    assert st.running is False
    assert st.pid is None
    assert "auto-restart" in st.note


def test_parse_systemctl_start_limit_hit():
    text = ("ActiveState=failed\nSubState=failed\nMainPID=0\n"
            "ExecMainStatus=1\nResult=start-limit-hit\nLoadState=loaded\n"
            "UnitFileState=enabled\nNRestarts=5\n")
    st = _parse_systemctl_show(text)
    assert st.running is False
    assert "start-limit-hit" in st.note


def test_parse_systemctl_not_loaded():
    text = "ActiveState=inactive\nSubState=dead\nMainPID=0\nLoadState=not-found\n"
    st = _parse_systemctl_show(text)
    assert st.loaded is False
    assert st.running is False


def test_start_writes_unit_and_runs_systemctl(monkeypatch, tmp_path):
    import ccremote.platform.linux as lx
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    monkeypatch.setattr(lx.subprocess, "run", fake_run)
    # capture the rendered unit instead of writing to /etc
    written = {}
    monkeypatch.setattr(lx, "_stage_unit", lambda content: written.setdefault("c", content) or "/tmp/x.service")
    monkeypatch.setattr(lx.getpass, "getuser", lambda: "ec2-user")

    b = lx.SystemdBackend()
    res = b.start(
        pybin="/opt/venv/bin/python", bridge_py="/home/ec2-user/.cc_remote/bin/bridge.py",
        workdir="/home/ec2-user/.cc_remote", env_file="/home/ec2-user/.cc_remote/.env",
        log_path="/home/ec2-user/.cc_remote/bridge.log",
    )
    assert res.ok is True
    assert "User=ec2-user" in written["c"]
    flat = [" ".join(c) for c in calls]
    assert any("daemon-reload" in f for f in flat)
    assert any("enable" in f and "--now" in f and UNIT_NAME in f for f in flat)


def test_stop_runs_disable_now(monkeypatch):
    import ccremote.platform.linux as lx
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    monkeypatch.setattr(lx.subprocess, "run", fake_run)
    b = lx.SystemdBackend()
    monkeypatch.setattr(b, "state", lambda: lx.ServiceState(loaded=False, running=False))
    res = b.stop()
    assert res.ok is True
    flat = [" ".join(c) for c in calls]
    assert any("disable" in f and "--now" in f for f in flat)


def test_stray_processes_excludes_managed(monkeypatch):
    import ccremote.platform.linux as lx
    monkeypatch.setattr(lx, "_pgrep_bridge", lambda: ["100", "200"])
    b = lx.SystemdBackend()
    monkeypatch.setattr(b, "state", lambda: lx.ServiceState(loaded=True, running=True, pid=200))
    assert b.stray_processes() == ["100"]


def test_tool_hints_amzn(monkeypatch):
    import ccremote.platform.linux as lx
    monkeypatch.setattr(lx, "_distro_id", lambda: "amzn")
    hints = dict(lx.SystemdBackend().tool_hints())
    assert hints["cwebp"] == "sudo dnf install -y libwebp-tools"   # verified on live AL2023
    assert hints["tmux"] == "sudo dnf install -y tmux"
    assert "repo.charm.sh" in hints["freeze"]


def test_tool_hints_ubuntu(monkeypatch):
    import ccremote.platform.linux as lx
    monkeypatch.setattr(lx, "_distro_id", lambda: "ubuntu")
    hints = dict(lx.SystemdBackend().tool_hints())
    assert hints["cwebp"] == "sudo apt install -y webp"            # NOT libwebp-tools on Ubuntu
    assert hints["tmux"] == "sudo apt install -y tmux"
    assert "repo.charm.sh" in hints["freeze"]


def test_tool_hints_unknown_distro_generic(monkeypatch):
    import ccremote.platform.linux as lx
    monkeypatch.setattr(lx, "_distro_id", lambda: "")
    hints = dict(lx.SystemdBackend().tool_hints())
    # Generic, non-failing guidance.
    assert "tmux" in hints["tmux"].lower()
    assert "github.com/charmbracelet/freeze" in hints["freeze"]


def test_python_dep_note_mentions_venv():
    import ccremote.platform.linux as lx
    note = lx.SystemdBackend().python_dep_note()
    assert "venv" in note
    assert "CC_HOOK_PYTHON" in note
