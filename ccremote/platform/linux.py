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


def _render_unit(user, pybin, bridge_py, workdir, env_file, log_path, daemon_path):
    """Render the systemd system-service unit. All paths must be absolute —
    systemd does no ~ or env expansion. Mapping from the macOS launchd plist is
    documented in the facts brief."""
    return (
        "[Unit]\n"
        "Description=cc-remote Feishu bridge (WebSocket client daemon)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={user}\n"
        f"WorkingDirectory={workdir}\n"
        f"ExecStart={pybin} {bridge_py}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        f"Environment=PATH={daemon_path}\n"
        "Environment=LANG=en_US.UTF-8\n"
        "Environment=LC_ALL=en_US.UTF-8\n"
        f"EnvironmentFile=-{env_file}\n"
        f"StandardOutput=append:{log_path}\n"
        f"StandardError=append:{log_path}\n"
        "SyslogIdentifier=ccremote-bridge\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


class SystemdBackend(ServiceBackend):
    name = "linux"
    service_label = UNIT_NAME

    def extra_path_dirs(self):
        return list(_LINUX_PATH_DIRS)
