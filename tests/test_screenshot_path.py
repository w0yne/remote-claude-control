# tests/test_screenshot_path.py
"""screenshot.py prepends platform-appropriate bin dirs to PATH so tmux/freeze/
cwebp resolve under a minimal daemon PATH. macOS keeps Homebrew dirs; Linux uses
standard bin dirs. We assert the helper picks them from the platform backend."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_path_dirs_come_from_backend(monkeypatch):
    from ccremote import screenshot
    dirs = screenshot._platform_path_dirs()
    # Whatever the host backend says — non-empty list of abs dirs.
    assert isinstance(dirs, list) and dirs
    assert all(d.startswith("/") for d in dirs)


def test_import_prepends_dirs_to_path(monkeypatch):
    # After import, the backend dirs are on PATH (idempotent prepend).
    from ccremote import screenshot
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    for d in screenshot._platform_path_dirs():
        assert d in path_parts
