"""Linux systemd backend. The resident bridge runs as a systemd SYSTEM service
(/etc/systemd/system/ccremote-bridge.service, managed with sudo systemctl),
NOT a --user service. Targets Amazon Linux 2023 and Ubuntu on x86_64/arm64.

systemd does no ~ or env expansion: ExecStart needs an absolute interpreter,
PATH and locale must be set explicitly, and User= is mandatory (a system
service is root otherwise and would write root-owned files into ~/.cc_remote)."""
import getpass
import os
import subprocess
import tempfile

from .base import ServiceBackend, ServiceState, ServiceResult

UNIT_NAME = "ccremote-bridge.service"
UNIT_PATH = f"/etc/systemd/system/{UNIT_NAME}"
_LINUX_PATH_DIRS = ["/usr/local/bin", "/usr/bin", "/bin"]
_CHARM_YUM = ("add the charm repo (repo.charm.sh/yum/) then "
              "`sudo dnf install -y freeze` — see README")
_CHARM_APT = ("add the charm repo (repo.charm.sh/apt/) then "
              "`sudo apt install -y freeze` — see README")


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
    ServiceState. ActiveState=active + SubState=running + a real MainPID means
    running; SubState=auto-restart is a transient (crash-restart) window, not
    down; Result=start-limit-hit means systemd gave up after a crash loop."""
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


def _render_unit(user, pybin, bridge_py, workdir, log_path, daemon_path):
    """Render the systemd system-service unit. All paths must be absolute —
    systemd does no ~ or env expansion. Restart=on-failure + RestartSec=10
    mirror the macOS LaunchAgent's KeepAlive{SuccessfulExit:false} + throttle.

    No EnvironmentFile: the bridge loads ~/.cc_remote/.env itself via
    config.load_env() (python-dotenv), exactly like macOS launchd (which has
    no EnvironmentFile equivalent). Feeding .env through systemd's parser too
    would be redundant and risky — systemd's EnvironmentFile syntax differs
    from python-dotenv, and any PATH=/LANG= a user puts in .env would override
    the explicit UTF-8 locale below (which exists to prevent CJK crashes)."""
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
        f"StandardOutput=append:{log_path}\n"
        f"StandardError=append:{log_path}\n"
        "SyslogIdentifier=ccremote-bridge\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _stage_unit(content):
    """Write the unit content to a temp file the user owns; return its path.
    (Separated so start() is testable without touching /etc.)"""
    fd, path = tempfile.mkstemp(suffix=".service")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


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

    def start(self, pybin, bridge_py, workdir, env_file, log_path):
        # env_file is part of the shared start() contract; the bridge loads
        # .env itself (config.load_env), so the unit doesn't reference it.
        user = getpass.getuser()
        unit = _render_unit(user=user, pybin=pybin, bridge_py=bridge_py,
                            workdir=workdir, log_path=log_path,
                            daemon_path=self.daemon_path())
        staged = _stage_unit(unit)
        steps = [
            ["sudo", "cp", staged, UNIT_PATH],
            ["sudo", "systemctl", "daemon-reload"],
            ["sudo", "systemctl", "enable", "--now", UNIT_NAME],
        ]
        try:
            for cmd in steps:
                r = _run(cmd)
                if r.returncode != 0:
                    hint = ("\n  sudo may need a password or NOPASSWD; run these manually:\n    "
                            + "\n    ".join(" ".join(s) for s in steps))
                    return ServiceResult(False, f"{' '.join(cmd)} failed: {r.stderr.strip()}{hint}")
            return ServiceResult(True, f"started via systemd ({UNIT_NAME})")
        finally:
            try:
                os.unlink(staged)
            except OSError:
                pass

    def stop(self):
        # Success == the process is actually down. We don't gate on returncode
        # or LoadState: `disable --now` can return nonzero for benign reasons,
        # and the unit FILE lingers in /etc (LoadState stays 'loaded') until a
        # daemon-reload even after a clean stop. So check state().running, and
        # surface stderr only when the bridge is genuinely still up.
        r = _run(["sudo", "systemctl", "disable", "--now", UNIT_NAME])
        if self.state().running:
            detail = f": {r.stderr.strip()}" if r.stderr.strip() else ""
            return ServiceResult(False, f"systemctl disable failed{detail}")
        return ServiceResult(True, "stopped")

    def health_warnings(self):
        # The unit pins LANG/LC_ALL=en_US.UTF-8; if that locale isn't generated,
        # it's inert and CJK text/paths crash under systemd. Surface it so the
        # CLI needn't know anything Linux-specific.
        loc = _run(["locale", "-a"])
        has_utf8 = any("en_us.utf8" in l.lower() or "c.utf-8" in l.lower()
                       for l in loc.stdout.splitlines())
        return [("en_US.UTF-8 locale present", has_utf8,
                 "sudo locale-gen en_US.UTF-8  (Ubuntu) — prevents CJK crashes under systemd")]

    def tool_hints(self):
        distro = _distro_id()
        if distro in ("amzn", "rhel", "fedora", "centos"):
            return [
                ("freeze", _CHARM_YUM),
                ("cwebp", "sudo dnf install -y libwebp-tools"),
                ("tmux", "sudo dnf install -y tmux"),
            ]
        if distro in ("ubuntu", "debian"):
            return [
                ("freeze", _CHARM_APT),
                ("cwebp", "sudo apt install -y webp"),
                ("tmux", "sudo apt install -y tmux"),
            ]
        return [
            ("freeze", "install via your package manager or github.com/charmbracelet/freeze"),
            ("cwebp", "install your distro's webp / libwebp-tools package (provides cwebp)"),
            ("tmux", "install tmux via your package manager"),
        ]

    def python_dep_note(self):
        return ("create a venv and point CC_HOOK_PYTHON at it (PEP 668 blocks "
                "system pip):  python3 -m venv ~/.cc_remote/venv && "
                "~/.cc_remote/venv/bin/pip install lark-oapi python-dotenv  "
                "then set CC_HOOK_PYTHON=~/.cc_remote/venv/bin/python in ~/.cc_remote/.env")
