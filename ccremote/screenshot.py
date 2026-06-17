#!/usr/bin/env python3
"""
Shared terminal-screenshot helper used by both bridge.py (for /read) and
hook_notify.py (for the Stop-hook auto screenshot).

Captures a tmux pane (with ANSI color) and renders it to an image:
  tmux capture-pane -e  →  freeze (PNG)  →  cwebp (WebP)

Pure subprocess work, no Feishu/Lark dependency — callers send the resulting
file however they like.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime

# tmux/freeze/cwebp live in platform-specific bin dirs (Homebrew on macOS,
# /usr/bin etc. on Linux). Ask the platform backend so they're findable even
# under a minimal daemon PATH. Prepend, drop empties, stay idempotent.
def _platform_path_dirs():
    try:
        from ccremote import platform
        return platform.detect().extra_path_dirs()
    except Exception:
        # Never let PATH setup break screenshots; fall back to common dirs.
        return ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]


_existing = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
_prepend = [d for d in _platform_path_dirs() if d not in _existing]
os.environ["PATH"] = os.pathsep.join(_prepend + _existing)


def log(msg: str) -> None:
    print(f"[screenshot] {msg}", file=sys.stderr)


def safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"failed to remove {path}: {e}")


def safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def render(
    tmux_session: str,
    screenshot_dir: str,
    capture_lines: int = 0,
    webp_quality: int = 80,
) -> str:
    """Capture the tmux pane and render it to an image. Returns the path of the
    image to send (WebP, or PNG if cwebp is missing). Raises on capture/render
    failure. Intermediates go to a temp file; only the final image lands in
    screenshot_dir.

    capture_lines == 0 captures only the visible screen (no -S), so the height
    is fixed at the pane's row count — stable for a redrawing TUI.
    """
    cmd = ["tmux", "capture-pane", "-t", tmux_session, "-p", "-e"]
    if capture_lines > 0:
        cmd += ["-S", f"-{capture_lines}"]
    cap = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if not cap.stdout.strip():
        raise RuntimeError("tmux capture was empty")

    os.makedirs(screenshot_dir, exist_ok=True)
    # Microsecond + pid suffix so two renders in the same second don't collide.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_{os.getpid()}"
    png_path = os.path.join(screenshot_dir, f"{ts}.png")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(cap.stdout)
        txt_path = tf.name
    try:
        # --language ansi: capture holds raw ANSI color escapes (from -e);
        #   without it freeze guesses a language and fails ("Language Unknown").
        # stdin=DEVNULL: when stdin is not a TTY, freeze tries to read input
        #   FROM stdin and ignores the file arg ("No input"). /dev/null fixes it.
        result = subprocess.run(
            ["freeze", txt_path, "--language", "ansi", "-o", png_path],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not os.path.exists(png_path):
            raise RuntimeError(
                f"freeze exit {result.returncode}: "
                f"{result.stdout.strip()} {result.stderr.strip()}"
            )
    finally:
        safe_remove(txt_path)

    webp_path = os.path.join(screenshot_dir, f"{ts}.webp")
    try:
        subprocess.run(
            ["cwebp", "-q", str(webp_quality), png_path, "-o", webp_path],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=True,
        )
        if os.path.getsize(webp_path) > 0:
            safe_remove(png_path)
            return webp_path
        raise RuntimeError("cwebp produced an empty file")
    except Exception as e:
        log(f"cwebp conversion failed (using PNG): {e}")
        safe_remove(webp_path)
        return png_path


def prune_dir(dirpath: str, keep: int) -> None:
    """Keep only the `keep` most recently modified files in dirpath."""
    keep = max(1, keep)
    try:
        files = [
            os.path.join(dirpath, n)
            for n in os.listdir(dirpath)
            if os.path.isfile(os.path.join(dirpath, n))
        ]
        files.sort(key=safe_mtime, reverse=True)
        for stale in files[keep:]:
            safe_remove(stale)
    except Exception as e:
        log(f"prune failed: {e}")
