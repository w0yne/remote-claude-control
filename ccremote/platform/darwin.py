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
