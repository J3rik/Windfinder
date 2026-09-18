#!/usr/bin/env python3
"""Standalone alert worker: notifies users when a rideable window is coming up.

Run it alongside the Streamlit app:

    .venv/bin/python alert_service.py            # run continuously
    .venv/bin/python alert_service.py --once     # single pass, then exit
    .venv/bin/python alert_service.py --test     # ignore check_times, alert now
    .venv/bin/python alert_service.py --list     # show profiles and next runs

Design notes
------------
* users.json is re-read at the start of every cycle, so profile edits made in
  the Streamlit UI take effect without restarting this service.
* Each cycle compares the current Europe/Berlin time against every user's
  check_times. A (user, time) pair fires at most once per day, tracked in an
  in-memory set, so a restart at most repeats the current minute.
* Alerts always go to the log. Email is sent as well when the SMTP_* environment
  variables below are present; without them the service stays log-only.
"""

import argparse
import html
import json
import logging
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import profiles
import wind_forecast as wf

TIMEZONE = ZoneInfo(wf.TIMEZONE)
POLL_SECONDS = 30          # how often to re-read the clock (cheap)
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
ENV_PATH = Path(__file__).with_name(".env")


def load_env_file(path=ENV_PATH):
    """Load KEY=VALUE lines from .env into os.environ (without overwriting).

    Keeps credentials out of the source and out of the shell history. Real
    environment variables always win, so `WINDFINDER_SMTP_HOST=... python
    alert_service.py` still overrides the file.
    """
    if not path.exists():
        return {}
    loaded = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
            loaded[key] = value
    except OSError as error:
        log.warning("could not read %s: %s", path, error)
    return loaded


load_env_file()


def _env(*names, default=""):
    """Return the first non-empty env var among `names`.

    Accepts several spellings so both the documented WINDFINDER_SMTP_* names
    and the shorter SMTP_* names work in .env or the shell.
    """
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return default


# Email delivery. Host plus sender are the minimum; user/password are optional
# for relays that do not require authentication.
SMTP_HOST = _env("SMTP_SERVER", "WINDFINDER_SMTP_HOST", "SMTP_HOST")
try:
    SMTP_PORT = int(_env("SMTP_PORT", "WINDFINDER_SMTP_PORT", default="587"))
except ValueError:
    SMTP_PORT = 587
SMTP_USER = _env("SMTP_USER", "WINDFINDER_SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "WINDFINDER_SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_SENDER", "WINDFINDER_SMTP_FROM", "SMTP_FROM",
                 default=SMTP_USER)
SMTP_STARTTLS = _env("SMTP_STARTTLS", "WINDFINDER_SMTP_STARTTLS",
                     default="1") != "0"

# Ports tried if the configured port cannot be reached. Comma separated; set
# SMTP_FALLBACK_PORTS="" to disable the fallback entirely.
SMTP_FALLBACK_PORTS = [
    int(p) for p in _env("SMTP_FALLBACK_PORTS", default="25,465").split(",")
    if p.strip().isdigit()
]

log = logging.getLogger("windfinder.alerts")


def email_enabled():
    """True when the credentials required to authenticate are all present.

    SMTP_USER and SMTP_PASSWORD are mandatory: this service authenticates on
    every send, so a missing credential is a configuration error rather than a
    reason to attempt an anonymous relay.
    """
    return bool(SMTP_HOST and SMTP_FROM and SMTP_USER and SMTP_PASSWORD)


def email_config_error():
    """Describe what is missing for email, or None when it is usable."""
    missing = [name for name, value in (
        ("SMTP_SERVER", SMTP_HOST),
        ("SMTP_USER", SMTP_USER),
        ("SMTP_PASSWORD", SMTP_PASSWORD),
        ("SMTP_SENDER", SMTP_FROM),
    ) if not value]
    if not missing:
        return None
    return ("email is not configured: set " + ", ".join(missing)
            + " (see .env.example). Alerts are logged only.")


