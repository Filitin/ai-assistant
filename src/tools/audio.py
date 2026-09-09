import subprocess

AUDIO_DEVICES = {
    "speakers": "{0.0.0.00000000}.{0a4a8d4a-9741-430f-8b96-69d14bb5e7e5}",
    "headphones": "{0.0.0.00000000}.{14253e55-7c6b-46ad-a362-c9222d7bd5c1}",
}


def switch_audio_device(device: str) -> str:
    """
    Переключает устройство воспроизведения звука по умолчанию в Windows.
    device: 'speakers' для колонок, 'headphones' для наушников.
    """
    if device not in AUDIO_DEVICES:
        raise ValueError(f"Неизвестное устройство: {device}. Доступны: {list(AUDIO_DEVICES.keys())}")

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

    return f"Устройство переключено на {device}"
