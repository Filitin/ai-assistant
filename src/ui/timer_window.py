# src/ui/timer_window.py
"""
Timer window in Windows 11 Clock style.
Called via subprocess from src/tools/timer.py:
    python -m src.ui.timer_window --seconds 1500 --label "Focus"
"""

import argparse
import math
import subprocess
import sys
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
import winreg

PROJECT_ROOT = Path(__file__).parent.parent.parent

# ── Theme ────────────────────────────────────────────────────────────────────

LIGHT = {
    "bg":           "#f3f3f3",
    "bg_card":      "#e8e8e8",
    "text":         "#1a1a1a",
    "subtext":      "#6a6a6a",
    "accent":       "#8860d0",   # purple like Clock app
    "accent_dim":   "#d0c0ef",
    "track":        "#d0d0d0",
    "btn_bg":       "#e0e0e0",
    "btn_fg":       "#1a1a1a",
    "btn_hover":    "#cccccc",
}

DARK = {
    "bg":           "#1c1c1c",
    "bg_card":      "#2a2a2a",
    "text":         "#ffffff",
    "subtext":      "#999999",
    "accent":       "#c084fc",   # purple
    "accent_dim":   "#4a3060",
    "track":        "#3a3a3a",
    "btn_bg":       "#333333",
    "btn_fg":       "#ffffff",
    "btn_hover":    "#444444",
}


def _get_theme() -> dict:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return LIGHT if value == 1 else DARK
    except OSError:
        return DARK


# ── Geometry helpers ─────────────────────────────────────────────────────────

WIN_W = 300
WIN_H = 380
CANVAS_SIZE = 220
RING_OUTER = 100   # radius outer edge of ring
RING_INNER = 78    # radius inner edge (ring thickness = 22px)
CENTER = CANVAS_SIZE // 2


def _center_window(win: tk.Tk) -> None:
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = (sw - WIN_W) // 2
    y = (sh - WIN_H) // 2
    win.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")


# ── Arc drawing ───────────────────────────────────────────────────────────────

def _draw_arc(canvas: tk.Canvas, fraction: float, color: str, track_color: str) -> None:
    """
    Draw a circular progress ring.
    fraction: 1.0 = full, 0.0 = empty. Starts at top, goes clockwise.
    """
    canvas.delete("arc")
    pad = CENTER - RING_OUTER

    # Background track (full circle)
    canvas.create_arc(
        pad, pad, CANVAS_SIZE - pad, CANVAS_SIZE - pad,
        start=90, extent=359.99,
        style="arc",
        outline=track_color,
        width=RING_OUTER - RING_INNER,
        tags="arc",
    )

    # Foreground progress
    if fraction > 0.001:
        extent = fraction * 359.99
        canvas.create_arc(
            pad, pad, CANVAS_SIZE - pad, CANVAS_SIZE - pad,
            start=90, extent=-extent,   # negative = clockwise
            style="arc",
            outline=color,
            width=RING_OUTER - RING_INNER,
            tags="arc",
        )

    # End cap dot
    if fraction > 0.001:
        angle_rad = math.radians(90 - extent)
        r_mid = (RING_OUTER + RING_INNER) / 2
        dot_x = CENTER + r_mid * math.cos(angle_rad)
        dot_y = CENTER - r_mid * math.sin(angle_rad)
        dot_r = (RING_OUTER - RING_INNER) / 2
        canvas.create_oval(
            dot_x - dot_r, dot_y - dot_r,
            dot_x + dot_r, dot_y + dot_r,
            fill=color, outline="", tags="arc",
        )


# ── Button helper ─────────────────────────────────────────────────────────────

def _round_btn(parent: tk.Widget, text: str, t: dict,
               size: int, command, is_accent: bool = False) -> tk.Button:
    bg = t["accent"] if is_accent else t["btn_bg"]
    fg = "#000000" if is_accent else t["btn_fg"]
    btn = tk.Button(
        parent, text=text, font=tkfont.Font(family="Segoe UI", size=size),
        bg=bg, fg=fg, activebackground=t["btn_hover"],
        activeforeground=fg, relief="flat", bd=0,
        cursor="hand2", width=3, height=1,
        command=command,
    )
    return btn