def smtp_status():
    """Human-readable state of the SMTP configuration, for --list output."""
    if email_enabled():
        return (f"on ({SMTP_HOST}:{SMTP_PORT}, from {SMTP_FROM}, auth, "
                f"STARTTLS {'on' if SMTP_STARTTLS else 'off'})")
    missing = [name for name, value in (
        ("SMTP_SERVER", SMTP_HOST),
        ("SMTP_USER", SMTP_USER),
        ("SMTP_PASSWORD", SMTP_PASSWORD),
        ("SMTP_SENDER", SMTP_FROM),
    ) if not value]
    return f"off (missing {', '.join(missing)})"


def config_for(profile):
    """Build a wf.Config from a stored profile's settings block."""
    settings = profiles.normalise_settings(profile.get("settings"),
                                           profiles.spot_names())
    return wf.Config(
        min_wind_kn=settings["base_wind"][0],
        max_wind_kn=settings["base_wind"][1],
        max_gust_spread_kn=settings["max_gust_spread"],
        max_total_gust_kn=settings["max_total_gust_kn"],
        start_hour=settings["daily_time_window"][0],
        end_hour=settings["daily_time_window"][1],
        min_water_level=settings["min_water_level"],
    ), settings


def evaluate_user(name, profile, forecast_days=wf.FORECAST_DAYS):
    """Run the rideability evaluation for one user.

    Reuses the app's filtering rules via wind_forecast.build_hours, so the
    service and the dashboard can never disagree about what is rideable.
    Returns a list of per-spot result dicts.
    """
    config, settings = config_for(profile)
    results = []
    for spot in settings["active_spots"]:
        coords = wf.SPOTS.get(spot)
        if coords is None:
            continue
        try:
            wind = wf.fetch_wind(coords["latitude"], coords["longitude"],
                                 forecast_days)
            tide = wf.fetch_tide(coords["latitude"], coords["longitude"],
                                 forecast_days)
        except Exception as error:  # network trouble must not kill the cycle
            log.warning("  %s/%s: fetch failed (%s)", name, spot, error)
            continue
        hours = wf.build_hours(wind, tide, coords["allowed"], config)
        rideable = [h for h in hours if not h["reasons"]]
        if rideable:
            results.append({"spot": spot, "hours": rideable,
                            "total": len(hours)})
    return results


def _daily_windows(hours):
    """Group rideable hours by date, merging contiguous runs into windows.

    Returns (date, [hours]) pairs where each list is one contiguous run, so the
    per-window stats describe that window only and not the whole day.
    """
    by_date = {}
    for hour in hours:
        by_date.setdefault(hour["date"], []).append(hour)

    windows = []
    for date, items in sorted(by_date.items()):
        items.sort(key=lambda h: h["hour"])
        run = [items[0]]
        for hour in items[1:]:
            if hour["hour"] == run[-1]["hour"] + 1:
                run.append(hour)
            else:
                windows.append((date, run))
                run = [hour]
        windows.append((date, run))
    return windows


# German weekday abbreviations, matching the app's own labels.
_WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_MONTHS_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
              "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _day_label(iso_date):
    """'Heute, Fr 18. Sep' style label, so a mail is readable without counting."""
    try:
        day = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return iso_date
    today = datetime.now(TIMEZONE).date()
    delta = (day - today).days
    prefix = {0: "Heute", 1: "Morgen"}.get(delta)
    stamp = (f"{_WEEKDAYS_DE[day.weekday()]} {day.day}. "
             f"{_MONTHS_DE[day.month - 1]}")
    return f"{prefix}, {stamp}" if prefix else stamp


