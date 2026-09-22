"""Погодный инструмент на базе Open-Meteo (бесплатный API, без ключа).

Экспонирует две функции-инструмента для модели:
- get_weather        — прогноз (сегодня / завтра / неделя) с температурой,
                       осадками, ветром, влажностью и предупреждением о
                       серьёзных явлениях (гроза, шторм, сильный снег);
- set_weather_location — сохранить город по умолчанию в общем хранилище (SQLite).

Дизайн (см. ADR фазы 5):
- Геокодинг города — бесплатный keyless-эндпоинт Open-Meteo.
- Один запрос прогноза сразу на 7 дней; нужный срез выбирается локально.
- Локация по умолчанию хранится в таблице settings (ключ "weather_location")
  как JSON {name, lat, lon}. Координаты кэшируются, чтобы не геокодировать
  сохранённый город при каждом запросе. Изначально — Миссиссога.
- Серьёзные предупреждения выводятся эвристически из WMO-кода и порывов ветра.
  Это НЕ официальные штормовые предупреждения гидрометслужбы — у бесплатного
  Open-Meteo их нет.
- Все ожидаемые сбои (нет сети, город не найден) возвращаются дружелюбной
  строкой, а не исключением: choke point в handle_turn ловит raise, но для
  ОЖИДАЕМЫХ ошибок мы отдаём понятный текст, который модель озвучит.

Возвращаемые строки — на русском; модель сама переформулирует / переведёт
ответ на язык пользователя (RU/UK/EN).
"""

from __future__ import annotations

import json

import requests

from src.db.database import get_setting, set_setting

# --- Константы --------------------------------------------------------------

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 10  # секунд на HTTP-запрос

# Ключ в таблице settings, под которым лежит JSON локации по умолчанию.
_LOCATION_KEY = "weather_location"

# Локация по умолчанию — Миссиссога, Онтарио (пока пользователь не задал свою).
_DEFAULT_LOCATION = {"name": "Mississauga", "lat": 43.5890, "lon": -79.6441}

# Порог порывов ветра (км/ч), при котором добавляем предупреждение о шторме.
_WIND_GUST_ALERT_KMH = 70.0

# WMO weather code -> (описание, серьёзное_явление)
# https://open-meteo.com/en/docs  (раздел "Weather variable documentation")
WMO_CODES: dict[int, tuple[str, bool]] = {
    0: ("ясно", False),
    1: ("преимущественно ясно", False),
    2: ("переменная облачность", False),
    3: ("пасмурно", False),
    45: ("туман", False),
    48: ("изморозь", False),
    51: ("слабая морось", False),
    53: ("морось", False),
    55: ("сильная морось", False),
    56: ("ледяная морось", True),
    57: ("сильная ледяная морось", True),
    61: ("небольшой дождь", False),
    63: ("дождь", False),
    65: ("сильный дождь", True),
    66: ("ледяной дождь", True),
    67: ("сильный ледяной дождь", True),
    71: ("небольшой снег", False),
    73: ("снег", False),
    75: ("сильный снегопад", True),
    77: ("снежная крупа", False),
    80: ("кратковременный дождь", False),
    81: ("ливень", False),
    82: ("сильный ливень", True),
    85: ("снежные заряды", False),
    86: ("сильные снежные заряды", True),
    95: ("гроза", True),
    96: ("гроза с градом", True),
    99: ("сильная гроза с градом", True),
}


def _describe_code(code: int | None) -> tuple[str, bool]:
    """Вернуть (описание, серьёзное) по WMO-коду; неизвестный код — нейтрально."""
    if code is None:
        return ("нет данных", False)
    return WMO_CODES.get(int(code), (f"код погоды {code}", False))


# --- Сетевые вызовы ---------------------------------------------------------


