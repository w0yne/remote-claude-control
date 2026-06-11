"""Shared library for the Feishu → tmux → Claude Code remote-control tool.

Entrypoints (bridge.py, hook_notify.py) and the cc-remote CLI import from here.
Keep config.py dependency-free (stdlib + dotenv) so the CLI can import it even
when lark_oapi is missing; heavy imports (lark_oapi) live in feishu.py only.
"""

__version__ = "0.2.0"