def allowed_dates(scope, today=None, days=wf.FORECAST_DAYS):
    """Set of ISO dates an alert may cover for the given day scope.

    "today" and "tomorrow" cover exactly those days, "both" covers the two,
    "all" leaves the whole forecast open. Unknown scopes behave like "both".
    """
    today = today or datetime.now(TIMEZONE).date()
    scope = profiles.normalise_alert_days(scope)
    if scope == "today":
        wanted = [0]
    elif scope == "tomorrow":
        wanted = [1]
    elif scope == "all":
        return {(today + timedelta(days=offset)).isoformat()
                for offset in range(days)}
    else:  # both
        wanted = [0, 1]
    return {(today + timedelta(days=offset)).isoformat() for offset in wanted}


def filter_by_days(results, scope, today=None):
    """Drop rideable hours outside the user's chosen day scope."""
    keep = allowed_dates(scope, today)
    filtered = []
    for result in results:
        hours = [h for h in result["hours"] if h["date"] in keep]
        if hours:
            filtered.append({**result, "hours": hours})
    return filtered


def format_alert(name, results):
    """Plain-text fallback body. The HTML version carries the styling."""
    lines = [f"Rideable windows for {name}"]
    for window in collect_windows(results):
        line = (f"{window['day_label']}, {window['range']}  {window['spot']}  "
                f"wind {window['wind']} kn  gusts to {window['peak']:.0f} kn  "
                f"{window['compass']}")
        if window["level_text"]:
            line += f"  tide {window['level_text']} m"
        lines.append(line)
    return "\n".join(lines)


def collect_windows(results):
    """Flatten results into per-window dicts with everything the mail shows."""
    windows = []
    for result in results:
        for date, run in _daily_windows(result["hours"]):
            speeds = [h["speed"] for h in run]
            levels = [h["level"] for h in run if h["level"] is not None]
            direction = run[0]["direction"]
            windows.append({
                "date": date,
                "day_label": _day_label(date),
                "spot": result["spot"],
                "start": f"{run[0]['hour']:02d}:00",
                "end": f"{run[-1]['hour'] + 1:02d}:00",
                "range": f"{run[0]['hour']:02d}:00-{run[-1]['hour'] + 1:02d}:00",
                "hours": len(run),
                "wind": f"{min(speeds):.0f}-{max(speeds):.0f}",
                "peak": max(h["gust"] for h in run),
                "compass": wf.compass_point(direction) if direction is not None else "?",
                "direction": direction if direction is not None else 0.0,
                "level_text": (f"{min(levels):+.2f}..{max(levels):+.2f}"
                               if levels else ""),
            })
    return windows


