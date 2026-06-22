"""
A minimal local MCP **server** built on the official SDK's FastMCP helper.

Phase 3/4: rather than depend on a third-party public weather server (which would
need an API key, network access and a stable contract we don't control), we run a
tiny server we own. It exposes two tools:

  • ``get_weather(city)`` — current conditions. Tries the free, key-less
    Open-Meteo API; if the network is unavailable it falls back to deterministic
    mock data so the demo always works offline.
  • ``echo(text)``        — trivial tool, handy for connectivity smoke-tests.

Run it directly for a manual check::

    python -m jarvis.mcp.servers.weather

It speaks MCP over **stdio**, so it is normally launched as a subprocess by the
client (see jarvis.mcp.client / jarvis.mcp.registry), not used standalone.
"""

from __future__ import annotations

import json
import ssl
from urllib.parse import urlencode
from urllib.request import urlopen

from mcp.server.fastmcp import FastMCP

# Use certifi's CA bundle when available so HTTPS works on Python builds whose
# default trust store isn't configured (the common macOS python.org case);
# fall back to the system default otherwise.
try:
    import certifi
    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = None

# Quiet the server's per-request INFO logging ("Processing request of type …").
# It goes to the subprocess stderr, which the client inherits, and would otherwise
# corrupt the CLI's in-place spinner line. Warnings/errors still surface.
mcp = FastMCP("weather", log_level="WARNING")

# Open-Meteo: free, no API key. Geocode the city, then read current weather.
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_HTTP_TIMEOUT_S = 6

# WMO weather-code → human description (abridged to the common cases).
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow",
    73: "snow", 75: "heavy snow", 80: "rain showers", 95: "thunderstorm",
}


def _get_json(url: str, params: dict) -> dict:
    with urlopen(f"{url}?{urlencode(params)}", timeout=_HTTP_TIMEOUT_S, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mock_weather(city: str) -> dict:
    """Deterministic offline fallback so the tool never hard-fails in a demo."""
    temp = 15 + (sum(ord(c) for c in city.lower()) % 15)
    return {
        "city": city.title(),
        "temperature_c": temp,
        "conditions": "partly cloudy (mock)",
        "source": "mock (network unavailable)",
    }


@mcp.tool()
def get_weather(city: str) -> str:
    """Return current weather for a city as a short human-readable line.

    Uses the free Open-Meteo API; falls back to mock data when offline.
    """
    try:
        geo = _get_json(_GEOCODE_URL, {"name": city, "count": 1})
        results = geo.get("results") or []
        if not results:
            return f"Unknown city: {city!r}. Try a different spelling."
        place = results[0]
        forecast = _get_json(_FORECAST_URL, {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,weather_code",
        })
        current = forecast.get("current", {})
        temp = current.get("temperature_2m")
        desc = _WMO.get(current.get("weather_code"), "unknown conditions")
        name = ", ".join(p for p in (place.get("name"), place.get("country")) if p)
        return f"{name}: {temp}°C, {desc} (source: Open-Meteo)"
    except Exception:
        data = _mock_weather(city)
        return (
            f"{data['city']}: {data['temperature_c']}°C, "
            f"{data['conditions']} (source: {data['source']})"
        )


@mcp.tool()
def echo(text: str) -> str:
    """Return the input unchanged — a connectivity smoke-test tool."""
    return text


def main() -> None:
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
