# tests/test_platform_linux.py
"""Tests for the Linux systemd backend. /etc/os-release reading, unit-file
rendering, and systemctl parsing are split into pure functions so these run
offline on macOS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote.platform.linux import SystemdBackend, _parse_os_release, _render_unit, _parse_systemctl_show


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
