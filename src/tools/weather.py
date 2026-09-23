"""Weather tool backed by Open-Meteo (free API, no key).

Tool functions exposed to the model:
- get_weather          — forecast (today / tomorrow / week): temperature,
                         precipitation, wind, humidity, and a warning for severe
                         conditions (thunderstorm, storm, heavy snow);
- set_weather_location — save the default city in shared storage (SQLite).

Design (see Phase 5 ADR):
- City geocoding uses Open-Meteo's free keyless endpoint.
- One forecast request covers 7 days; the needed slice is picked locally.
- The default location lives in the settings table (key "weather_location")
  as JSON {name, lat, lon}. Coordinates are cached so the saved city isn't
  geocoded on every request. Initially Mississauga.
- Severe warnings are derived heuristically from the WMO code and wind gusts.
  They are NOT official weather-service warnings — free Open-Meteo has none.
- All expected failures (no network, city not found) return a friendly string
  instead of raising: the handle_turn choke point catches raises, but for
  EXPECTED errors we return clear text the model can voice.

Return strings are English; the model replies in the user's language (RU/UK/EN).
"""

from __future__ import annotations

import json

import requests

from src.db.database import get_setting, set_setting

# --- Constants --------------------------------------------------------------

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 10  # seconds per HTTP request

# settings-table key holding the default location JSON.
_LOCATION_KEY = "weather_location"

# Default location — Mississauga, Ontario (until the user sets their own).
_DEFAULT_LOCATION = {"name": "Mississauga", "lat": 43.5890, "lon": -79.6441}

# Wind gust threshold (km/h) that adds a storm warning.
_WIND_GUST_ALERT_KMH = 70.0

# WMO weather code -> (description, is_severe)
# https://open-meteo.com/en/docs  ("Weather variable documentation" section)
WMO_CODES: dict[int, tuple[str, bool]] = {
    0: ("clear sky", False),
    1: ("mainly clear", False),
    2: ("partly cloudy", False),
    3: ("overcast", False),
    45: ("fog", False),
    48: ("depositing rime fog", False),
    51: ("light drizzle", False),
    53: ("drizzle", False),
    55: ("dense drizzle", False),
    56: ("freezing drizzle", True),
    57: ("dense freezing drizzle", True),
    61: ("light rain", False),
    63: ("rain", False),
    65: ("heavy rain", True),
    66: ("freezing rain", True),
    67: ("heavy freezing rain", True),
    71: ("light snow", False),
    73: ("snow", False),
    75: ("heavy snowfall", True),
    77: ("snow grains", False),
    80: ("rain showers", False),
    81: ("heavy showers", False),
    82: ("violent rain showers", True),
    85: ("snow showers", False),
    86: ("heavy snow showers", True),
    95: ("thunderstorm", True),
    96: ("thunderstorm with hail", True),
    99: ("severe thunderstorm with hail", True),
}


def _describe_code(code: int | None) -> tuple[str, bool]:
    """Return (description, is_severe) for a WMO code; unknown code -> neutral."""
    if code is None:
        return ("no data", False)
    return WMO_CODES.get(int(code), (f"weather code {code}", False))


# --- Network calls ----------------------------------------------------------


def _geocode(city: str) -> dict | None:
    """Find a city's coordinates. None if the city isn't found."""
    params = {"name": city, "count": 1, "language": "en", "format": "json"}
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
    """Fetch a 7-day forecast + current conditions in one call."""
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


# --- Default location (shared storage) --------------------------------------


def _load_default_location() -> dict:
    """Read the saved location from settings; otherwise Mississauga."""
    raw = get_setting(_LOCATION_KEY)
    if raw:
        try:
            loc = json.loads(raw)
            if {"name", "lat", "lon"} <= loc.keys():
                return loc
        except (ValueError, AttributeError):
            pass  # corrupted value — silently fall back to the default
    return _DEFAULT_LOCATION


# --- Data processing --------------------------------------------------------


