# src/notify.py
"""
Standalone banner notification window.
Can be imported and called directly, or run as a script:
    python -m src.notify --title "Timer" --message "Done" --mode auto
    python -m src.notify --title "Reminder" --message "Task due" --mode confirm --item-id 3

Modes:
    auto    — appears for `timeout` seconds then closes itself (for timers)
    confirm — stays until user clicks a button (for due_date reminders)
"""

import argparse
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont


BANNER_WIDTH = 360
BANNER_HEIGHT_AUTO = 90
BANNER_HEIGHT_CONFIRM = 130
CORNER_RADIUS = 12
BG_COLOR = "#1e1e2e"
TEXT_COLOR = "#cdd6f4"
TITLE_COLOR = "#cba6f7"
BTN_DONE_COLOR = "#a6e3a1"
BTN_DISMISS_COLOR = "#6c7086"
BTN_TEXT_COLOR = "#1e1e2e"
AUTO_TIMEOUT_MS = 6000  # 6 seconds for auto-close banners


def _place_bottom_right(win: tk.Tk, width: int, height: int) -> None:
    """Position window in the bottom-right corner with a small margin."""
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    margin = 16
    x = screen_w - width - margin
    y = screen_h - height - margin - 48  # 48px above taskbar
    win.geometry(f"{width}x{height}+{x}+{y}")


def show_auto(title: str, message: str, timeout_ms: int = AUTO_TIMEOUT_MS) -> None:
    """Banner that closes itself after timeout_ms milliseconds."""
    win = tk.Tk()
    win.overrideredirect(True)       # no title bar
    win.attributes("-topmost", True) # always on top
    win.attributes("-alpha", 0.95)
    win.configure(bg=BG_COLOR)

    _place_bottom_right(win, BANNER_WIDTH, BANNER_HEIGHT_AUTO)

    title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
    msg_font = tkfont.Font(family="Segoe UI", size=9)

    tk.Label(win, text=title, font=title_font,
             bg=BG_COLOR, fg=TITLE_COLOR, anchor="w",
             padx=14, pady=(10, 2)).pack(fill="x")

    tk.Label(win, text=message, font=msg_font,
             bg=BG_COLOR, fg=TEXT_COLOR, anchor="w",
             padx=14, pady=(0, 10), wraplength=BANNER_WIDTH - 28,
             justify="left").pack(fill="x")

    # Progress bar that shrinks over timeout_ms
    bar_frame = tk.Frame(win, bg=BG_COLOR)
    bar_frame.pack(fill="x", padx=14, pady=(0, 8))
    bar = tk.Frame(bar_frame, bg=TITLE_COLOR, height=3)
    bar.pack(fill="x")

    start_time = [0]

    def _update_bar() -> None:
        elapsed = win.tk.call("clock", "milliseconds") - start_time[0]
        fraction = max(0.0, 1.0 - elapsed / timeout_ms)
        bar.configure(width=int((BANNER_WIDTH - 28) * fraction))
        if fraction > 0:
            win.after(30, _update_bar)

    def _start() -> None:
        start_time[0] = win.tk.call("clock", "milliseconds")
        _update_bar()
        win.after(timeout_ms, win.destroy)

    win.after(10, _start)

    # Click anywhere to dismiss early
    win.bind("<Button-1>", lambda e: win.destroy())
    win.mainloop()


def show_confirm(title: str, message: str, item_id: int | None = None) -> None:
    """
    Banner that waits for user action.
    If item_id is provided, 'Mark done' button updates the DB directly.
    """
    win = tk.Tk()
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.attributes("-alpha", 0.95)
    win.configure(bg=BG_COLOR)

    _place_bottom_right(win, BANNER_WIDTH, BANNER_HEIGHT_CONFIRM)

    title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
    msg_font = tkfont.Font(family="Segoe UI", size=9)
    btn_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")

    tk.Label(win, text=title, font=title_font,
             bg=BG_COLOR, fg=TITLE_COLOR, anchor="w",
             padx=14, pady=(10, 2)).pack(fill="x")

    tk.Label(win, text=message, font=msg_font,
             bg=BG_COLOR, fg=TEXT_COLOR, anchor="w",
             padx=14, pady=(0, 8), wraplength=BANNER_WIDTH - 28,
             justify="left").pack(fill="x")

    btn_frame = tk.Frame(win, bg=BG_COLOR)
    btn_frame.pack(fill="x", padx=14, pady=(0, 12))

    def _mark_done() -> None:
        if item_id is not None:
            # Import here to avoid circular issues when run as __main__
            sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
            from src.db.database import update_item_status
            update_item_status(item_id, "done")
        win.destroy()

    def _dismiss() -> None:
        win.destroy()

    if item_id is not None:
        tk.Button(
            btn_frame, text="Mark done", font=btn_font,
            bg=BTN_DONE_COLOR, fg=BTN_TEXT_COLOR,
            relief="flat", padx=10, pady=3,
            cursor="hand2", command=_mark_done,
        ).pack(side="left", padx=(0, 8))

    tk.Button(
        btn_frame, text="Dismiss", font=btn_font,
        bg=BTN_DISMISS_COLOR, fg=TEXT_COLOR,
        relief="flat", padx=10, pady=3,
        cursor="hand2", command=_dismiss,
    ).pack(side="left")

    win.mainloop()


# ---------------------------------------------------------------------------
# Entry point — called via subprocess from timer.py and reminders.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--mode", choices=["auto", "confirm"], default="auto")
    parser.add_argument("--item-id", type=int, default=None)
    args = parser.parse_args()

    if args.mode == "auto":
        show_auto(args.title, args.message)
    else:
        show_confirm(args.title, args.message, item_id=args.item_id)