def _geocode(city: str) -> dict | None:
    """Найти координаты города. None — если город не найден."""
    params = {"name": city, "count": 1, "language": "ru", "format": "json"}
    resp = requests.get(_GEOCODE_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        return None
    top = results[0]
    label = top["name"]
    if top.get("admin1"):
        label += f", {top['admin1']}"
    if top.get("country"):
        label += f", {top['country']}"
    return {"name": label, "lat": top["latitude"], "lon": top["longitude"]}


def _fetch_forecast(lat: float, lon: float) -> dict:
    """Запросить прогноз на 7 дней + текущие условия одним вызовом."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
            ]
        ),
        "hourly": "relative_humidity_2m",
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "wind_speed_10m",
                "weather_code",
            ]
        ),
        "wind_speed_unit": "kmh",
        "temperature_unit": "celsius",
        "timezone": "auto",
        "forecast_days": 7,
    }
    resp = requests.get(_FORECAST_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# --- Локация по умолчанию (через общее хранилище) ---------------------------


def _load_default_location() -> dict:
    """Прочитать сохранённую локацию из settings; иначе — Миссиссога."""
    raw = get_setting(_LOCATION_KEY)
    if raw:
        try:
            loc = json.loads(raw)
            if {"name", "lat", "lon"} <= loc.keys():
                return loc
        except (ValueError, AttributeError):
            pass  # повреждённое значение — тихо откатываемся к дефолту
    return _DEFAULT_LOCATION


# --- Обработка данных -------------------------------------------------------


def _daily_humidity_means(data: dict) -> dict[str, float]:
    """Средняя относительная влажность по датам из почасовых данных.

    В суточном API Open-Meteo нет агрегата влажности, поэтому усредняем
    почасовые значения relative_humidity_2m по каждой дате.
    """
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    hums = hourly.get("relative_humidity_2m", [])
    buckets: dict[str, list[float]] = {}
    for ts, h in zip(times, hums):
        if h is None:
            continue
        day_key = ts[:10]  # 'YYYY-MM-DD'
        buckets.setdefault(day_key, []).append(h)
    return {d: sum(vs) / len(vs) for d, vs in buckets.items() if vs}


def _fmt_temp(value: float | None) -> str:
    """+18°C / -4°C / 0°C."""
    if value is None:
        return "?"
    rounded = round(value)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{rounded}°C"


def _alert_for(code: int | None, gust_kmh: float | None) -> str | None:
    """Строка предупреждения, если явление серьёзное или сильные порывы."""
    reasons: list[str] = []
    desc, severe = _describe_code(code)
    if severe:
        reasons.append(desc)
    if gust_kmh is not None and gust_kmh >= _WIND_GUST_ALERT_KMH:
        reasons.append(f"порывы ветра до {round(gust_kmh)} км/ч")
    if not reasons:
        return None
    return "⚠️ Внимание: " + ", ".join(reasons)


def _format_one_day(data: dict, idx: int, hum_means: dict[str, float]) -> str:
    """Одна строка прогноза для дня с индексом idx (0=сегодня)."""
    daily = data["daily"]
    day_str = daily["time"][idx]
    code = daily["weather_code"][idx]
    desc, _ = _describe_code(code)
    tmax = daily["temperature_2m_max"][idx]
    tmin = daily["temperature_2m_min"][idx]
    precip = daily["precipitation_probability_max"][idx]
    wind = daily["wind_speed_10m_max"][idx]
    gust = daily["wind_gusts_10m_max"][idx]
    hum = hum_means.get(day_str)

    parts = [
        desc,
        f"днём {_fmt_temp(tmax)}, ночью {_fmt_temp(tmin)}",
        f"осадки {round(precip)}%" if precip is not None else "осадки н/д",
        f"ветер до {round(wind)} км/ч" if wind is not None else "ветер н/д",
    ]
    if gust is not None:
        parts[-1] += f" (порывы {round(gust)} км/ч)"
    if hum is not None:
        parts.append(f"влажность ~{round(hum)}%")

    line = f"{day_str}: " + ", ".join(parts)
    alert = _alert_for(code, gust)
    if alert:
        line += ". " + alert
    return line


# --- Публичные функции-инструменты ------------------------------------------


def get_weather(day: str = "today", location: str | None = None) -> str:
    """Узнать прогноз погоды: температура (°C), вероятность осадков, ветер,
    влажность и предупреждение о серьёзных явлениях (гроза, шторм, сильный снег).

    Используй для любых вопросов о погоде на любом языке: «какая погода
    сегодня», «яка погода завтра», "what's the weather tomorrow", «погода в
    Киеве», «прогноз на неделю».

    day: "today" (сегодня, по умолчанию), "tomorrow" (завтра) или "week"
        (сводка на 7 дней).
    location: название города, например "Kyiv", "London" — для разового
        прогноза в другом городе. НЕ указывай, чтобы использовать сохранённую
        локацию по умолчанию (изначально Миссиссога).
    """
    day_norm = (day or "today").strip().lower()

    try:
        if location and location.strip():
            loc = _geocode(location.strip())
            if loc is None:
                return f"Не удалось найти локацию «{location}»."
        else:
            loc = _load_default_location()
        data = _fetch_forecast(loc["lat"], loc["lon"])
    except requests.exceptions.RequestException:
        return "Сейчас не могу получить данные о погоде — сервис недоступен."
    except (KeyError, ValueError, TypeError):
        return "Сервис погоды вернул неожиданный ответ, попробуйте позже."

    hum_means = _daily_humidity_means(data)
    name = loc["name"]
    n_days = len(data["daily"]["time"])

    if day_norm in ("week", "7day", "7-day", "7 day", "неделя"):
        lines = [_format_one_day(data, i, hum_means) for i in range(n_days)]
        return f"Погода в {name} на 7 дней:\n" + "\n".join(lines)

    if day_norm in ("tomorrow", "завтра"):
        idx, label = 1, "завтра"
    else:  # today / сегодня / всё прочее
        idx, label = 0, "сегодня"

    if idx >= n_days:  # защита, если API вернул меньше дней, чем ожидалось
        return "Сервис погоды вернул неполные данные, попробуйте позже."

    body = _format_one_day(data, idx, hum_means)
    _, _, rest = body.partition(": ")  # убираем ведущую дату для естественной фразы
    return f"Погода в {name} на {label}: {rest}"


def set_weather_location(city: str) -> str:
    """Сохранить город по умолчанию для прогноза погоды в общем хранилище.

    Используй, когда пользователь просит запомнить или сменить свой город
    погоды: «запомни мой город — Торонто», «сделай погоду по умолчанию для
    Киева», "set my default weather city to London". Для разового прогноза в
    другом городе это НЕ вызывай — просто передай location в get_weather.

    city: название города, например "Toronto", "Киев", "Львів".
    """
    if not city or not city.strip():
        return "Не указан город."
    try:
        found = _geocode(city.strip())
    except requests.exceptions.RequestException:
        return "Сейчас не могу проверить город — сервис недоступен."
    if found is None:
        return f"Не удалось найти локацию «{city}»."
    set_setting(_LOCATION_KEY, json.dumps(found, ensure_ascii=False))
    return f"Локация по умолчанию сохранена: {found['name']}."


# --- Ручной тест (офлайн-логика подменяется в тестах) -----------------------

if __name__ == "__main__":
    print(get_weather("today"))
    print(get_weather("tomorrow"))
    print(get_weather("week"))
    print(get_weather("tomorrow", location="Kyiv"))
    print(set_weather_location("Toronto"))
