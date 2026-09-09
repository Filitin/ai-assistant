# src/tray.py
"""
System tray process. Run independently via Task Scheduler.
Right-click menu: Open Assistant, Exit.
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw
import pystray

PROJECT_ROOT = Path(__file__).parent.parent


def _make_icon() -> Image.Image:
    """Generate a simple circular icon programmatically."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Outer circle — Catppuccin Mauve
    draw.ellipse([2, 2, size - 2, size - 2], fill="#cba6f7")
    # Inner dot — dark background
    cx, cy, r = size // 2, size // 2, size // 6
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#1e1e2e")
    return img


def _open_assistant(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    subprocess.Popen(
        ["powershell.exe", "-NoExit", "-Command",
         f"cd '{PROJECT_ROOT}'; python -m src.main"],
        cwd=PROJECT_ROOT,
    )


def _exit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    icon.stop()


def main() -> None:
    icon = pystray.Icon(
        name="ai_assistant",
        icon=_make_icon(),
        title="AI Assistant",
        menu=pystray.Menu(
            pystray.MenuItem("Open Assistant", _open_assistant, default=True),
            pystray.MenuItem("Exit", _exit),
        ),
    )
    icon.run()


if __name__ == "__main__":
    main()