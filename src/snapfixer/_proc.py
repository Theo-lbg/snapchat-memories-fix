"""subprocess.run wrapper that keeps a console window from flashing up on
Windows for every ffmpeg/ffprobe call made by the windowed GUI app."""

from __future__ import annotations

import subprocess
import sys

_WIN_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    if _WIN_FLAGS:
        kwargs.setdefault("creationflags", _WIN_FLAGS)
    return subprocess.run(cmd, **kwargs)