def build_email_html(name, windows, generated=None):
    """Mobile-friendly HTML mail: single column, inline styles, no external assets.

    Inline CSS and a table-free layout are used deliberately: mail clients strip
    <style> blocks and media queries are unreliable, so the design has to hold up
    at phone width without them.
    """
    generated = generated or datetime.now(TIMEZONE).strftime("%d.%m.%Y %H:%M")
    total_hours = sum(w["hours"] for w in windows)

    cards = []
    for window in windows:
        tide = (f'<span style="color:#374151;">{window["level_text"]} m</span>'
                if window["level_text"] else
                '<span style="color:#9ca3af;">keine Daten</span>')
        cards.append(f'''
      <div style="padding:12px 0;border-top:1px solid #e5e7eb;">
        <div style="font-size:13px;font-weight:600;color:#6b7280;
                    text-transform:uppercase;letter-spacing:0.02em;">
          {html.escape(window["day_label"])}
        </div>
        <div style="font-size:17px;font-weight:600;color:#0f172a;">
          {html.escape(window["spot"])}
        </div>
        <div style="font-size:15px;color:#1d4ed8;font-weight:600;margin:2px 0 6px;">
          {html.escape(window["start"])}&ndash;{html.escape(window["end"])}
          <span style="color:#6b7280;font-weight:400;">
            &middot; {window["hours"]} h
          </span>
        </div>
        <div style="font-size:15px;color:#111827;line-height:1.6;">
          &#128168; Wind <b>{html.escape(window["wind"])} kn</b><br>
          &#127786; B&ouml;en bis <b>{window["peak"]:.0f} kn</b><br>
          &#129517; Richtung <b>{html.escape(window["compass"])}</b>
          ({window["direction"]:.0f}&deg;)<br>
          &#127754; Wasser {tide}
        </div>
      </div>''')

    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Windfinder</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;">
  <div style="max-width:600px;margin:0 auto;padding:16px;">
    <div style="background:#ffffff;border-radius:12px;padding:20px;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
                Helvetica,Arial,sans-serif;color:#111827;">

      <div style="font-size:20px;font-weight:700;color:#0f172a;">
        &#127940; Windfinder
      </div>
      <div style="font-size:15px;color:#374151;margin-top:4px;">
        Kitebare Fenster f&uuml;r <b>{html.escape(name)}</b>
      </div>
      <div style="display:inline-block;background:#dcfce7;color:#166534;
                  font-size:14px;font-weight:600;padding:6px 12px;
                  border-radius:999px;margin-top:10px;">
        {len(windows)} Fenster &middot; {total_hours} Stunden
      </div>

      {''.join(cards)}

      <div style="border-top:1px solid #e5e7eb;margin-top:14px;padding-top:12px;
                  font-size:12px;color:#9ca3af;line-height:1.5;">
        Erzeugt am {generated} (Europe/Berlin)<br>
        Daten: Open-Meteo &middot; ICON seamless &middot; Filter und Zeiten
        kannst du in der App anpassen.
      </div>
    </div>
  </div>
