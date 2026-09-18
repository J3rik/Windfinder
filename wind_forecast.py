"""Minimal prototype: rideable wind + tide windows for Hooksiel and Norddeich.

Data sources (Open-Meteo, no API key):
  * Wind : https://api.open-meteo.com/v1/forecast
  * Tide : https://marine-api.open-meteo.com/v1/marine

Wind uses the ICON seamless blend (DWD): the ultra-fine 2.2 km ICON-D2 model
covers days 1-2, then the request automatically blends into the 7 km ICON-EU
model for days 3-7. That gives a 7-day horizon, so forecast_days=7 -- matched by
the marine request range. Times are local German time (MEZ/MESZ) via
timezone=Europe/Berlin.

An hour is only printed when ALL hold:
  1. water level >= MIN_WATER_LEVEL (enough water over the mudflat),
  2. wind direction is inside the spot's allowed (side-onshore/onshore) range,
  3. the local hour falls inside the personal START_HOUR..END_HOUR window,
  4. base wind sits inside MIN_WIND_KN..MAX_WIND_KN, and
  5. the gust jump (gusts - base wind) stays within MAX_GUST_SPREAD_KN.
Hours failing any test are dropped, not marked.

Stdlib only -- no external dependencies.
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# User configuration -- edit these to match your own preferences.
# ---------------------------------------------------------------------------

# Acceptable base wind speed (knots). Hours outside this band are dropped.
MIN_WIND_KN = 9.0
MAX_WIND_KN = 30.0

# Maximum tolerable gust jump: (gusts - base wind) must not exceed this.
MAX_GUST_SPREAD_KN = 30.0

# Hard ceiling on the absolute gust value. A gust above this rejects the hour
# even when base wind and gust spread are both within their own limits.
MAX_TOTAL_GUST_KN = 28.0

# Personal availability, local German time in 24-hour format.
# The window is half-open: START_HOUR <= hour < END_HOUR, so with the defaults
# below the last printed hour is 19:00 and the session ends at 20:00.
START_HOUR = 0
END_HOUR = 23

# Minimum water level (metres MSL) before the mudflat is rideable.
MIN_WATER_LEVEL = 0.20

# Detail level for the console output.
#   False -> compact dashboard: spot header + day overview only.
#   True  -> also print the full hourly tables and filter breakdowns.
SHOW_DETAILS = False

# ---------------------------------------------------------------------------
# Data sources and model settings.
# ---------------------------------------------------------------------------

WIND_API_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"

# ICON seamless: 2.2 km ICON-D2 for days 1-2, blending into 7 km ICON-EU for
# the following days. Used for the wind request; the marine API has no model
# switch. Both endpoints serve 8 days (192 h).
MODEL = "icon_seamless"
FORECAST_DAYS = 8
TIMEZONE = "Europe/Berlin"

# Water level must move by more than this (metres) to count as rising/falling.
TIDE_EPSILON = 0.005

# ---------------------------------------------------------------------------
# ANSI colour codes for terminal highlighting. No external library needed.
# ---------------------------------------------------------------------------

RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"

# Waterfront kite surf zones, each with its allowed wind direction sector.
# `allowed` is (start, end) in degrees and may wrap through 0/360. The sector is
# inclusive of both endpoints; everything else is K.O. offshore wind.
SPOTS = {
    "Hooksiel": {
        "latitude": 53.6450,
        "longitude": 8.0330,
        "allowed": (320, 120),   # NW through N to ESE; K.O. 121-319 (Süd/West)
    },
    "Norddeich": {
        "latitude": 53.6265,
        "longitude": 7.1550,
        "allowed": (240, 70),    # WSW through N to ENE; K.O. 71-239 (Süd)
    },
    "Schillig": {
        "latitude": 53.7040,
        "longitude": 8.0280,
        "allowed": (300, 130),   # WNW through N to SE; K.O. 131-299 (Süd/Südwest)
    },
    "Neuharlingersiel": {
        "latitude": 53.7015,
        "longitude": 7.7070,
        "allowed": (280, 80),    # WNW through N to ENE; K.O. 81-279 (Süd/Südwest/Ost)
    },

    # --- Ostfriesische Inseln (schnell per Fähre erreichbar) ---
    "Norderney": {
        "latitude": 53.7120,
        "longitude": 7.1600,
        "allowed": (230, 80),    # WSW über N bis ONO; K.O. 81-229 (Süd)
    },
    "Borkum": {
        "latitude": 53.5920,
        "longitude": 6.6600,
        "allowed": (210, 70),    # SSW über W/NW/N bis ENE; K.O. 71-209 (Süd/Südost)
    },

    # --- Festland-Ausweichspots bei Südwest (per Auto via Wesertunnel / A28) ---
    "Cuxhaven_Sahlenburg": {
        "latitude": 53.8620,
        "longitude": 8.5900,
        "allowed": (200, 30),    # SSW über W, NW bis NNE; K.O. 31-199 (Ost/Südost)
    },
    "Wremen": {
        "latitude": 53.6490,
        "longitude": 8.4980,
        "allowed": (190, 340),   # SSW/SW über W bis NNW; K.O. 341-189 (Ost/ablandig)
    },
}

HOURLY_VARIABLES = ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"]
MARINE_VARIABLES = ["sea_level_height_msl"]

# 16-point compass rose, indexed by round(degrees / 22.5) mod 16.
COMPASS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


@dataclass(frozen=True)
class Config:
    """The five filter thresholds, bundled so a caller (e.g. Streamlit) can
    vary them per run. Frozen, so it is hashable and usable as a cache key.

    The defaults mirror the constants above; the filtering rules themselves are
    unchanged and live in build_hours().
    """

    min_wind_kn: float = MIN_WIND_KN
    max_wind_kn: float = MAX_WIND_KN
    max_gust_spread_kn: float = MAX_GUST_SPREAD_KN
    max_total_gust_kn: float = MAX_TOTAL_GUST_KN
    start_hour: int = START_HOUR
    end_hour: int = END_HOUR
    min_water_level: float = MIN_WATER_LEVEL

    def summary(self):
        """One-line description of the active thresholds (used by CLI and app)."""
        return (f"water >= {self.min_water_level:.2f} m | "
                f"wind {self.min_wind_kn:.0f}-{self.max_wind_kn:.0f} kn | "
                f"gust jump <= {self.max_gust_spread_kn:.1f} kn | "
                f"gust ceiling <= {self.max_total_gust_kn:.1f} kn | "
                f"hours {self.start_hour:02d}:00-"
                f"{min(self.end_hour + 1, 24):02d}:00")


DEFAULT_CONFIG = Config()


def compass_point(degrees):
    """Convert a wind direction in degrees to a compass label such as NW."""
    if degrees is None:
        return "?"
    return COMPASS[round(degrees / 22.5) % 16]


def in_allowed_sector(direction, allowed):
    """True if `direction` (degrees) lies inside the inclusive `allowed` sector.

    Uses modular arithmetic so a sector that wraps through 0/360 works without
    a special case: e.g. Hooksiel (320, 120) spans 320..360 plus 0..120.
    """
    if direction is None:
        return False
    start, end = allowed
    span = (end - start) % 360
    offset = (direction - start) % 360
    return offset <= span


def _get_json(url, params):
    """GET an Open-Meteo endpoint and return the parsed JSON body."""
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{query}", timeout=30) as response:
        return json.load(response)


def fetch_wind(latitude, longitude, forecast_days=FORECAST_DAYS):
    """Fetch hourly wind forecast (ICON-D2) from the Open-Meteo forecast API."""
    return _get_json(WIND_API_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY_VARIABLES),
        "models": MODEL,
        "wind_speed_unit": "kn",
        "forecast_days": forecast_days,
        "timezone": TIMEZONE,
    })


def fetch_tide(latitude, longitude, forecast_days=FORECAST_DAYS):
    """Fetch hourly sea level height from the Open-Meteo marine API."""
    return _get_json(MARINE_API_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(MARINE_VARIABLES),
        "forecast_days": forecast_days,
        "timezone": TIMEZONE,
    })


def tide_states(levels):
    """Label each hour's tide trend by comparing it with the previous hour.

    The first hour has no predecessor, so it is reported as unknown.
    """
    states = [None]
    for previous, current in zip(levels, levels[1:]):
        if previous is None or current is None:
            states.append(None)
        elif current - previous > TIDE_EPSILON:
            states.append("Rising \u2197 (Flut)")
        elif previous - current > TIDE_EPSILON:
            states.append("Falling \u2198 (Ebbe)")
        else:
            states.append("Steady \u2192")
    return states


def build_hours(wind, tide, allowed, config=DEFAULT_CONFIG):
    """Merge wind and tide by timestamp and tag each hour as rideable or not.

    Every applicable rejection reason is recorded (not just the first), so the
    per-day summary can attribute each dropped hour to a cause.

    `config` carries the filter thresholds; passing None falls back to the
    script-level constants written in DEFAULT_CONFIG.
    """
    if config is None:
        config = DEFAULT_CONFIG
    tide_by_time = dict(zip(tide["hourly"]["time"],
                            tide["hourly"]["sea_level_height_msl"]))
    wind_hourly = wind["hourly"]
    levels = [tide_by_time.get(t) for t in wind_hourly["time"]]
    states = tide_states(levels)

    hours = []
    for time, speed, gust, direction, level, state in zip(
            wind_hourly["time"],
            wind_hourly["wind_speed_10m"],
            wind_hourly["wind_gusts_10m"],
            wind_hourly["wind_direction_10m"],
            levels,
            states):
        # Timestamps look like 2026-09-17T14:00; slice the local hour out.
        hour_of_day = int(time[11:13])
        delta = None if (speed is None or gust is None) else gust - speed

        reasons = []
        if level is None:
            reasons.append("no tide data")
        elif level < config.min_water_level:
            reasons.append("tide too low")
        if not in_allowed_sector(direction, allowed):
            reasons.append("offshore wind")
        if not config.start_hour <= hour_of_day < config.end_hour:
            reasons.append("outside time window")
        if speed is None:
            reasons.append("no wind data")
        elif not config.min_wind_kn <= speed <= config.max_wind_kn:
            reasons.append("wind too low/high")
        if delta is None:
            if speed is not None:
                reasons.append("no gust data")
        elif delta > config.max_gust_spread_kn:
            reasons.append("too gusty")
        if gust is not None and gust > config.max_total_gust_kn:
            reasons.append("gust ceiling exceeded")

        hours.append({
            "time": time,
            "date": time[:10],
            "hour": hour_of_day,
            "speed": speed,
            "gust": gust,
            "delta": delta,
            "direction": direction,
            "level": level,
            "state": state,
            "reasons": reasons,
        })
    return hours


def _stats_text(kept):
    """Plain-text stats for a rideable day, without leading count/label."""
    speeds = [h["speed"] for h in kept]
    peak = max(kept, key=lambda h: h["speed"])
    return (f"{_window_text(kept)}  "
            f"wind {min(speeds):.0f}-{max(speeds):.0f} kn  "
            f"peak gust {peak['gust']:.0f} kn {compass_point(peak['direction'])}")


def print_spot(spot, coords, wind, tide, hours, config=DEFAULT_CONFIG):
    """Print the spot header, the colour-coded day overview, and optional tables.

    In compact mode (SHOW_DETAILS = False) only the header and overview print, so
    several spots fit on one screen as a dashboard.
    """
    rideable = [h for h in hours if not h["reasons"]]
    start, end = coords["allowed"]

    print()
    print(f"=== {spot} ===")
    print(f"wind  lat {coords['latitude']}, lon {coords['longitude']} | "
          f"model {MODEL} | local time ({wind['timezone']}) | "
          f"unit {wind['hourly_units']['wind_speed_10m']}")
    print(f"tide  marine grid cell {round(tide['latitude'], 3)}, "
          f"{round(tide['longitude'], 3)} | "
          f"unit {tide['hourly_units']['sea_level_height_msl']} MSL")
    print(f"ride  {config.summary()} | "
          f"direction {start}\u00b0-{end}\u00b0 "
          f"({compass_point(start)}-{compass_point(end)})")

    # Preserve forecast order; days appear in the order the timestamps do.
    dates = list(dict.fromkeys(h["date"] for h in hours))
    by_date = {date: [h for h in hours if h["date"] == date] for date in dates}

    # Day overview: the compact dashboard, and a week-at-a-glance index in full mode.
    print()
    print("day overview")
    for date in dates:
        day = by_date[date]
        kept = [h for h in day if not h["reasons"]]
        label = _format_date(date)

        if kept:
            body = f"{len(kept):>2}h rideable  {_stats_text(kept)}"
            if SHOW_DETAILS:
                print(f"  {label:<16} {body}")
            else:
                # Colour the whole status block so good days pop out. The label is
                # kept outside the colour run so columns stay aligned.
                print(f"  {label:<16} {GREEN}{body}{RESET}")
        else:
            print(f"  {label:<16} {RED}no rideable window{RESET}")

    if not SHOW_DETAILS:
        _print_total(rideable, hours)
        return

    for date in dates:
        day = by_date[date]
        kept = [h for h in day if not h["reasons"]]
        date_label = _format_date(date)

        print()
        if not kept:
            print(f"No rideable window found for {date_label}.")
            print(f"  {len(day)} hours checked: {_reason_counts(day)}")
            continue

        print(f"--- {date_label} | {len(kept)} of {len(day)} hours rideable ---")
        print(f"{'Date/Time':<17} {'Wind (kn)':>9} {'Gusts (kn)':>10} "
              f"{'Gust Delta':>11} {'Dir':>8} {'Water Level':>12} "
              f"{'Tide State':<16}")
        print("-" * 90)
        for h in kept:
            direction_text = f"{compass_point(h['direction'])} {h['direction']:.0f}\u00b0"
            print(f"{h['time']:<17} {h['speed']:>9.1f} {h['gust']:>10.1f} "
                  f"{h['delta']:>+10.1f}  {direction_text:>8} "
                  f"{h['level']:>+11.2f} m {h['state'] or '--':<16}")
        print("-" * 90)

    _print_total(rideable, hours, details=True)


def _print_total(rideable, hours, details=False):
    """Colour-coded total: green when at least one hour is rideable, else red."""
    total = (f"{len(rideable)} rideable hours out of {len(hours)} "
             f"({_percent(len(rideable), len(hours))})")
    colour = GREEN if rideable else RED
    print()
    print(f"{colour}{total}{RESET}")
    if details and len(rideable) < len(hours):
        print(f"  filtered: {_reason_counts(hours)}")


def _window_text(kept):
    """Describe rideable hours as a time window without implying they are contiguous.

    Contiguous hours collapse to '12:00-18:00'. Gaps mean the window is broken,
    so it reports e.g. '08:00+19:00 (2x)' rather than a misleading span.
    """
    times = [h["time"][11:16] for h in kept]
    hours = [h["hour"] for h in kept]
    contiguous = all(b - a == 1 for a, b in zip(hours, hours[1:]))
    if contiguous:
        # END_HOUR is exclusive, so a block ending at 19:00 ends at 20:00.
        last = kept[-1]["hour"] + 1
        return f"{times[0]}-{last:02d}:00"
    return f"{times[0]}+{times[-1]} ({len(kept)}x)"


def _reason_counts(hours):
    """Summarise rejection reasons, e.g. '12h tide too low, 20h wind too low/high'."""
    counts = {}
    for hour in hours:
        for reason in hour["reasons"]:
            counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return "none"
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    return ", ".join(f"{n}h {reason}" for reason, n in ordered)


def _format_date(date):
    """Render an ISO date (YYYY-MM-DD) as e.g. 'Thu 17 Sep 2026'."""
    from datetime import date as _date
    d = _date.fromisoformat(date)
    return d.strftime("%a %d %b %Y")


def _percent(part, whole):
    return "0%" if not whole else f"{100 * part / whole:.0f}%"


def main():
    for spot, coords in SPOTS.items():
        wind = fetch_wind(coords["latitude"], coords["longitude"])
        tide = fetch_tide(coords["latitude"], coords["longitude"])
        hours = build_hours(wind, tide, coords["allowed"])
        print_spot(spot, coords, wind, tide, hours)


if __name__ == "__main__":
    main()
