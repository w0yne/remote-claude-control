# tests/test_platform_linux.py
"""Tests for the Linux systemd backend. /etc/os-release reading, unit-file
rendering, and systemctl parsing are split into pure functions so these run
offline on macOS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ccremote.platform.linux import SystemdBackend, _parse_os_release


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
