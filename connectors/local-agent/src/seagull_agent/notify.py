from __future__ import annotations

import platform
import shutil
import subprocess


def desktop_notify(title: str, body: str) -> bool:
    if platform.system() != "Darwin" or shutil.which("osascript") is None:
        return False

    script = f'display notification {applescript_string(body)} with title {applescript_string(title)}'
    completed = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
