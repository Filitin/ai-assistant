# src/voice/recorder.py
"""
Microphone capture for the voice layer — hold-to-talk (V1).

Hold F9 to record, release to stop. Records mono 16 kHz float32 audio (the
format faster-whisper expects) from the default input device. V2 will replace
the F9 trigger with a voice-activity-detection loop while reusing the capture
core (record_stream / _Recorder) unchanged.

Global hotkey via the `keyboard` library requires running as administrator on
Windows. Run directly to hold-to-talk one clip and print its transcription:
    python -m src.voice.recorder
"""

from __future__ import annotations

import numpy as np
import sounddevice as sd
import keyboard

SAMPLE_RATE = 16000   # Whisper expects 16 kHz
CHANNELS = 1
PTT_KEY = "f9"


class _Recorder:
    """Collects mic frames while active. The capture core reused by V1 and V2."""

    def __init__(self) -> None:
        self._frames: list[np.ndarray] = []

    def _callback(self, indata, _frames, _time, status) -> None:
        if status:
            print(f"[recorder] stream status: {status}")
        self._frames.append(indata.copy())   # copy: PortAudio reuses the buffer

    def record_while(self, is_active) -> np.ndarray:
        """
        Record for as long as is_active() returns True; return a 1-D float32 array.

        is_active is a callable polled continuously — here it's "F9 is held down".
        """
        self._frames.clear()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
        ):
            while is_active():
                sd.sleep(30)   # ~33 Hz poll; low CPU, no perceptible lag

        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._frames, axis=0).flatten()


def record_hold_to_talk() -> np.ndarray:
    """
    Wait for F9 to be pressed, record while it's held, stop on release.

    Returns the captured audio as a 1-D float32 array (empty if nothing recorded).
    """
    print(f"Hold {PTT_KEY.upper()} to talk...")
    keyboard.wait(PTT_KEY)                       # block until F9 goes down
    rec = _Recorder()
    return rec.record_while(lambda: keyboard.is_pressed(PTT_KEY))


if __name__ == "__main__":
    from src.voice.stt import transcribe, warm_up

    warm_up()                                    # load large-v3 before recording
    audio = record_hold_to_talk()
    print(f"[recorder] Captured {len(audio) / SAMPLE_RATE:.1f}s of audio.")

    text, lang = transcribe(audio)
    print(f"[recorder] Detected language: {lang}")
    print(f"[recorder] Transcript: {text!r}")