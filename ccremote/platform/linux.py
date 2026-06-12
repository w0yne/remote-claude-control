"""Linux systemd backend. The resident bridge runs as a systemd SYSTEM service
(/etc/systemd/system/ccremote-bridge.service, managed with sudo systemctl),
NOT a --user service. Targets Amazon Linux 2023 and Ubuntu on x86_64/arm64.

systemd does no ~ or env expansion: ExecStart needs an absolute interpreter,
PATH and locale must be set explicitly, and User= is mandatory (a system
service is root otherwise and would write root-owned files into ~/.cc_remote).
See docs/tech/2026-06-12T13-16-linux-support-facts-brief.md."""
import getpass
import os
import subprocess

from .base import ServiceBackend, ServiceState, ServiceResult, _pgrep_bridge

UNIT_NAME = "ccremote-bridge.service"
UNIT_PATH = f"/etc/systemd/system/{UNIT_NAME}"
_LINUX_PATH_DIRS = ["/usr/local/bin", "/usr/bin", "/bin"]


def _parse_os_release(text):
    """Return the distro ID from /etc/os-release text ('amzn','ubuntu',...), or ''."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ID="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _distro_id():
    try:
        with open("/etc/os-release") as f:
            return _parse_os_release(f.read())
    except OSError:
        return ""


class SystemdBackend(ServiceBackend):
    name = "linux"
    service_label = UNIT_NAME

    def extra_path_dirs(self):
        return list(_LINUX_PATH_DIRS)
