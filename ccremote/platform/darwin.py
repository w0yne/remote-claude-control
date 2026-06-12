"""macOS launchd backend. The resident bridge runs as a per-user LaunchAgent
(~/Library/LaunchAgents/com.ccremote.bridge.plist). This is the existing
behavior, moved out of cc-remote verbatim so macOS is byte-for-byte unchanged."""
import os
import plistlib
import subprocess

from .base import ServiceBackend, ServiceState, ServiceResult, _pgrep_bridge

LAUNCHD_LABEL = "com.ccremote.bridge"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")
# Homebrew dirs for tmux/freeze/cwebp; system dirs appended for the daemon env.
_HOMEBREW_DIRS = ["/opt/homebrew/bin", "/usr/local/bin"]
_DAEMON_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def _parse_launchctl_list(text, returncode):
    """Parse `launchctl list <label>` output into a ServiceState.
    returncode != 0 means the job isn't loaded."""
    if returncode != 0:
        return ServiceState(loaded=False, running=False)
    pid, last_exit = None, None
    for line in text.splitlines():
        s = line.strip().rstrip(";").replace('"', "")  # launchctl prints plist-style: "PID" = 12345;
        if s.startswith("PID ="):
            v = s.split("=", 1)[1].strip()
            pid = int(v) if v.isdigit() and v != "0" else None  # PID=0 means loaded-but-not-running (launchd convention)
        elif s.startswith("LastExitStatus ="):
            v = s.split("=", 1)[1].strip()
            last_exit = int(v) if v.lstrip("-").isdigit() else None
    return ServiceState(loaded=True, running=pid is not None,
                        pid=pid, last_exit=last_exit)


class LaunchdBackend(ServiceBackend):
    name = "darwin"
    service_label = LAUNCHD_LABEL

    def extra_path_dirs(self):
        return list(_HOMEBREW_DIRS)

    def daemon_path(self):
        return _DAEMON_PATH

    def tool_hints(self):
        return [
            ("freeze", "brew install charmbracelet/tap/freeze"),
            ("cwebp", "brew install webp"),
            ("tmux", "brew install tmux"),
        ]

    def python_dep_note(self):
        return "pip install lark-oapi python-dotenv"

    def state(self):
        out = subprocess.run(["launchctl", "list", LAUNCHD_LABEL],
                             capture_output=True, text=True)
        return _parse_launchctl_list(out.stdout, out.returncode)
