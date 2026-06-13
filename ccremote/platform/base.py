# ccremote/platform/base.py
import os
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServiceState:
    """Unified view of the resident bridge service across launchd/systemd."""
    loaded: bool                 # service definition is known to the init system
    running: bool                # a live process exists right now
    pid: Optional[int] = None
    last_exit: Optional[int] = None
    note: str = ""               # transient/extra: systemd 'auto-restart', 'start-limit-hit', etc.


@dataclass
class ServiceResult:
    ok: bool
    message: str = ""


class ServiceBackend:
    """OS-specific management of the resident bridge daemon + dep hints.

    Subclasses: LaunchdBackend (macOS), SystemdBackend (Linux). The CLI keeps
    all orchestration/printing/credential-checks and calls ONLY these methods
    for OS-specific mechanics."""

    name = "base"
    service_label = "com.ccremote.bridge"

    def extra_path_dirs(self) -> list:
        """Dirs to PREPEND to PATH so tmux/freeze/cwebp resolve (screenshot.py
        + daemon env). macOS: Homebrew dirs. Linux: standard bin dirs."""
        raise NotImplementedError

    def daemon_path(self) -> str:
        """The PATH *value* baked into the service definition (os.pathsep-joined)."""
        return os.pathsep.join(self.extra_path_dirs())

    def start(self, pybin: str, bridge_py: str, workdir: str,
              env_file: str, log_path: str) -> ServiceResult:
        """Write the service definition and (re)load+start it. Idempotent."""
        raise NotImplementedError

    def stop(self) -> ServiceResult:
        raise NotImplementedError

    def state(self) -> ServiceState:
        raise NotImplementedError

    def stray_processes(self, managed_pid="__fetch__") -> list:
        """PIDs (as str) of bridge.py processes NOT managed by this backend.

        Identical across launchd/systemd, so it lives here. Pass managed_pid
        when the caller already has state() in hand, to skip a redundant
        launchctl/systemctl subprocess (and the TOCTOU window between the two
        reads — a relaunch in between would otherwise flag the fresh managed
        process as a stray). Pass managed_pid=None to mean 'nothing is managed'
        (e.g. right after stop()), so every live bridge.py counts as stray.
        Omit it entirely (the default) to fetch the managed pid via state()."""
        if managed_pid == "__fetch__":
            managed_pid = self.state().pid
        managed_s = str(managed_pid) if managed_pid else None
        return [p for p in _pgrep_bridge() if p != managed_s]

    def health_warnings(self) -> list:
        """Extra OS-specific doctor checks: [(label, ok_bool, hint), ...].
        Empty by default; the CLI stays platform-agnostic and just loops these."""
        return []

    def tool_hints(self) -> list:
        """[(tool_name, install_hint_str), ...] for freeze/cwebp/tmux."""
        raise NotImplementedError

    def python_dep_note(self) -> str:
        """One-line hint on how to get lark-oapi/python-dotenv on this OS."""
        raise NotImplementedError


def _pgrep_bridge() -> list:
    """All PIDs (str) whose cmdline matches bridge.py. Used by both backends."""
    out = subprocess.run(["pgrep", "-f", "bridge.py"], capture_output=True, text=True)
    return [p for p in out.stdout.split() if p]
