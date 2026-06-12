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

    def stray_processes(self) -> list:
        """PIDs (as str) of bridge.py processes NOT managed by this backend."""
        raise NotImplementedError

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
