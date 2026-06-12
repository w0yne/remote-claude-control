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


def _render_plist(pybin, bridge_py, workdir, log_path):
    """Return the plist bytes for the LaunchAgent (matches the original
    cc-remote _write_plist exactly)."""
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [pybin, bridge_py],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "WorkingDirectory": workdir,
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "EnvironmentVariables": {
            "PATH": _DAEMON_PATH,
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
        },
    }
    return plistlib.dumps(plist)


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

    def start(self, pybin, bridge_py, workdir, env_file, log_path):
        os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
        with open(PLIST_PATH, "wb") as f:
            f.write(_render_plist(pybin, bridge_py, workdir, log_path))
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", PLIST_PATH],
                       capture_output=True)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", PLIST_PATH],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return ServiceResult(False, f"launchctl bootstrap failed: {r.stderr.strip()} "
                                        f"(plist at {PLIST_PATH})")
        return ServiceResult(True, f"started via launchd ({LAUNCHD_LABEL})")

    def stop(self):
        uid = os.getuid()
        r = subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCHD_LABEL}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["launchctl", "bootout", f"gui/{uid}", PLIST_PATH],
                           capture_output=True)
        if not self.state().loaded:
            return ServiceResult(True, "stopped")
        return ServiceResult(False, "launchd job still loaded — try again")

    def stray_processes(self):
        managed = self.state().pid
        managed_s = str(managed) if managed else None
        return [p for p in _pgrep_bridge() if p != managed_s]
