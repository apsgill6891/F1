"""
Weather Module
Fetches race weekend forecast from Open-Meteo (free, no API key needed).
Returns hourly temperature, precipitation, wind, and cloud cover.
"""

import requests
import requests_cache
from datetime import datetime, timedelta, timezone
from retry_requests import retry

# Cache requests for 30 minutes to avoid hammering the API
requests_cache.install_cache("data/weather_cache", expire_after=1800)
session = retry(requests_cache.CachedSession("data/weather_cache"), retries=3, backoff_factor=0.5)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Suzuka circuit coordinates
CIRCUIT_LOCATIONS = {
    "Suzuka": {"lat": 34.8431, "lon": 136.5407, "tz": "Asia/Tokyo"},
    "Monza": {"lat": 45.6156, "lon": 9.2811, "tz": "Europe/Rome"},
    "Monaco": {"lat": 43.7347, "lon": 7.4205, "tz": "Europe/Monaco"},
    "Silverstone": {"lat": 52.0786, "lon": -1.0169, "tz": "Europe/London"},
    "COTA": {"lat": 30.1328, "lon": -97.6411, "tz": "America/Chicago"},
}


def fetch_forecast(circuit: str = "Suzuka", race_date: str = None) -> dict:
    """
    Fetch 7-day hourly forecast for the circuit location.
    race_date: ISO format YYYY-MM-DD, defaults to next Sunday if not given.
    Returns structured dict with race-day and weekend summary.
    """
    loc = CIRCUIT_LOCATIONS.get(circuit, CIRCUIT_LOCATIONS["Suzuka"])

    if race_date is None:
        # Default: next Sunday
        today = datetime.now()
        days_ahead = (6 - today.weekday()) % 7
        race_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "precipitation",
            "windspeed_10m",
            "cloudcover",
            "relativehumidity_2m",
        ],
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
        ],
        "timezone": loc["tz"],
        "forecast_days": 7,
    }

    try:
        resp = session.get(OPEN_METEO_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [weather] API error: {e} — using fallback defaults")
        return _fallback_weather(circuit, race_date)

    hourly = data.get("hourly", {})
    daily = data.get("daily", {})

    # Extract race day hours (typical race window: 13:00-16:00 local)
    race_day_idx = []
    for i, t in enumerate(hourly.get("time", [])):
        if t.startswith(race_date) and "13" <= t[11:13] <= "16":
            race_day_idx.append(i)

    def avg_at_race(key):
        vals = [hourly[key][i] for i in race_day_idx if i < len(hourly.get(key, []))]
        return round(sum(vals) / len(vals), 1) if vals else None

    race_hour_summary = {
        "temp_c": avg_at_race("temperature_2m"),
        "humidity_pct": avg_at_race("relativehumidity_2m"),
        "precip_prob_pct": avg_at_race("precipitation_probability"),
        "precip_mm": avg_at_race("precipitation"),
        "wind_kph": avg_at_race("windspeed_10m"),
        "cloud_pct": avg_at_race("cloudcover"),
    }

    # Daily summary for the whole weekend
    daily_summary = {}
    for i, date in enumerate(daily.get("time", [])):
        daily_summary[date] = {
            "max_c": daily["temperature_2m_max"][i] if i < len(daily.get("temperature_2m_max", [])) else None,
            "min_c": daily["temperature_2m_min"][i] if i < len(daily.get("temperature_2m_min", [])) else None,
            "precip_sum_mm": daily["precipitation_sum"][i] if i < len(daily.get("precipitation_sum", [])) else None,
            "precip_prob_max": daily["precipitation_probability_max"][i] if i < len(daily.get("precipitation_probability_max", [])) else None,
        }

    return {
        "circuit": circuit,
        "race_date": race_date,
        "location": loc,
        "race_window_forecast": race_hour_summary,
        "daily": daily_summary,
        "condition": _classify_condition(race_hour_summary),
        "strategy_implication": _weather_strategy_note(race_hour_summary),
    }


def _classify_condition(f: dict) -> str:
    """Simple condition string from forecast dict."""
    if f.get("precip_prob_pct", 0) and f["precip_prob_pct"] > 60:
        return "WET / INTERMEDIATE likely"
    elif f.get("precip_prob_pct", 0) and f["precip_prob_pct"] > 30:
        return "MIXED — monitor closely"
    elif f.get("temp_c", 25) and f["temp_c"] > 35:
        return "HOT — high tyre deg expected"
    elif f.get("temp_c", 25) and f["temp_c"] < 15:
        return "COOL — slower tyre warm-up"
    else:
        return "DRY — normal conditions"


def _weather_strategy_note(f: dict) -> str:
    """One-line strategy implication from conditions."""
    precip = f.get("precip_prob_pct", 0) or 0
    temp = f.get("temp_c", 25) or 25

    if precip > 60:
        return "High wet probability: consider Intermediate/Wet on standby, monitor SC probability spike."
    elif precip > 30:
        return "Mixed conditions: split strategy viable — one driver on inters as information scout."
    elif temp > 35:
        return "High heat: softer compounds will degrade faster, extend hard stints where possible."
    elif temp < 15:
        return "Cool conditions: tyres take longer to activate, avoid pitting for option tyres too early."
    else:
        return "Stable dry conditions: execute nominal strategy, watch rival undercut windows."


def _fallback_weather(circuit: str, race_date: str) -> dict:
    """Return neutral defaults when API is unavailable."""
    return {
        "circuit": circuit,
        "race_date": race_date,
        "location": CIRCUIT_LOCATIONS.get(circuit, {}),
        "race_window_forecast": {
            "temp_c": 22.0,
            "humidity_pct": 60,
            "precip_prob_pct": 10,
            "precip_mm": 0.0,
            "wind_kph": 15.0,
            "cloud_pct": 30,
        },
        "daily": {},
        "condition": "DRY (fallback — no API data)",
        "strategy_implication": "Unable to fetch live forecast. Assume dry conditions.",
    }
