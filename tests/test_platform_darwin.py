# tests/test_platform_darwin.py
"""Tests for the macOS launchd backend. subprocess/launchctl is mocked or
parsing is split into pure functions, so these run offline on any OS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote.platform.darwin import LaunchdBackend, _parse_launchctl_list


def test_extra_path_dirs_are_homebrew():
    b = LaunchdBackend()
    dirs = b.extra_path_dirs()
    assert dirs == ["/opt/homebrew/bin", "/usr/local/bin"]


def test_daemon_path_includes_system_dirs():
    b = LaunchdBackend()
    # daemon env needs system dirs too (launchd provides no PATH)
    assert b.daemon_path() == "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def test_tool_hints_use_brew():
    b = LaunchdBackend()
    hints = dict(b.tool_hints())
    assert "brew install" in hints["freeze"]
    assert hints["cwebp"] == "brew install webp"
    assert hints["tmux"] == "brew install tmux"


def test_python_dep_note_mentions_pip():
    assert "pip install" in LaunchdBackend().python_dep_note()


def test_service_label_unchanged():
    assert LaunchdBackend().service_label == "com.ccremote.bridge"


def test_parse_launchctl_running():
    # Real `launchctl list com.ccremote.bridge` shape (abbreviated).
    text = '''{
	"LimitLoadToSessionType" = "Aqua";
	"Label" = "com.ccremote.bridge";
	"LastExitStatus" = 0;
	"PID" = 12345;
}'''
    st = _parse_launchctl_list(text, returncode=0)
    assert st.loaded is True
    assert st.running is True
    assert st.pid == 12345
    assert st.last_exit == 0


def test_parse_launchctl_loaded_not_running_crashed():
    text = '''{
	"Label" = "com.ccremote.bridge";
	"LastExitStatus" = 1;
}'''
    st = _parse_launchctl_list(text, returncode=0)
    assert st.loaded is True
    assert st.running is False
    assert st.pid is None
    assert st.last_exit == 1


def test_parse_launchctl_not_loaded():
    st = _parse_launchctl_list("", returncode=1)
    assert st.loaded is False
    assert st.running is False
    assert st.pid is None