def _daily_humidity_means(data: dict) -> dict[str, float]:
    """Mean relative humidity per date, from hourly data.

    Open-Meteo's daily API has no humidity aggregate, so hourly
    relative_humidity_2m values are averaged per date.
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
    """Warning line if the condition is severe or gusts are strong."""
    reasons: list[str] = []
    desc, severe = _describe_code(code)
    if severe:
        reasons.append(desc)
    if gust_kmh is not None and gust_kmh >= _WIND_GUST_ALERT_KMH:
        reasons.append(f"wind gusts up to {round(gust_kmh)} km/h")
    if not reasons:
        return None
    return "WARNING: " + ", ".join(reasons)


def _format_one_day(data: dict, idx: int, hum_means: dict[str, float]) -> str:
    """One forecast line for the day at index idx (0 = today)."""
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
        f"high {_fmt_temp(tmax)}, low {_fmt_temp(tmin)}",
        f"precipitation {round(precip)}%" if precip is not None else "precipitation n/a",
        f"wind up to {round(wind)} km/h" if wind is not None else "wind n/a",
    ]
    if gust is not None:
        parts[-1] += f" (gusts {round(gust)} km/h)"
    if hum is not None:
        parts.append(f"humidity ~{round(hum)}%")

    line = f"{day_str}: " + ", ".join(parts)
    alert = _alert_for(code, gust)
    if alert:
        line += ". " + alert
    return line


# --- Public tool functions --------------------------------------------------


def get_weather(day: str = "today", location: str | None = None) -> str:
    """Get the weather forecast: temperature (°C), precipitation chance, wind,
    humidity, and a warning for severe conditions (thunderstorm, storm, heavy snow).

    Use for any weather question in any language: "what's the weather
    tomorrow", «какая погода сегодня», «яка погода завтра», «погода в Киеве»,
    «прогноз на неделю».

    day: "today" (default), "tomorrow", or "week" (7-day summary).
    location: city name, e.g. "Kyiv", "London" — for a one-off forecast in
        another city. OMIT it to use the saved default location
        (initially Mississauga).
    """
    day_norm = (day or "today").strip().lower()

    try:
        if location and location.strip():
            loc = _geocode(location.strip())
            if loc is None:
                return f"Could not find location '{location}'."
        else:
            loc = _load_default_location()
        data = _fetch_forecast(loc["lat"], loc["lon"])
    except requests.exceptions.RequestException:
        return "Can't get weather data right now — the service is unavailable."
    except (KeyError, ValueError, TypeError):
        return "The weather service returned an unexpected response, try again later."

    hum_means = _daily_humidity_means(data)
    name = loc["name"]
    n_days = len(data["daily"]["time"])

    if day_norm in ("week", "7day", "7-day", "7 day", "неделя"):
        lines = [_format_one_day(data, i, hum_means) for i in range(n_days)]
        return f"7-day weather for {name}:\n" + "\n".join(lines)

    if day_norm in ("tomorrow", "завтра"):
        idx, label = 1, "tomorrow"
    else:  # today / сегодня / anything else
        idx, label = 0, "today"

    if idx >= n_days:  # guard: API returned fewer days than expected
        return "The weather service returned incomplete data, try again later."

    body = _format_one_day(data, idx, hum_means)
    _, _, rest = body.partition(": ")  # drop the leading date for a natural phrase
    return f"Weather in {name} {label}: {rest}"


def set_weather_location(city: str) -> str:
    """Save the default city for weather forecasts in shared storage.

    Use when the user asks to remember or change their weather city:
    "set my default weather city to London", «запомни мой город — Торонто»,
    «зроби погоду за замовчуванням для Києва». Do NOT call this for a one-off
    forecast in another city — just pass location to get_weather.

    city: city name, e.g. "Toronto", "Киев", "Львів".
    """
    if not city or not city.strip():
        return "No city specified."
    try:
        found = _geocode(city.strip())
    except requests.exceptions.RequestException:
        return "Can't verify the city right now — the service is unavailable."
    if found is None:
        return f"Could not find location '{city}'."
    set_setting(_LOCATION_KEY, json.dumps(found, ensure_ascii=False))
    return f"Default location saved: {found['name']}."


# --- Manual test (offline logic is mocked in tests) -------------------------

if __name__ == "__main__":
    print(get_weather("today"))
    print(get_weather("tomorrow"))
    print(get_weather("week"))
    print(get_weather("tomorrow", location="Kyiv"))
    print(set_weather_location("Toronto"))
