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


def _parse_systemctl_show(text):
    """Parse `systemctl show <unit> --property=...` key=value output into a
    ServiceState. See facts brief 4 for the property semantics."""
    kv = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
    active = kv.get("ActiveState", "")
    sub = kv.get("SubState", "")
    pid_raw = kv.get("MainPID", "0")
    pid = int(pid_raw) if pid_raw.isdigit() and pid_raw != "0" else None
    exit_raw = kv.get("ExecMainStatus", "")
    last_exit = int(exit_raw) if exit_raw.lstrip("-").isdigit() else None
    note_bits = []
    if sub == "auto-restart":
        note_bits.append("auto-restart (transient)")
    if kv.get("Result") == "start-limit-hit":
        note_bits.append("start-limit-hit (run: systemctl reset-failed)")
    if active == "failed":
        note_bits.append("failed")
    return ServiceState(
        loaded=kv.get("LoadState") == "loaded",
        running=(active == "active" and sub == "running" and pid is not None),
        pid=pid,
        last_exit=last_exit,
        note="; ".join(note_bits),
    )


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
    _SHOW_PROPS = ["ActiveState", "SubState", "MainPID", "ExecMainStatus",
                   "Result", "LoadState", "UnitFileState", "NRestarts"]

    def extra_path_dirs(self):
        return list(_LINUX_PATH_DIRS)

    def state(self):
        out = subprocess.run(
            ["systemctl", "show", UNIT_NAME,
             "--property=" + ",".join(self._SHOW_PROPS), "--no-pager"],
            capture_output=True, text=True)
        return _parse_systemctl_show(out.stdout)