</body>
</html>'''


def _build_message(recipient, subject, text_body, html_body=None):
    """Build the message. HTML with a plain-text alternative when available."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    return message


def _try_send(host, port, message, use_starttls):
    """One delivery attempt. Returns (ok, error_or_None).

    Raises nothing: the caller decides whether to try another port.
    """
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            if use_starttls and server.has_extn("starttls"):
                server.starttls()
                server.ehlo()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
        return True, None
    except smtplib.SMTPAuthenticationError as error:
        # A credential problem will not be fixed by another port.
        return False, f"authentication rejected ({error.smtp_code})"
    except Exception as error:
        return False, error


def send_email(recipient, subject, body, html_body=None):
    """Send one email, falling back to alternate ports. Never raises.

    The configured port is tried first. If it cannot be reached (a firewall
    block or a provider rate-limit, which is what a burst of failed logins
    causes), the alternates are tried so an alert is not lost. A rejected login
    stops immediately instead of hammering the server.
    """
    if not email_enabled():
        log.error("  cannot send to %s - %s", recipient, email_config_error())
        return False

    message = _build_message(recipient, subject, body, html_body)
    ports = [SMTP_PORT] + [p for p in SMTP_FALLBACK_PORTS if p != SMTP_PORT]
    last_error = None

    for port in ports:
        ok, error = _try_send(SMTP_HOST, port, message, SMTP_STARTTLS)
        if ok:
            if port != SMTP_PORT:
                log.warning("  sent via fallback port %d (%d unreachable)",
                            port, SMTP_PORT)
            return True
        last_error = error
        log.warning("  port %d failed: %s", port, error)
        if isinstance(error, str) and error.startswith("authentication"):
            break

    log.error("  email to %s failed: %s", recipient, last_error)
    return False


def notify(name, profile, results, windows):
    """Deliver an alert to the log, and by email when configured."""
    body = format_alert(name, results)
    for line in body.splitlines():
        log.info("  %s", line)
    if not email_enabled():
        log.warning("  %s", email_config_error())
        return
    recipient = (profile.get("email") or "").strip()
    if not recipient:
        log.warning("  no email address for %s; skipped", name)
        return

    windows = windows or collect_windows(results)
    count = len(windows)
    days = len({w["date"] for w in windows})
    subject = (f"Windfinder: {count} kitebare Fenster "
               f"an {days} Tag(en) f\u00fcr {name}")
    if send_email(recipient, subject, body, build_email_html(name, windows)):
        log.info("  email sent to %s", recipient)


def run_cycle(fired, force=False):
    """One pass over all profiles. Returns the number of alerts sent."""
    users = profiles.load_users()          # fresh read every cycle
    if not users:
        log.info("no profiles in %s; nothing to do", profiles.USERS_PATH)
        return 0

    now = datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    current = now.strftime("%H:%M")
    sent = 0

    for name, raw in users.items():
        profile = profiles.normalise_profile(raw, profiles.spot_names())
        times = profile["check_times"]

        if not force:
            if current not in times:
                continue
            key = (name, today, current)
            if key in fired:
                continue
            fired.add(key)

        scope = profile["alert_days"]
        log.info("checking %s (scheduled %s, days %s)%s", name,
                 ", ".join(times) or "never", scope,
                 " [forced]" if force else "")
        try:
            results = evaluate_user(name, profile)
        except Exception as error:
            log.error("  evaluation failed for %s: %s", name, error)
            continue

        # Keep only the days this user asked about (today / tomorrow / ...).
        results = filter_by_days(results, scope)
        windows = collect_windows(results)

        if windows:
            log.info("  %d window(s) across %d spot(s)", len(windows),
                     len(results))
            notify(name, profile, results, windows)
            sent += 1
        else:
            log.info("  no rideable window for scope '%s'", scope)

    # Drop yesterday's dedupe keys so the set cannot grow without bound.
    for key in [k for k in fired if k[1] != today]:
        fired.discard(key)
    return sent


def next_check_times(users, first_only=True):
    """Upcoming check times today, for --list output."""
    now = datetime.now(TIMEZONE).strftime("%H:%M")
    upcoming = []
    for name, raw in users.items():
        profile = profiles.normalise_profile(raw, profiles.spot_names())
        later = [t for t in profile["check_times"] if t >= now]
        upcoming.append((name, profile, later[:1] if first_only else later))
    return upcoming, now


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true",
                        help="run a single cycle and exit")
    parser.add_argument("--test", action="store_true",
                        help="ignore check_times and alert for every user now")
    parser.add_argument("--list", action="store_true",
                        help="list profiles, check times and next run")
    parser.add_argument("--days", type=int, default=wf.FORECAST_DAYS,
                        help="forecast horizon to evaluate")
    parser.add_argument("--poll", type=int, default=POLL_SECONDS,
                        help="seconds between clock checks")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    profiles.ensure_users_file()
    users = profiles.load_users()
    if args.list:
        upcoming, now = next_check_times(users)
        print(f"profiles file : {profiles.USERS_PATH}")
        print(f"local time    : {now} ({wf.TIMEZONE})")
        print(f"env file      : {ENV_PATH} ({'found' if ENV_PATH.exists() else 'missing'})")
        print(f"email         : {smtp_status()}")
        if not users:
            print("no profiles defined")
        for name, profile, later in upcoming:
            print(f"  {name:<16} times={','.join(profile['check_times']) or '-':<14} "
                  f"spots={len(profile['settings']['active_spots'])}")
            print(f"  {'':<16} next today: {later[0] if later else 'none left'}")
        return 0

    if args.test:
        log.info("forced test run over %d profile(s)", len(users))
        sent = run_cycle(set(), force=True)
        log.info("done: %d alert(s)", sent)
        return 0

    if args.once:
        sent = run_cycle(set())
        log.info("done: %d alert(s)", sent)
        return 0

    log.info("alert service started (tz %s, poll %ds, email %s)",
             wf.TIMEZONE, args.poll, "on" if email_enabled() else "off")
    fired = set()
    while True:
        try:
            run_cycle(fired)
        except Exception as error:  # keep the worker alive no matter what
            log.exception("cycle failed: %s", error)
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
