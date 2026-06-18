"""Platform backends for the resident bridge daemon (launchd / systemd).

Pure stdlib so the CLI can import it before anything is installed. detect()
returns the right backend for the host OS; the CLI calls only the backend
interface for OS-specific mechanics (screenshot.py also asks for PATH dirs)."""
import sys

from .base import ServiceBackend, ServiceState, ServiceResult

__all__ = ["detect", "ServiceBackend", "ServiceState", "ServiceResult"]


def detect() -> ServiceBackend:
    if sys.platform == "darwin":
        from .darwin import LaunchdBackend
        return LaunchdBackend()
    if sys.platform.startswith("linux"):
        from .linux import SystemdBackend
        return SystemdBackend()
    raise NotImplementedError(
        f"cc-remote has no service backend for platform {sys.platform!r} "
        "(supported: darwin, linux)"
    )
