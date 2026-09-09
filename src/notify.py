# src/notify.py
"""
Standalone banner notification window. Fluent Design, theme-adaptive.
Usage:
    python -m src.notify --title "Timer" --message "Done" --mode auto
    python -m src.notify --title "Reminder" --message "Task due" --mode confirm --item-id 3
"""

import argparse
import sys
import winreg
import winsound
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path

BANNER_WIDTH = 380
BANNER_HEIGHT_AUTO = 100
BANNER_HEIGHT_CONFIRM = 148
AUTO_TIMEOUT_MS = 6000

# ── Fluent light theme ───────────────────────────────────────────────────────
LIGHT = {
    "bg":           "#f3f3f3",
    "bg2":          "#ebebeb",
    "text":         "#1a1a1a",
    "subtext":      "#4a4a4a",
    "accent":       "#0067c0",       # Windows 11 default blue
    "btn_primary":  "#0067c0",
    "btn_primary_fg": "#ffffff",
    "btn_secondary": "#e0e0e0",
    "btn_secondary_fg": "#1a1a1a",
    "bar":          "#0067c0",
    "border":       "#d0d0d0",
}

# ── Fluent dark theme ────────────────────────────────────────────────────────
DARK = {
    "bg":           "#202020",
    "bg2":          "#2d2d2d",
    "text":         "#ffffff",
    "subtext":      "#c0c0c0",
    "accent":       "#60cdff",       # Windows 11 dark mode blue
    "btn_primary":  "#60cdff",
    "btn_primary_fg": "#000000",
    "btn_secondary": "#3d3d3d",
    "btn_secondary_fg": "#ffffff",
    "bar":          "#60cdff",
    "border":       "#3a3a3a",
}


def _get_theme() -> dict:
    """Read Windows AppsUseLightTheme registry key. Returns DARK or LIGHT palette."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return LIGHT if value == 1 else DARK
    except OSError:
        return DARK  # safe default


def _place_bottom_right(win: tk.Tk, width: int, height: int) -> None:
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    x = screen_w - width - 16
    y = screen_h - height - 56   # above taskbar
    win.geometry(f"{width}x{height}+{x}+{y}")


def _play_sound(mode: str) -> None:
    """
    auto    → short single ding (MessageBeep default)
    confirm → two-tone alert (Exclamation)
    """
    if mode == "auto":
        winsound.MessageBeep(winsound.MB_OK)
    else:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)


def _build_window(width: int, height: int, t: dict) -> tk.Tk:
    win = tk.Tk()
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.97)
    win.configure(bg=t["bg"])
    _place_bottom_right(win, width, height)

    # Thin accent border on top
    accent_bar = tk.Frame(win, bg=t["accent"], height=3)
    accent_bar.pack(fill="x", side="top")

    # Outer border illusion via 1px frame
    win.configure(highlightbackground=t["border"],
                  highlightcolor=t["border"],
                  highlightthickness=1)
    return win


def show_auto(title: str, message: str, timeout_ms: int = AUTO_TIMEOUT_MS) -> None:
    t = _get_theme()
    win = _build_window(BANNER_WIDTH, BANNER_HEIGHT_AUTO, t)

    title_font  = tkfont.Font(family="Segoe UI Semibold", size=10, weight="bold")
    msg_font    = tkfont.Font(family="Segoe UI", size=9)

    content = tk.Frame(win, bg=t["bg"])
    content.pack(fill="both", expand=True, padx=14, pady=8)

    tk.Label(content, text=title, font=title_font,
             bg=t["bg"], fg=t["text"],
             anchor="w").pack(fill="x")

    tk.Label(content, text=message, font=msg_font,
             bg=t["bg"], fg=t["subtext"],
             anchor="w", wraplength=BANNER_WIDTH - 28,
             justify="left").pack(fill="x", pady=(2, 8))

    # Progress bar
    bar_bg = tk.Frame(content, bg=t["border"], height=3)
    bar_bg.pack(fill="x")
    bar_fg = tk.Frame(bar_bg, bg=t["bar"], height=3)
    bar_fg.place(x=0, y=0, relwidth=1.0, height=3)

    start_time = [0]

    def _update_bar() -> None:
        elapsed = win.tk.call("clock", "milliseconds") - start_time[0]
        fraction = max(0.0, 1.0 - elapsed / timeout_ms)
        bar_fg.place(x=0, y=0, relwidth=fraction, height=3)
        if fraction > 0:
            win.after(30, _update_bar)

    def _start() -> None:
        start_time[0] = win.tk.call("clock", "milliseconds")
        _update_bar()
        win.after(timeout_ms, win.destroy)

    win.after(10, _start)
    win.bind("<Button-1>", lambda e: win.destroy())

    _play_sound("auto")
    win.mainloop()


def show_confirm(title: str, message: str, item_id: int | None = None) -> None:
    t = _get_theme()
    win = _build_window(BANNER_WIDTH, BANNER_HEIGHT_CONFIRM, t)

    title_font  = tkfont.Font(family="Segoe UI Semibold", size=10, weight="bold")
    msg_font    = tkfont.Font(family="Segoe UI", size=9)
    btn_font    = tkfont.Font(family="Segoe UI", size=9)

    content = tk.Frame(win, bg=t["bg"])
    content.pack(fill="both", expand=True, padx=14, pady=8)

    tk.Label(content, text=title, font=title_font,
             bg=t["bg"], fg=t["text"],
             anchor="w").pack(fill="x")

    tk.Label(content, text=message, font=msg_font,
             bg=t["bg"], fg=t["subtext"],
             anchor="w", wraplength=BANNER_WIDTH - 28,
             justify="left").pack(fill="x", pady=(2, 10))

    btn_frame = tk.Frame(content, bg=t["bg"])
    btn_frame.pack(anchor="w")

    def _mark_done() -> None:
        if item_id is not None:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from src.db.database import update_item_status
            update_item_status(item_id, "done")
        win.destroy()

    if item_id is not None:
        tk.Button(
            btn_frame, text="Mark done", font=btn_font,
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            relief="flat", padx=12, pady=4,
            cursor="hand2", bd=0,
            activebackground=t["accent"],
            activeforeground=t["btn_primary_fg"],
            command=_mark_done,
        ).pack(side="left", padx=(0, 8))

    tk.Button(
        btn_frame, text="Dismiss", font=btn_font,
        bg=t["btn_secondary"], fg=t["btn_secondary_fg"],
        relief="flat", padx=12, pady=4,
        cursor="hand2", bd=0,
        activebackground=t["border"],
        activeforeground=t["btn_secondary_fg"],
        command=win.destroy,
    ).pack(side="left")

    _play_sound("confirm")
    win.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--title",   required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--mode",    choices=["auto", "confirm"], default="auto")
    parser.add_argument("--item-id", type=int, default=None)
    args = parser.parse_args()

    if args.mode == "auto":
        show_auto(args.title, args.message)
    else:
        show_confirm(args.title, args.message, item_id=args.item_id)