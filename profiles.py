"""User profile persistence for the Windfinder app and alert service.

Profiles live in a single UTF-8 JSON file (users.json) next to this module.
The schema is deliberately plain so it can be edited by hand:

{
  "alex": {
    "email": "rider@example.com",
    "check_times": ["07:30", "18:30"],
    "alert_days": "both",
    "settings": {
      "base_wind": [10.0, 20.0],
      "max_gust_spread": 10.0,
      "max_total_gust_kn": 28.0,
      "min_water_level": 0.20,
      "daily_time_window": [8, 20],
      "active_spots": ["Hooksiel", "Norddeich"]
    }
  }
}

This module is intentionally free of Streamlit and of wind_forecast imports so
the background alert service can use it without pulling in the UI stack.
"""

import json
import os
import re
import tempfile
from pathlib import Path

USERS_PATH = Path(__file__).with_name("users.json")

# Default settings for a freshly created profile. Mirrors the app defaults so a
# new user starts from exactly what the sidebar shows on a cold start.
DEFAULT_SETTINGS = {
    "base_wind": [9.0, 30.0],
    "max_gust_spread": 30.0,
    "max_total_gust_kn": 28.0,
    "min_water_level": 0.20,
    "daily_time_window": [0, 23],
    "active_spots": ["Hooksiel", "Norddeich", "Schillig", "Neuharlingersiel"],
}

# "07:30" / "7:30" -> normalised to zero-padded HH:MM.
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

# Which forecast days an alert may cover. Stored per profile as one of these
# keys; both the app and the alert service read this list.
ALERT_DAYS = ["today", "tomorrow", "both", "all"]


def normalise_alert_days(raw, default="both"):
    """Coerce the stored day scope to a known key."""
    value = str(raw or "").strip().lower()
    return value if value in ALERT_DAYS else default


def ensure_users_file(path=USERS_PATH):
    """Make sure a writable users.json file exists; return its status.

    Two cases matter for deployment:
      * missing file -> create it as {} so the first save has somewhere to go,
      * a DIRECTORY at that path -> Docker creates one when a bind mount's
        source does not exist on the host, which would make every save fail.
        It is replaced by an empty file so the service still works.

    Returns True when the path is a usable file afterwards.
    """
    path = Path(path)
    try:
        if path.is_dir():
            path.rmdir()          # only succeeds when empty
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        return True
    except OSError:
        return False


def load_users(path=USERS_PATH):
    """Read the profile file. Returns {} when it is missing or unreadable.

    A corrupt file is not fatal: the caller gets an empty mapping so the UI can
    still start, rather than the whole app failing to boot.
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_users(users_dict, path=USERS_PATH):
    """Write the profile file, atomically where the filesystem allows it.

    A temp file plus os.replace() keeps readers (the alert service) from ever
    seeing a half-written document. That rename fails when the path is a Docker
    *file* bind mount, because such a file is a mount point and cannot be
    replaced ("Device or resource busy"). In that case the data is written
    in place, which keeps the deployment working; readers then rely on the write
    being short and the JSON being parseable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(users_dict, indent=2, ensure_ascii=False) + "\n"

    tmp = None
    try:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=path.name,
            suffix=".tmp", delete=False)
        tmp = Path(handle.name)
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        tmp = None
        return users_dict
    except OSError:
        # Fall through to the in-place write below.
        pass
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return users_dict


def normalise_check_times(raw):
    """Accepts ['07:30','18:30'] or '07:30, 18:30' and returns sorted HH:MM."""
    if isinstance(raw, str):
        items = [part for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        return []

    cleaned = set()
    for item in items:
        match = _TIME_RE.match(str(item))
        if not match:
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            cleaned.add(f"{hour:02d}:{minute:02d}")
    return sorted(cleaned)


def _as_pair(raw, default, cast=float):
    """Coerce a 2-item sequence into a (lo, hi) tuple, falling back to default."""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            lo, hi = cast(raw[0]), cast(raw[1])
        except (TypeError, ValueError):
            return tuple(default)
        return (lo, hi) if lo <= hi else (hi, lo)
    return tuple(default)


def _as_number(raw, default, cast=float):
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return cast(default)


def normalise_settings(raw, valid_spots=None):
    """Coerce a stored settings block into the expected shapes and ranges.

    The file is user-editable, so every field is validated rather than trusted.
    Unknown spot names are dropped; an empty result falls back to the default.
    """
    raw = raw if isinstance(raw, dict) else {}
    settings = {
        "base_wind": _as_pair(raw.get("base_wind"),
                              DEFAULT_SETTINGS["base_wind"], float),
        "max_gust_spread": _as_number(raw.get("max_gust_spread"),
                                      DEFAULT_SETTINGS["max_gust_spread"]),
        "max_total_gust_kn": _as_number(raw.get("max_total_gust_kn"),
                                        DEFAULT_SETTINGS["max_total_gust_kn"]),
        "min_water_level": _as_number(raw.get("min_water_level"),
                                      DEFAULT_SETTINGS["min_water_level"]),
        "daily_time_window": _as_pair(raw.get("daily_time_window"),
                                      DEFAULT_SETTINGS["daily_time_window"], int),
    }

    spots = raw.get("active_spots")
    if isinstance(spots, (list, tuple)):
        spots = [str(s) for s in spots]
    else:
        spots = []
    if valid_spots is not None:
        spots = [s for s in spots if s in valid_spots]
    settings["active_spots"] = spots or list(DEFAULT_SETTINGS["active_spots"])
    return settings


def normalise_profile(raw, valid_spots=None):
    """Coerce one profile entry (email, check_times, alert_days, settings)."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "email": str(raw.get("email", "") or "").strip(),
        "check_times": normalise_check_times(raw.get("check_times", [])),
        # Default "both" matches the behaviour before this option existed.
        "alert_days": normalise_alert_days(raw.get("alert_days")),
        "settings": normalise_settings(raw.get("settings"), valid_spots),
    }


def new_profile(email="", check_times=None, settings=None, valid_spots=None,
                alert_days="both"):
    """Build a complete profile, merged over the defaults."""
    profile = normalise_profile(
        {"email": email,
         "check_times": check_times or [],
         "alert_days": alert_days,
         "settings": settings or {}},
        valid_spots)
    return profile


def spot_names():
    """Valid spot names, imported lazily so this module stays UI-free."""
    try:
        from wind_forecast import SPOTS
    except Exception:
        return None
    return list(SPOTS)