# ── Main window ───────────────────────────────────────────────────────────────

def run_timer(total_seconds: int, label: str) -> None:
    t = _get_theme()

    win = tk.Tk()
    win.title("Timer")
    win.geometry(f"{WIN_W}x{WIN_H}")
    win.configure(bg=t["bg"])
    win.resizable(False, False)
    _center_window(win)

    # Try to set window icon programmatically (suppress error if no icon)
    try:
        win.iconbitmap(default="")
    except Exception:
        pass

    # ── State ──────────────────────────────────────────────────────────────
    remaining   = [total_seconds]
    paused      = [False]
    finished    = [False]
    after_id    = [None]

    # ── Label at top ───────────────────────────────────────────────────────
    lbl_font  = tkfont.Font(family="Segoe UI", size=11)
    time_font = tkfont.Font(family="Segoe UI Light", size=26, weight="bold")
    sub_font  = tkfont.Font(family="Segoe UI", size=9)

    tk.Label(win, text=label, font=lbl_font,
             bg=t["bg"], fg=t["subtext"]).pack(pady=(20, 0))

    # ── Canvas ring ────────────────────────────────────────────────────────
    canvas = tk.Canvas(win, width=CANVAS_SIZE, height=CANVAS_SIZE,
                       bg=t["bg"], highlightthickness=0)
    canvas.pack(pady=(6, 0))

    # Time text inside ring
    canvas.create_text(
        CENTER, CENTER,
        text="",
        font=time_font,
        fill=t["text"],
        tags="time_text",
    )   

    # ── Buttons ────────────────────────────────────────────────────────────
    btn_frame = tk.Frame(win, bg=t["bg"])
    btn_frame.pack(pady=16)

    def _toggle_pause() -> None:
        if finished[0]:
            return
        paused[0] = not paused[0]
        pause_btn.config(text="▶" if paused[0] else "⏸")

    def _cancel() -> None:
        if after_id[0]:
            win.after_cancel(after_id[0])
        win.destroy()

    pause_btn = _round_btn(btn_frame, "⏸", t, size=14,
                           command=_toggle_pause, is_accent=True)
    pause_btn.pack(side="left", padx=10, ipadx=8, ipady=6)

    cancel_btn = _round_btn(btn_frame, "↺", t, size=14,
                            command=_cancel, is_accent=False)
    cancel_btn.pack(side="left", padx=10, ipadx=8, ipady=6)

    # ── Tick function ───────────────────────────────────────────────────────
    def _fmt(secs: int) -> str:
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _tick() -> None:
        if finished[0]:
            return
        if not paused[0]:
            remaining[0] -= 1

        fraction = remaining[0] / total_seconds
        _draw_arc(canvas, fraction, t["accent"], t["track"])
        canvas.itemconfig("time_text", text=_fmt(remaining[0]))

        if remaining[0] <= 0:
            finished[0] = True
            _on_finish()
            return

        after_id[0] = win.after(1000, _tick)

    def _on_finish() -> None:
        pause_btn.config(state="disabled")
        _draw_arc(canvas, 0.0, t["accent"], t["track"])
        canvas.itemconfig("time_text", text="Done!")

        # Fire banner notification
        subprocess.Popen(
            [
                sys.executable, "-m", "src.notify",
                "--title", "Timer complete",
                "--message", label,
                "--mode", "auto",
            ],
            cwd=PROJECT_ROOT,
        )
        # Close timer window after 3 seconds
        win.after(3000, win.destroy)

    # ── Init ───────────────────────────────────────────────────────────────
    canvas.itemconfig("time_text", text=_fmt(total_seconds))
    _draw_arc(canvas, 1.0, t["accent"], t["track"])
    after_id[0] = win.after(1000, _tick)

    win.protocol("WM_DELETE_WINDOW", _cancel)
    win.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--label",   type=str, default="Timer")
    args = parser.parse_args()
    run_timer(args.seconds, args.label)