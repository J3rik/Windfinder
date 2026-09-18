"""Interactive Streamlit dashboard for rideable wind + tide windows.

Bilingual UI (German default, English optional). All data fetching, the tide
trend maths and the five filtering rules live in wind_forecast.py and stay in
English; this file only localises presentation and never feeds the language
into a cached fetch, so switching language re-renders without new API calls.

Run with:
    streamlit run app.py
"""

import pandas as pd
import streamlit as st

import profiles
import wind_forecast as wf

CACHE_TTL = 3600  # seconds; Open-Meteo refreshes hourly

LANGUAGES = ["Deutsch", "English"]

# Forecast spans offered in the sidebar. ICON seamless and the marine API both
# serve 8 days (192 h); 8 is the default and maximum.
FORECAST_DAY_OPTIONS = [2, 4, 8]
DEFAULT_FORECAST_DAYS = 8

# Fallback centre of East Frisia, used for sunrise/sunset only when no spot is
# selected. Otherwise the mean of the active spots is used.
REGION_LAT, REGION_LON = 53.5, 7.5

# German date parts are hardcoded rather than locale-based: strftime's %a/%b
# depend on the system locale, which is often missing de_DE (and is here).
WEEKDAYS = {
    "Deutsch": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "English": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
MONTHS = {
    "Deutsch": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    "English": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

TRANSLATIONS = {
    "Deutsch": {
        "language_label": "Sprache / Language",
        "app_title": "Wind & Gezeiten",
        "subtitle": "Open-Meteo · ICON seamless · deutsche Lokalzeit",
        "page_title": "Kitebare Wind- & Tidenfenster",
        "sec_wind": "Windbereich",
        "sec_gusts": "Böen",
        "sec_water": "Wasser",
        "sec_availability": "Verfügbarkeit",
        "sec_spots": "Spots",
        "sec_view": "Ansicht",
        "slider_wind": "Grundwind (kn)",
        "slider_gust": "Max. Böensprung (kn)",
        "slider_gust_help": "Erlaubter Sprung von Grundwind zur Böe.",
        "slider_gust_ceiling": "Max. Windstärke inkl. Böen (kn)",
        "slider_gust_ceiling_help": "Harte Obergrenze: Wenn eine Böe diesen Wert überschreitet, wird die Stunde aussortiert – selbst wenn Grundwind und Böensprung im Rahmen liegen.",
        "slider_water": "Min. Wasserstand (m MSL)",
        "slider_window": "Tageszeitfenster",
        "slider_window_help": "24-Stunden-Format. Die Endstunde ist ausgeschlossen.",
        "forecast_range": "Vorhersagezeitraum",
        "daylight_only": "Nur Tageslicht",
        "daylight_only_help": "Setzt das Zeitfenster auf die vollen Tageslichtstunden.",
        "sun_line": "\U0001f305 Sonnenaufgang ca. {sunrise} Uhr · "
                    "\U0001f307 Sonnenuntergang ca. {sunset} Uhr",
        "multiselect_spots": "Aktive Spots",
        "toggle_details": "Volle Details (Stundentabellen)",
        "btn_clear": "API-Zwischenspeicher leeren",
        "rideable_hours": "{n} fahrbare Stunden",
        "no_rideable_hours": "Keine fahrbaren Stunden",
        "no_window_badge": "Kein Zeitfenster",
        "hours_rideable": "{n} Std. fahrbar",
        "gusts_to": "Böen bis {x} kn",
        "wind_range": "Wind {min}-{max} kn",
        "wind_range_sec": "Windbereich {min}-{max} kn",
        "of_hours": "{n} von {total} Stunden",
        "week_blocker": "Häufigster Blocker der Woche: {reason} ({n} Stunden).",
        "expander": "Stundentabelle anzeigen",
        "map_expander": "\U0001f4cd Karte / Map",
        "open_in_maps": "\U0001f4cd In Google Maps öffnen",
        "map_caption": "Koordinaten {lat}, {lon} (Zoom 12)",
        "caption_onshore": "onshore-Sektor {start}°-{end}° ({sc}-{ec})",
        "caption_model": "Modell {model}",
        "legend": "{rideable} von {total} Stunden fahrbar · grüne Zeilen erfüllen alle Filter",
        "footer": "Über {spots} Spot(s): {rideable} fahrbare Stunden von {total} · Schwellen live angewendet, API-Antworten {ttl} Min. gecacht",
        "no_spots": "Bitte mindestens einen Spot in der Sidebar auswählen.",
        "load_error": "{spot}: Vorhersage konnte nicht geladen werden ({error})",
        "profile_label": "Nutzerprofil",
        "no_profiles": "Noch kein Profil vorhanden. Lege mit \u201e+ Neuer Nutzer\u201c "
                       "dein erstes Profil an, um Einstellungen zu speichern.",
        "users_file_unwritable": "users.json konnte nicht angelegt werden. Profile "
                                 "k\u00f6nnen nicht gespeichert werden \u2013 Volume-Mount "
                                 "und Schreibrechte pr\u00fcfen.",
        "save_settings": "\U0001f4be Einstellungen für {name} speichern",
        "save_settings_generic": "\U0001f4be Einstellungen speichern",
        "saved_toast": "Einstellungen für {name} gespeichert.",
        "new_user": "+ Neuer Nutzer",
        "new_user_name": "Nutzername",
        "new_user_email": "E-Mail-Adresse",
        "new_user_times": "Benachrichtigungszeiten (z. B. 07:30, 18:30)",
        "new_user_create": "Nutzer anlegen",
        "new_user_needs_name": "Bitte einen Nutzernamen angeben.",
        "new_user_exists": "Nutzer \"{name}\" existiert bereits.",
        "new_user_created": "Nutzer \"{name}\" angelegt.",
        "new_user_from_current": "Einstellungen aus der aktuellen Sidebar übernehmen",
        "alert_times_popover": "\u23f0 Alerts",
        "alert_days_label": "Tage",
        "alert_times_help": "Kommagetrennt im 24-Stunden-Format, z. B. 07:30, 18:30",
        "alert_times_save": "Alerts speichern",
        "alert_times_saved": "Alerts für {name}: {days} um {times}",
        "alert_times_none": "keine",
        "alert_times_invalid": "Keine gültigen Zeiten erkannt – bitte Format HH:MM verwenden.",
        "alert_days": {
            "today": "Nur heute",
            "tomorrow": "Nur morgen",
            "both": "Heute und morgen",
            "all": "Alle Vorhersagetage",
        },
        "reasons": {
            "offshore wind": "Ablandiger Wind",
            "tide too low": "Zu wenig Wasser (Watt trocken)",
            "too gusty": "Zu böig",
            "gust ceiling exceeded": "Böenspitze über Limit",
            "wind too low/high": "Wind zu schwach/stark",
            "outside time window": "Außerhalb des Zeitfensters",
            "no tide data": "Keine Tide-Daten",
            "no wind data": "Keine Winddaten",
            "no gust data": "Keine Böendaten",
        },
        "tide": {
            "Rising": "Steigend \u2197 (Flut)",
            "Falling": "Fallend \u2198 (Ebbe)",
            "Steady": "Gleichbleibend \u2192",
        },
        "cols": {
            "Date": "Datum", "Time": "Zeit", "Wind (kn)": "Wind (kn)",
            "Gusts (kn)": "Böen (kn)", "Gust Delta (kn)": "Böensprung (kn)",
            "Direction": "Richtung", "Water Level (m)": "Wasserstand (m)",
            "Tide": "Gezeit", "Rideable": "Fahrbar", "Blocked by": "Blockiert durch",
        },
    },
    "English": {
        "language_label": "Sprache / Language",
        "app_title": "Wind & Tide",
        "subtitle": "Open-Meteo · ICON seamless · local German time",
        "page_title": "Rideable wind & tide windows",
        "sec_wind": "Wind range",
        "sec_gusts": "Gusts",
        "sec_water": "Water",
        "sec_availability": "Availability",
        "sec_spots": "Spots",
        "sec_view": "View",
        "slider_wind": "Base wind (kn)",
        "slider_gust": "Max gust spread (kn)",
        "slider_gust_help": "Allowed jump from base wind to gust.",
        "slider_gust_ceiling": "Max wind incl. gusts (kn)",
        "slider_gust_ceiling_help": "Hard ceiling: If a gust exceeds this threshold, the hour is filtered out even if base wind and spread are within range.",
        "slider_water": "Min water level (m MSL)",
        "slider_window": "Daily time window",
        "slider_window_help": "24-hour format. The window excludes the end hour.",
        "forecast_range": "Forecast range",
        "daylight_only": "Daylight only",
        "daylight_only_help": "Clamps the window to the whole daylight hours.",
        "sun_line": "\U0001f305 Sunrise approx. {sunrise} · "
                    "\U0001f307 Sunset approx. {sunset}",
        "multiselect_spots": "Active spots",
        "toggle_details": "Full details (hourly tables)",
        "btn_clear": "Clear cached API data",
        "rideable_hours": "{n} rideable hours",
        "no_rideable_hours": "No rideable hours",
        "no_window_badge": "No rideable window",
        "hours_rideable": "{n}h rideable",
        "gusts_to": "Gusts to {x} kn",
        "wind_range": "Wind {min}-{max} kn",
        "wind_range_sec": "Wind range {min}-{max} kn",
        "of_hours": "{n} of {total} hours",
        "week_blocker": "Main blocker across the week: {reason} ({n} hours).",
        "expander": "Show hourly breakdown",
        "map_expander": "\U0001f4cd Map",
        "open_in_maps": "\U0001f4cd Open in Google Maps",
        "map_caption": "Coordinates {lat}, {lon} (zoom 12)",
        "caption_onshore": "onshore sector {start}°-{end}° ({sc}-{ec})",
        "caption_model": "model {model}",
        "legend": "{rideable} of {total} hours rideable · green rows pass every filter",
        "footer": "Across {spots} spot(s): {rideable} rideable hours out of {total} · thresholds applied live, API responses cached {ttl} min",
        "no_spots": "Select at least one spot in the sidebar to see the forecast.",
        "load_error": "{spot}: could not load forecast ({error})",
        "profile_label": "User profile",
        "no_profiles": "No profile yet. Use \u201c+ New User\u201d to create your first "
                       "profile so settings can be saved.",
        "users_file_unwritable": "users.json could not be created. Profiles cannot "
                                 "be saved - check the volume mount and its permissions.",
        "save_settings": "\U0001f4be Save settings for {name}",
        "save_settings_generic": "\U0001f4be Save settings",
        "saved_toast": "Settings saved for {name}.",
        "new_user": "+ New User",
        "new_user_name": "User name",
        "new_user_email": "Email address",
        "new_user_times": "Notification times (e.g. 07:30, 18:30)",
        "new_user_create": "Create user",
        "new_user_needs_name": "Please enter a user name.",
        "new_user_exists": "User \"{name}\" already exists.",
        "new_user_created": "Created user \"{name}\".",
        "new_user_from_current": "Copy settings from the current sidebar",
        "alert_times_popover": "\u23f0 Alerts",
        "alert_days_label": "Days",
        "alert_times_help": "Comma separated, 24-hour format, e.g. 07:30, 18:30",
        "alert_times_save": "Save alerts",
        "alert_times_saved": "Alerts for {name}: {days} at {times}",
        "alert_times_none": "none",
        "alert_times_invalid": "No valid times found – please use HH:MM.",
        "alert_days": {
            "today": "Today only",
            "tomorrow": "Tomorrow only",
            "both": "Today and tomorrow",
            "all": "All forecast days",
        },
        "reasons": {
            "offshore wind": "Offshore wind",
            "tide too low": "Mudflat dry (low water)",
            "too gusty": "Too gusty",
            "gust ceiling exceeded": "Gust ceiling exceeded",
            "wind too low/high": "Wind too low/high",
            "outside time window": "Outside time window",
            "no tide data": "No tide data",
            "no wind data": "No wind data",
            "no gust data": "No gust data",
        },
        "tide": {
            "Rising": "Rising \u2197 (Flut)",
            "Falling": "Falling \u2198 (Ebbe)",
            "Steady": "Steady \u2192",
        },
        "cols": {
            "Date": "Date", "Time": "Time", "Wind (kn)": "Wind (kn)",
            "Gusts (kn)": "Gusts (kn)", "Gust Delta (kn)": "Gust Delta (kn)",
            "Direction": "Direction", "Water Level (m)": "Water Level (m)",
            "Tide": "Tide", "Rideable": "Rideable", "Blocked by": "Blocked by",
        },
    },
}

# Most useful explanation first. Used both for the weekly headline and to pick
# one reason per hour when tallying a red day, so the hour counts sum to the
# number of checked hours instead of double-counting hours that fail twice.
REASON_PRIORITY = [
    "offshore wind",
    "tide too low",
    "wind too low/high",
    "too gusty",
    "gust ceiling exceeded",
    "outside time window",
    "no tide data",
    "no wind data",
    "no gust data",
]

TILE_COLORS = {
    "green": ("#0f5132", "#d1e7dd", "#a3cfbb"),
    "red": ("#842029", "#f8d7da", "#f1aeb5"),
}


def t(lang, key, **kwargs):
    """Look up a translated UI string, formatting any placeholders."""
    text = TRANSLATIONS[lang][key]
    return text.format(**kwargs) if kwargs else text


def reason_text(lang, reason):
    """Translate a reason key produced by wind_forecast.build_hours()."""
    return TRANSLATIONS[lang]["reasons"].get(reason, reason)


def tide_text(lang, state):
    """Translate the tide trend, keeping the (Flut)/(Ebbe) suffix in both languages."""
    if not state:
        return "--"
    for key in ("Rising", "Falling", "Steady"):
        if state.startswith(key):
            return TRANSLATIONS[lang]["tide"][key]
    return state


def format_day(lang, iso_date, with_year=False):
    """Localised short date, e.g. 'Do, 17. Sep' / 'Thu 17 Sep'."""
    stamp = pd.Timestamp(iso_date)
    weekday = WEEKDAYS[lang][stamp.weekday()]
    month = MONTHS[lang][stamp.month - 1]
    if lang == "Deutsch":
        text = f"{weekday}, {stamp.day}. {month}"
    else:
        text = f"{weekday} {stamp.day:02d} {month}"
    return f"{text} {stamp.year}" if with_year else text


# ---------------------------------------------------------------------------
# Cached data access.
#
# Only coordinates and forecast_days reach the cache key, so sidebar changes
# (including the language switch) reuse the stored API response and re-run only
# the cheap local filtering.
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_wind(latitude, longitude, forecast_days=wf.FORECAST_DAYS):
    """Fetch the hourly wind forecast (ICON seamless). Cached for an hour."""
    return wf.fetch_wind(latitude, longitude, forecast_days)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_tide(latitude, longitude, forecast_days=wf.FORECAST_DAYS):
    """Fetch the hourly sea level. Cached for an hour."""
    return wf.fetch_tide(latitude, longitude, forecast_days)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_sun_times(latitude, longitude, forecast_days=DEFAULT_FORECAST_DAYS):
    """Fetch daily sunrise/sunset (local time) for one coordinate.

    Kept in the app rather than wind_forecast.py because it is presentation
    data (it only drives the time slider), not part of the rideability rules.
    Returns a list of (date, sunrise 'HH:MM', sunset 'HH:MM').
    """
    payload = wf._get_json(wf.WIND_API_URL, {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "sunrise,sunset",
        "timezone": wf.TIMEZONE,
        "forecast_days": forecast_days,
    })
    daily = payload.get("daily", {})
    return list(zip(daily.get("time", []),
                    [s[11:16] for s in daily.get("sunrise", [])],
                    [s[11:16] for s in daily.get("sunset", [])]))


def region_centre(active):
    """Mean coordinate of the active spots, or the East Frisia fallback."""
    if not active:
        return REGION_LAT, REGION_LON
    lats = [wf.SPOTS[s]["latitude"] for s in active]
    lons = [wf.SPOTS[s]["longitude"] for s in active]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def daylight_bounds(sun_time):
    """Whole daylight hours as an exclusive slider range.

    Sunrise is floored and sunset is ceiled, so the range always covers the full
    daylight period (07:06-19:40 -> 07:00-20:00). Returns None without sun data.
    """
    if not sun_time or len(sun_time) != 3:
        return None
    _, sunrise, sunset = sun_time
    start = int(sunrise[:2])
    end = min(int(sunset[:2]) + (1 if int(sunset[3:]) else 0), 24)
    return start, end


def get_hours(spot_name, config, forecast_days=DEFAULT_FORECAST_DAYS):
    """Return the merged, tagged hours for one spot using the sidebar config."""
    coords = wf.SPOTS[spot_name]
    wind = load_wind(coords["latitude"], coords["longitude"], forecast_days)
    tide = load_tide(coords["latitude"], coords["longitude"], forecast_days)
    return wf.build_hours(wind, tide, coords["allowed"], config)


# ---------------------------------------------------------------------------
# Reason tallying.
# ---------------------------------------------------------------------------

def tally_best_reason(day):
    """Count, per hour, the single highest-priority reason that blocked it.

    Picking one reason per hour keeps the counts summing to the number of
    checked hours; an hour that fails several filters is attributed to the most
    informative one (offshore wind before a dry mudflat, and so on).
    Returns (reason_key, hours, checked_hours) or (None, 0, n).
    """
    counts = {}
    for hour in day:
        for reason in REASON_PRIORITY:
            if reason in hour["reasons"]:
                counts[reason] = counts.get(reason, 0) + 1
                break
    if not counts:
        return None, 0, len(day)
    reason = max(counts, key=lambda r: (counts[r], -REASON_PRIORITY.index(r)))
    return reason, counts[reason], len(day)


def tally_reasons(day, limit=2):
    """Top `limit` blocking reasons for a day, with hour counts, plus total."""
    counts = {}
    for hour in day:
        for reason in REASON_PRIORITY:
            if reason in hour["reasons"]:
                counts[reason] = counts.get(reason, 0) + 1
                break
    ordered = sorted(counts.items(),
                     key=lambda item: (-item[1], REASON_PRIORITY.index(item[0])))
    return ordered[:limit], len(day)


# ---------------------------------------------------------------------------
# Presentation helpers.
# ---------------------------------------------------------------------------

def window_text(kept):
    """Time window, or 'a / b' when the rideable hours are not contiguous."""
    times = [h["time"][11:16] for h in kept]
    hours = [h["hour"] for h in kept]
    if all(b - a == 1 for a, b in zip(hours, hours[1:])):
        return f"{times[0]} - {kept[-1]['hour'] + 1:02d}:00"
    return f"{times[0]} / {times[-1]}"


def tile(lang, day, kept):
    """Render one day tile: green when rideable, red with a reason breakdown."""
    date_label = format_day(lang, day[0]["date"])

    if kept:
        speeds = [h["speed"] for h in kept]
        peak = max(kept, key=lambda h: h["gust"])
        head = "green"
        body = [
            f"<b>{t(lang, 'hours_rideable', n=len(kept))}</b>",
            window_text(kept),
            t(lang, "wind_range", min=f"{min(speeds):.0f}",
              max=f"{max(speeds):.0f}"),
            t(lang, "gusts_to", x=f"{peak['gust']:.0f}"),
            f"{wf.compass_point(peak['direction'])} ({peak['direction']:.0f}&deg;)",
        ]
    else:
        reasons, checked = tally_reasons(day)
        head = "red"
        body = [f"<b>{t(lang, 'no_window_badge')}</b>"]
        if reasons:
            for reason, count in reasons:
                body.append(f"\u2022 {reason_text(lang, reason)} "
                            f"({count} {'Std.' if lang == 'Deutsch' else 'h'})")
        else:
            body.append(t(lang, "reasons")["no tide data"])
        body.append(t(lang, "of_hours", n=checked, total=checked))

    fg, bg, border = TILE_COLORS[head]
    lines = "".join(
        f'<div style="font-size:0.78rem;line-height:1.45;">{part}</div>'
        for part in body)
    return (f'<div style="border:1px solid {border};background:{bg};color:{fg};'
            f'border-radius:0.5rem;padding:0.5rem 0.6rem;min-height:8.5rem;">'
            f'<div style="font-weight:600;font-size:0.82rem;margin-bottom:0.25rem;">'
            f'{date_label}</div>{lines}</div>')


def hourly_frame(lang, day):
    """Build the per-hour table for one spot, rideable rows flagged."""
    rows = []
    for h in day:
        time = pd.Timestamp(h["time"])
        if h["direction"] is None:
            direction = "--"
        else:
            direction = f"{wf.compass_point(h['direction'])} {h['direction']:.0f}\u00b0"
        rows.append({
            "Date": format_day(lang, h["date"]),
            "Time": time.strftime("%H:%M"),
            "Wind (kn)": h["speed"],
            "Gusts (kn)": h["gust"],
            "Gust Delta (kn)": h["delta"],
            "Direction": direction,
            "Water Level (m)": h["level"],
            "Tide": tide_text(lang, h["state"]),
            "Rideable": not h["reasons"],
            "Blocked by": ", ".join(
                reason_text(lang, r) for r in h["reasons"]) or "\u2014",
        })
    return pd.DataFrame(rows)


def style_hourly(frame):
    """Subtle green wash for rideable rows; keeps other rows plain."""

    def row_style(row):
        if row["Rideable"]:
            return ["background-color: rgba(25, 135, 84, 0.14)"] * len(row)
        return [""] * len(row)

    return frame.style.apply(row_style, axis=1).format({
        "Wind (kn)": "{:.1f}",
        "Gusts (kn)": "{:.1f}",
        "Gust Delta (kn)": "{:+.1f}",
        "Water Level (m)": "{:+.2f}",
    })


def render_spot(lang, spot_name, config, show_details, forecast_days):
    """Render one spot card: header, KPI row, day tiles, optional hourly table."""
    hours = get_hours(spot_name, config, forecast_days)
    coords = wf.SPOTS[spot_name]
    rideable = [h for h in hours if not h["reasons"]]
    start, end = coords["allowed"]
    days = list(dict.fromkeys(h["date"] for h in hours))

    with st.container(border=True):
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        with left:
            st.subheader(spot_name)
            st.caption(
                f"{coords['latitude']:.4f}, {coords['longitude']:.4f} \u00b7 "
                + t(lang, "caption_onshore", start=start, end=end,
                    sc=wf.compass_point(start), ec=wf.compass_point(end))
                + " \u00b7 " + t(lang, "caption_model", model=wf.MODEL))
            # Direct navigation link, kept subtle so it sits beside the title.
            st.link_button(
                t(lang, "open_in_maps"),
                maps_url(coords["latitude"], coords["longitude"]),
                key=f"maps_{spot_name}")
        with right:
            if rideable:
                st.success(t(lang, "rideable_hours", n=len(rideable)), icon="\u2705")
            else:
                st.error(t(lang, "no_rideable_hours"), icon="\u26d4")

        if not rideable:
            reason, count, _ = tally_best_reason(hours)
            if reason:
                st.caption(t(lang, "week_blocker",
                             reason=reason_text(lang, reason), n=count))

        st.caption(config.summary())

        # Day tiles laid out in rows of four.
        for start_index in range(0, len(days), 4):
            columns = st.columns(4)
            for column, date in zip(columns, days[start_index:start_index + 4]):
                day = [h for h in hours if h["date"] == date]
                kept = [h for h in day if not h["reasons"]]
                with column:
                    st.markdown(tile(lang, day, kept), unsafe_allow_html=True)

        # Collapsed by default so the map never clutters the dashboard.
        with st.expander(t(lang, "map_expander")):
            spot_df = pd.DataFrame([{"lat": coords["latitude"],
                                     "lon": coords["longitude"]}])
            st.map(spot_df, zoom=12, width="stretch")
            st.caption(t(lang, "map_caption",
                         lat=f"{coords['latitude']:.4f}",
                         lon=f"{coords['longitude']:.4f}"))

        if show_details:
            with st.expander(t(lang, "expander")):
                frame = hourly_frame(lang, hours)
                labels = TRANSLATIONS[lang]["cols"]
                st.dataframe(
                    style_hourly(frame),
                    width="stretch",
                    hide_index=True,
                    # Column keys stay English (styling/formatting rely on them);
                    # only the displayed headers are localised.
                    column_config={
                        key: st.column_config.Column(labels.get(key, key))
                        for key in frame.columns
                        if key != "Rideable"
                    } | {
                        "Rideable": st.column_config.CheckboxColumn(
                            labels["Rideable"], disabled=True),
                    },
                )
                st.caption(t(lang, "legend", rideable=len(rideable),
                               total=len(hours)))

    return len(rideable), len(hours)


# ---------------------------------------------------------------------------
# Sidebar and page.
# ---------------------------------------------------------------------------

def maps_url(latitude, longitude):
    """Google Maps search URL for a coordinate pair."""
    return f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"


def _apply_daylight(sun_time):
    """Checkbox callback: clamp the time window to whole daylight hours.

    The window widget is created after this checkbox, so writing its session
    state here lands before the slider is built and takes effect immediately.
    Unchecking leaves the window alone rather than guessing a previous value.
    """
    if not st.session_state.get("daylight_only"):
        return
    bounds = daylight_bounds(sun_time)
    if bounds:
        st.session_state["window"] = bounds


# ---------------------------------------------------------------------------
# User profiles.
#
# users.json is the shared source of truth: the Streamlit app writes it and the
# background alert service reads it each cycle. Session state is the runtime
# copy, so switching users writes the profile's settings into the widget keys.
# ---------------------------------------------------------------------------

# Session-state key for each persisted setting, in sidebar order.
SETTING_KEYS = {
    "base_wind": "wind_range",
    "max_gust_spread": "max_spread",
    "max_total_gust_kn": "max_total_gust",
    "min_water_level": "min_level",
    "daily_time_window": "window",
    "active_spots": "active_spots",
}


def apply_profile(profile):
    """Push a profile's settings into the widget session state.

    Called before the sidebar builds its widgets, so the sliders and the spot
    selection show that user's values on this very run.
    """
    settings = profiles.normalise_settings(profile.get("settings"),
                                           list(wf.SPOTS))
    for setting, key in SETTING_KEYS.items():
        st.session_state[key] = settings[setting]
    # Keep the daylight clamp consistent with the profile's own window rather
    # than silently overriding the values that were just loaded.
    if st.session_state.get("daylight_only"):
        sun = current_sun_time()
        bounds = daylight_bounds(sun) if sun else None
        if bounds:
            st.session_state["window"] = bounds


def current_settings():
    """Read the live sidebar values as a settings dict ready for the file."""
    defaults = profiles.DEFAULT_SETTINGS
    return {
        "base_wind": list(st.session_state.get("wind_range",
                                                defaults["base_wind"])),
        "max_gust_spread": st.session_state.get("max_spread",
                                                defaults["max_gust_spread"]),
        "max_total_gust_kn": st.session_state.get("max_total_gust",
                                                  defaults["max_total_gust_kn"]),
        "min_water_level": st.session_state.get("min_level",
                                                defaults["min_water_level"]),
        "daily_time_window": list(st.session_state.get("window",
                                                       defaults["daily_time_window"])),
        "active_spots": list(st.session_state.get("active_spots",
                                                  defaults["active_spots"])),
    }


def current_sun_time():
    """Sunrise/sunset for the currently selected spots (used by the clamp)."""
    active = st.session_state.get("active_spots") or list(wf.SPOTS)
    days = st.session_state.get("forecast_days", DEFAULT_FORECAST_DAYS)
    try:
        sun_times = load_sun_times(*region_centre(active), days)
    except Exception:
        return None
    return sun_times[0] if sun_times else None


def save_alert_times(name, raw_times):
    """Update one profile's check_times.

    Returns (times, changed). Invalid input is rejected without touching the
    stored value, so a typo cannot silently delete a user's alerts.
    """
    times = profiles.normalise_check_times(raw_times)
    if not times:
        return [], False

    users = profiles.load_users()
    profile = profiles.normalise_profile(users.get(name), list(wf.SPOTS))
    profile["check_times"] = times
    users[name] = profile
    profiles.save_users(users)
    return times, True


def save_current_settings(name):
    """Persist the live sidebar values into `name`'s profile."""
    users = profiles.load_users()
    profile = profiles.normalise_profile(users.get(name), list(wf.SPOTS))
    profile["settings"] = current_settings()
    users[name] = profile
    profiles.save_users(users)
    return profile


def inject_header_css():
    """Pin the header row to one vertical baseline and style the empty state.

    Streamlit stacks every element with its own bottom margin, so a selectbox
    (which reserves extra height for its dropdown) and a button in neighbouring
    columns end up visibly offset. A dedicated label row plus zeroed margins on
    the controls in that row puts them on the same line.
    """
    st.markdown("""
        <style>
        /* Label row: small, muted, flush with the controls below. */
        .wf-head-label {
            font-size: 0.80rem;
            font-weight: 500;
            color: #6b7280;
            margin: 0 0 0.15rem 0;
            padding: 0;
            line-height: 1.2;
        }
        /* Zero the vertical gutters of the header controls so nothing is
           nudged up or down relative to its neighbours. */
        div[data-testid="stVerticalBlock"] > div:has(.wf-head-label),
        div[data-testid="stVerticalBlock"] > div:has(.wf-empty-profile) {
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"] > div:has(.wf-head-label)
            + div[data-testid="stHorizontalBlock"] {
            margin-top: 0 !important;
        }
        /* Buttons and selects inside the header share the same height. */
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button,
        div[data-testid="stHorizontalBlock"] div[data-testid="stPopover"] > button {
            min-height: 2.5rem;
            margin: 0 !important;
        }
        div[data-testid="stHorizontalBlock"] div[data-baseweb="select"] > div {
            min-height: 2.5rem;
            margin: 0 !important;
        }
        .wf-empty-profile {
            font-size: 0.85rem;
            line-height: 1.35;
            color: #92400e;
            background: #fef3c7;
            border: 1px solid #fcd34d;
            border-radius: 0.5rem;
            padding: 0.4rem 0.6rem;
            min-height: 2.5rem;
            display: flex;
            align-items: center;
        }
        </style>
    """, unsafe_allow_html=True)


def profile_bar(lang):
    """Top-right user selector, '+ New User' popover and save button.

    Rendered before the sidebar so a user switch can populate the widget keys
    before those widgets are created.
    """
    inject_header_css()

    if not profiles.ensure_users_file():
        st.warning(t(lang, "users_file_unwritable"), icon="\u26a0\ufe0f")

    users = profiles.load_users()

    # Guarantee an active user: session value, else the first profile.
    if st.session_state.get("active_user") not in users:
        if users:
            first = next(iter(users))
            st.session_state["active_user"] = first
            st.session_state["user_selector"] = first
            apply_profile(users[first])
        else:
            st.session_state["active_user"] = None

    # A label row above the controls keeps every column on one baseline: each
    # control sits in its own row, so different widget heights cannot offset it.
    _, label_selector, label_save, label_alerts, label_new = st.columns(
        [2.2, 2.1, 2.2, 1.0, 1.5])
    with label_selector:
        st.markdown(f'<div class="wf-head-label">{t(lang, "profile_label")}</div>',
                    unsafe_allow_html=True)
    with label_save:
        st.markdown('<div class="wf-head-label">&nbsp;</div>',
                    unsafe_allow_html=True)
    with label_alerts:
        st.markdown('<div class="wf-head-label">&nbsp;</div>',
                    unsafe_allow_html=True)

    spacer, selector_col, save_col, times_col, new_col = st.columns(
        [2.2, 2.1, 2.2, 1.0, 1.5])

    # IMPORTANT ordering: the create form runs BEFORE the selector. Streamlit
    # forbids writing a widget's key once that widget is instantiated, and
    # creating a user must be able to set the selector to the new profile.
    with new_col:
        _new_user_popover(lang)

    # Re-read: the form above may have just written a new profile to disk.
    users = profiles.load_users()
    names = list(users)
    if st.session_state.get("active_user") not in names and names:
        st.session_state["user_selector"] = names[0]
        st.session_state["active_user"] = names[0]
        apply_profile(users[names[0]])

    with selector_col:
        if names:
            selected = st.selectbox(
                t(lang, "profile_label"), names,
                index=names.index(st.session_state["active_user"])
                if st.session_state.get("active_user") in names else 0,
                key="user_selector",
                label_visibility="collapsed")
            if selected != st.session_state.get("active_user"):
                # Switching users writes the new profile's values into the
                # sidebar widget keys, ready for the next run.
                apply_profile(users[selected])
                st.session_state["active_user"] = selected
                st.rerun()
        else:
            selected = None
            st.markdown(
                f'<div class="wf-empty-profile">{t(lang, "no_profiles")}</div>',
                unsafe_allow_html=True)

    with save_col:
        # No profile yet means nothing to save, so the action is offered
        # disabled rather than hidden: the layout stays stable and it is clear
        # where settings will be saved once a profile exists.
        if st.button(t(lang, "save_settings", name=selected) if selected
                     else t(lang, "save_settings_generic"),
                     width="stretch", key="save_settings",
                     disabled=not selected):
            save_current_settings(selected)
            st.toast(t(lang, "saved_toast", name=selected), icon="\U0001f4be")

    with times_col:
        if selected:
            _alert_times_popover(lang, selected, users[selected])
        else:
            st.button(t(lang, "alert_times_popover"), width="stretch",
                      key="alerts_disabled", disabled=True)

    return selected


def save_alert_settings(name, raw_times, alert_days):
    """Persist a profile's notification times and day scope together.

    Returns (times, changed). Invalid times are rejected without touching the
    stored value, so a typo cannot silently delete a user's alerts.
    """
    times = profiles.normalise_check_times(raw_times)
    if not times:
        return [], False

    users = profiles.load_users()
    profile = profiles.normalise_profile(users.get(name), list(wf.SPOTS))
    profile["check_times"] = times
    profile["alert_days"] = profiles.normalise_alert_days(alert_days)
    users[name] = profile
    profiles.save_users(users)
    return times, True


def _alert_times_popover(lang, name, profile):
    """Edit an existing profile's alert days and notification times.

    Both fields are written to the file only on submit, so typing does not churn
    users.json on every keystroke.
    """
    day_options = profiles.ALERT_DAYS
    stored_days = profiles.normalise_alert_days(profile.get("alert_days"))
    key = f"days_input_{name}"
    # Seed the radio from the profile once per user; afterwards the widget owns
    # the value so switching profiles does not clobber an unsaved choice.
    if key not in st.session_state:
        st.session_state[key] = stored_days

    with st.popover(t(lang, "alert_times_popover"), width="stretch"):
        labels = TRANSLATIONS[lang]["alert_days"]
        alert_days = st.radio(
            t(lang, "alert_days_label"),
            options=day_options,
            format_func=lambda key_: labels[key_],
            key=key)

        raw = st.text_input(
            t(lang, "alert_times_help"),
            value=", ".join(profile.get("check_times", [])),
            key=f"times_input_{name}")

        if st.button(t(lang, "alert_times_save"), width="stretch",
                     key=f"times_save_{name}"):
            times, changed = save_alert_settings(name, raw, alert_days)
            if changed:
                st.toast(t(lang, "alert_times_saved", name=name,
                             days=labels[alert_days], times=", ".join(times)),
                         icon="\u23f0")
            else:
                st.warning(t(lang, "alert_times_invalid"), icon="\u26a0\ufe0f")


def _new_user_popover(lang):
    """Popover with the form that creates a new profile.

    On success it writes the profile, points the selector at it and triggers a
    rerun; the rerun raises a control-flow exception, so nothing below runs.
    """
    with st.popover(t(lang, "new_user"), width="stretch"):
        with st.form("new_user_form", clear_on_submit=False):
            name = st.text_input(t(lang, "new_user_name"))
            email = st.text_input(t(lang, "new_user_email"))
            times = st.text_input(t(lang, "new_user_times"),
                                  placeholder="07:30, 18:30")
            copy_current = st.checkbox(t(lang, "new_user_from_current"),
                                       value=True)
            submitted = st.form_submit_button(t(lang, "new_user_create"),
                                              width="stretch")

        if not submitted:
            return

        clean = name.strip()
        users = profiles.load_users()
        if not clean:
            st.warning(t(lang, "new_user_needs_name"), icon="\u26a0\ufe0f")
        elif clean in users:
            st.warning(t(lang, "new_user_exists", name=clean), icon="\u26a0\ufe0f")
        else:
            users[clean] = profiles.new_profile(
                email=email, check_times=times,
                settings=current_settings() if copy_current else None,
                valid_spots=list(wf.SPOTS))
            profiles.save_users(users)
            # Point the selector at the new profile before it is instantiated.
            st.session_state["user_selector"] = clean
            st.session_state["active_user"] = clean
            apply_profile(users[clean])
            st.session_state["_flash"] = t(lang, "new_user_created", name=clean)
            st.rerun()


def sidebar():
    """Build the reactive controls and return (lang, config, spots, details).

    Every widget gets an explicit, language-independent `key`. Without one,
    Streamlit identifies a widget by its label, so translating the label would
    look like a new widget and silently reset its value on language switch.
    """
    if "lang" not in st.session_state:
        st.session_state["lang"] = LANGUAGES[0]
    if "show_details" not in st.session_state:
        st.session_state["show_details"] = wf.SHOW_DETAILS
    if "daylight_only" not in st.session_state:
        st.session_state["daylight_only"] = False

    # NOTE: "window" is deliberately not pre-set. Seeding a widget's key makes
    # Streamlit warn that the value came from session state as well as a default.
    # The slider's own default applies until the daylight callback writes a clamp.

    # Language is chosen first so the very first run already renders in it.
    lang = st.sidebar.selectbox(
        TRANSLATIONS[LANGUAGES[0]]["language_label"], LANGUAGES, index=0,
        key="lang")

    st.sidebar.title("\U0001f3c4 " + t(lang, "app_title"))
    st.sidebar.caption(t(lang, "subtitle"))

    st.sidebar.subheader(t(lang, "sec_wind"))
    wind_range = st.sidebar.slider(
        t(lang, "slider_wind"), 0.0, 45.0, (wf.MIN_WIND_KN, wf.MAX_WIND_KN), 1.0,
        key="wind_range")
    min_wind, max_wind = wind_range

    st.sidebar.subheader(t(lang, "sec_gusts"))
    max_spread = st.sidebar.slider(
        t(lang, "slider_gust"), 0.0, 40.0, wf.MAX_GUST_SPREAD_KN, 1.0,
        help=t(lang, "slider_gust_help"), key="max_spread")

    max_total_gust = st.sidebar.slider(
        t(lang, "slider_gust_ceiling"), 15.0, 50.0, wf.MAX_TOTAL_GUST_KN, 1.0,
        help=t(lang, "slider_gust_ceiling_help"), key="max_total_gust")

    st.sidebar.subheader(t(lang, "sec_water"))
    min_level = st.sidebar.slider(
        t(lang, "slider_water"), -2.0, 2.0, wf.MIN_WATER_LEVEL, 0.05,
        format="%.2f", key="min_level")

    st.sidebar.subheader(t(lang, "sec_spots"))
    active = st.sidebar.multiselect(
        t(lang, "multiselect_spots"), list(wf.SPOTS), default=list(wf.SPOTS),
        key="active_spots")

    st.sidebar.subheader(t(lang, "sec_availability"))
    forecast_days = st.sidebar.radio(
        t(lang, "forecast_range"), FORECAST_DAY_OPTIONS, index=len(FORECAST_DAY_OPTIONS) - 1,
        horizontal=True, key="forecast_days")

    start_hour, end_hour = st.sidebar.slider(
        t(lang, "slider_window"), 0, 24, (wf.START_HOUR, wf.END_HOUR), 1,
        help=t(lang, "slider_window_help"), key="window")

    # Sunrise/sunset for the active spots, shown directly under the slider.
    sun_times = load_sun_times(*region_centre(active), forecast_days)
    sun_time = sun_times[0] if sun_times else None
    if sun_time:
        st.sidebar.caption(t(lang, "sun_line", sunrise=sun_time[1],
                             sunset=sun_time[2]))

    st.sidebar.checkbox(
        t(lang, "daylight_only"), key="daylight_only",
        help=t(lang, "daylight_only_help"),
        on_change=_apply_daylight, args=(sun_time,))

    st.sidebar.subheader(t(lang, "sec_view"))
    show_details = st.sidebar.toggle(
        t(lang, "toggle_details"), key="show_details")

    if st.sidebar.button(t(lang, "btn_clear"), width="stretch", key="clear"):
        st.cache_data.clear()
        st.rerun()

    config = wf.Config(
        min_wind_kn=min_wind,
        max_wind_kn=max_wind,
        max_gust_spread_kn=max_spread,
        max_total_gust_kn=max_total_gust,
        start_hour=start_hour,
        end_hour=end_hour,
        min_water_level=min_level,
    )
    return lang, config, active, show_details, forecast_days


def main():
    st.set_page_config(page_title="Wind & Tide", page_icon="\U0001f3c4",
                       layout="wide")

    # Language is only known after the sidebar builds the selector, so read the
    # stored value here and fall back to the default on the very first run.
    lang = st.session_state.get("lang", LANGUAGES[0])
    profile_bar(lang)

    lang, config, active, show_details, forecast_days = sidebar()

    flash = st.session_state.pop("_flash", None)
    if flash:
        st.success(flash, icon="\u2705")

    st.title(t(lang, "page_title"))
    total_rideable = total_hours = 0

    if not active:
        st.info(t(lang, "no_spots"))
        return

    for spot_name in active:
        try:
            kept, all_hours = render_spot(lang, spot_name, config, show_details,
                                          forecast_days)
        except Exception as error:  # network/API failure for one spot
            st.error(t(lang, "load_error", spot=spot_name, error=error))
            continue
        total_rideable += kept
        total_hours += all_hours

    st.caption(t(lang, "footer", spots=len(active), rideable=total_rideable,
                 total=total_hours, ttl=CACHE_TTL // 60))


if __name__ == "__main__":
    main()
