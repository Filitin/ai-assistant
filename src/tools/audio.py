import subprocess

import comtypes
from pycaw.pycaw import AudioUtilities

# ---------------------------------------------------------------------------
# Переключение устройства вывода (Phase 1b) — существующий инструмент
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Управление громкостью (Phase 1a) — pycaw / Core Audio (WASAPI)
# ---------------------------------------------------------------------------

def _ensure_com() -> None:
    """
    Инициализирует COM на текущем потоке, если это ещё не сделано.

    pycaw обращается к Core Audio через COM, а COM инициализируется отдельно
    для каждого потока. Инструмент может быть вызван из потока, где COM не
    поднят (трей, напоминания, таймер) — иначе ошибка 'CoInitialize has not
    been called'. Повторная инициализация безвредна (возвращает S_FALSE);
    исключение возникает лишь при другой модели апартамента, что для короткого
    вызова можно игнорировать.
    """
    try:
        comtypes.CoInitialize()
    except OSError:
        pass


def _endpoint():
    """
    Возвращает интерфейс громкости (IAudioEndpointVolume) устройства вывода
    по умолчанию.

    В pycaw 20251023 GetSpeakers() возвращает обёртку AudioDevice, у которой
    свойство .EndpointVolume уже отдаёт готовый POINTER(IAudioEndpointVolume).
    Ручной вызов .Activate()/cast() больше не нужен — он и падал с ошибкой
    'AudioDevice object has no attribute Activate'.

    Интерфейс берётся заново на каждый вызов и не кэшируется между потоками:
    COM-указатели привязаны к потоку/апартаменту. Управление громкостью не
    горячий путь, так что лишний вызов несущественен.
    """
    _ensure_com()
    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> int:
    """Возвращает текущую громкость системного звука как целое число 0–100."""
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(level: int) -> str:
    """
    Устанавливает громкость системного звука на точное (абсолютное) значение.

    Используй, когда пользователь называет конкретное число («поставь громкость
    на 40», «громкость 50»). Для «громче»/«тише» без числа используй change_volume.

    level: целевая громкость 0–100 (значения вне диапазона обрезаются).
    """
    level = max(0, min(100, int(level)))
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return f"Громкость установлена на {level}%."


def change_volume(delta: int) -> str:
    """
    Изменяет громкость системного звука на относительную величину.

    Используй, когда пользователь называет величину («сделай тише на 20»). Если
    число НЕ указано («сделай громче», «turn it up») — используй volume_up /
    volume_down.

    delta: на сколько пунктов изменить (положительное — громче, отрицательное —
    тише), например +10 или -20.
    """
    ep = _endpoint()  # одно получение интерфейса для чтения и записи — без гонки
    current = ep.GetMasterVolumeLevelScalar()
    target = max(0.0, min(1.0, current + int(delta) / 100.0))
    ep.SetMasterVolumeLevelScalar(target, None)
    verb = "повышена" if delta >= 0 else "понижена"
    return f"Громкость {verb} до {round(target * 100)}%."


VOLUME_STEP = 5  # шаг для «громче/тише» без указания величины — легко поменять


def volume_up() -> str:
    """
    Немного увеличивает громкость — на VOLUME_STEP пунктов.
    Используй для «сделай громче»/«turn it up»/«додай звук», когда величина не названа.
    """
    return change_volume(VOLUME_STEP)


def volume_down() -> str:
    """
    Немного уменьшает громкость — на VOLUME_STEP пунктов.
    Используй для «сделай тише»/«turn it down»/«прибери звук», когда величина не названа.
    """
    return change_volume(-VOLUME_STEP)


def set_mute(muted: bool) -> str:
    """
    Отключает (mute) или включает звук системного вывода.

    muted: True — заглушить, False — включить звук.
    """
    # Защита от модели, вернувшей строку "false" (непустая строка всегда истинна).
    if isinstance(muted, str):
        muted = muted.strip().lower() in ("true", "1", "yes", "on", "mute", "muted", "да")
    _endpoint().SetMute(1 if muted else 0, None)
    return "Звук заглушён." if muted else "Звук включён."


def get_mute() -> bool:
    """Возвращает True, если звук системного вывода сейчас заглушён."""
    return bool(_endpoint().GetMute())

