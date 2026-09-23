import subprocess

import comtypes
from pycaw.pycaw import AudioUtilities

# ---------------------------------------------------------------------------
# Output device switching (Phase 1b)
# ---------------------------------------------------------------------------

AUDIO_DEVICES = {
    "speakers": "{0.0.0.00000000}.{0a4a8d4a-9741-430f-8b96-69d14bb5e7e5}",
    "headphones": "{0.0.0.00000000}.{14253e55-7c6b-46ad-a362-c9222d7bd5c1}",
}


def switch_audio_device(device: str) -> str:
    """
    Switch the default Windows playback device.
    device: 'speakers' or 'headphones'.
    """
    if device not in AUDIO_DEVICES:
        raise ValueError(f"Unknown device: {device}. Available: {list(AUDIO_DEVICES.keys())}")

    device_id = AUDIO_DEVICES[device]

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f'Set-AudioDevice -ID "{device_id}"',
        ],
        capture_output=True,
        check=True,
    )

    return f"Output switched to {device}."


# ---------------------------------------------------------------------------
# Volume control (Phase 1a) — pycaw / Core Audio (WASAPI)
# ---------------------------------------------------------------------------

def _ensure_com() -> None:
    """
    Initialise COM on the current thread if it isn't already.

    pycaw talks to Core Audio over COM, and COM is initialised per thread. A
    tool may run on a thread without COM (tray, reminders, timer), which fails
    with 'CoInitialize has not been called'. Re-initialising is harmless
    (returns S_FALSE); it only raises on a different apartment model, which is
    safe to ignore for a short call.
    """
    try:
        comtypes.CoInitialize()
    except OSError:
        pass


def _endpoint():
    """
    Return the volume interface (IAudioEndpointVolume) of the default output.

    In pycaw 20251023 GetSpeakers() returns an AudioDevice wrapper whose
    .EndpointVolume is already a POINTER(IAudioEndpointVolume). The old manual
    .Activate()/cast() is gone — it failed with
    'AudioDevice object has no attribute Activate'.

    Fetched fresh on every call and never cached across threads: COM pointers
    are bound to their thread/apartment. Volume is not a hot path.
    """
    _ensure_com()
    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> int:
    """Return the current system volume as an integer 0-100."""
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(level: int) -> str:
    """
    Set the system volume to an exact (absolute) value.

    Use when the user names a number ("set volume to 40", «поставь громкость
    на 40», «гучність 50»). For "louder"/"quieter" without a number use
    volume_up / volume_down.

    level: target volume 0-100 (out-of-range values are clamped).
    """
    level = max(0, min(100, int(level)))
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return f"Volume set to {level}%."


def change_volume(delta: int) -> str:
    """
    Change the system volume by a relative amount.

    Use when the user names an amount ("turn it down by 20", «сделай тише на
    20», «додай 10»). If no number is given ("turn it up", «сделай громче»)
    use volume_up / volume_down.

    delta: points to change (positive = louder, negative = quieter), e.g. +10 or -20.
    """
    ep = _endpoint()  # one interface for read + write — no race
    current = ep.GetMasterVolumeLevelScalar()
    target = max(0.0, min(1.0, current + int(delta) / 100.0))
    ep.SetMasterVolumeLevelScalar(target, None)
    verb = "raised" if delta >= 0 else "lowered"
    return f"Volume {verb} to {round(target * 100)}%."


VOLUME_STEP = 5  # step for "louder/quieter" with no amount — easy to tune


def volume_up() -> str:
    """
    Raise the volume a little (by VOLUME_STEP points).
    Use for "turn it up", «сделай громче», «додай звук» when no amount is named.
    """
    return change_volume(VOLUME_STEP)


def volume_down() -> str:
    """
    Lower the volume a little (by VOLUME_STEP points).
    Use for "turn it down", «сделай тише», «прибери звук» when no amount is named.
    """
    return change_volume(-VOLUME_STEP)


def set_mute(muted: bool) -> str:
    """
    Mute or unmute the system output.

    muted: True to mute, False to unmute.
    """
    # Guard against the model passing the string "false" (non-empty str is truthy).
    if isinstance(muted, str):
        muted = muted.strip().lower() in ("true", "1", "yes", "on", "mute", "muted", "да", "так")
    _endpoint().SetMute(1 if muted else 0, None)
    return "Sound muted." if muted else "Sound unmuted."


def get_mute() -> bool:
    """Return True if the system output is currently muted."""
    return bool(_endpoint().GetMute())
