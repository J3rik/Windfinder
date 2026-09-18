# Windfinder

Kitesurf forecast dashboard for the East Frisian North Sea coast. It merges an
8-day wind forecast with tide levels and filters the result down to hours that
are actually rideable, then optionally mails you when a window opens up.

Data comes from [Open-Meteo](https://open-meteo.com) (ICON seamless wind + marine
sea level). No API key required.

## Features

- **8-day wind + tide forecast** per spot, evaluated hour by hour.
- **Filtering**: water level, onshore wind sector per spot, wind range, gust
  spread, an absolute gust ceiling, and a personal time window.
- **Green/red day tiles** showing at a glance whether a day has a rideable
  window, plus a colour-coded hourly table.
- **User profiles** stored in `users.json` (per-user filters, spots, and alert
  settings). No profiles are shipped - you create your own.
- **Alert worker** that checks the forecast at your chosen times and e-mails a
  mobile-friendly summary when a window exists.
- **Bilingual UI** (German default, English optional).
- **Interactive map** and Google Maps link per spot.

## Quick start (local)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Mail is optional. Skip this to run the dashboard only.
cp .env.example .env && $EDITOR .env

.venv/bin/streamlit run app.py
```

Open <http://localhost:8501>. Create your first profile via **+ Neuer Nutzer**
(top right) - until then the save button is disabled.

## Deploy with Docker Compose

```bash
# 1. users.json must exist as a FILE before starting, otherwise Docker creates a
#    DIRECTORY with that name and profiles cannot be saved.
touch users.json && echo '{}' > users.json

# 2. Add your mail credentials
$EDITOR docker-compose.yml      # fill in the SMTP_* placeholders

# 3. Start
docker compose up -d
docker compose logs -f
```

The dashboard is then on <http://SERVER:8501>.

To also run the alert worker (sends the scheduled mails):

```bash
docker compose --profile alerts up -d
```

### Updating

```bash
git pull
docker compose up -d --build
```

`users.json` is bind-mounted from the host, so profiles survive rebuilds.

## Alert worker

The worker is a long-running process. It re-reads `users.json` every 30 seconds,
so changes made in the UI apply without a restart.

```bash
.venv/bin/python alert_service.py --list    # profiles, times, mail status
.venv/bin/python alert_service.py --test    # send a test mail now
.venv/bin/python alert_service.py --once    # one scheduled pass, then exit
.venv/bin/python alert_service.py           # run continuously
```

Alert settings are per user (the **⏰ Alerts** button in the header):

| Setting | Meaning |
|---|---|
| `Tage` / `Days` | Look at today, tomorrow, both, or all forecast days |
| Times | Comma-separated `HH:MM` in Europe/Berlin, e.g. `07:30, 18:30` |

A mail is only sent when a rideable window actually exists in the chosen day
scope; otherwise the run is logged and nothing is sent.

### Mail configuration

All credentials come from environment variables - nothing is hardcoded:

| Variable | Default | Notes |
|---|---|---|
| `SMTP_SERVER` | - | e.g. `smtp.example.com` |
| `SMTP_PORT` | `587` | `587` = STARTTLS, `465` = implicit TLS |
| `SMTP_USER` | - | **required**; login user |
| `SMTP_PASSWORD` | - | **required**; app password, not your account password |
| `SMTP_SENDER` | `SMTP_USER` | From address |
| `SMTP_STARTTLS` | `1` | set `0` for implicit TLS on port 465 |
| `SMTP_FALLBACK_PORTS` | `25,465` | tried if the main port is unreachable |

If `SMTP_USER` or `SMTP_PASSWORD` is missing, sending is **skipped with a
descriptive log line** instead of failing: alerts are still written to the log.

Both plain `SMTP_*` and prefixed `WINDFINDER_SMTP_*` names are accepted; real
environment variables take precedence over `.env`.

## Configuration

`wind_forecast.py` holds the defaults; everything user-facing is editable in the
sidebar and saved per profile.

| Setting | Default | Meaning |
|---|---|---|
| `MIN_WIND_KN` / `MAX_WIND_KN` | 9 / 30 | Base wind band |
| `MAX_GUST_SPREAD_KN` | 30 | Allowed gust jump over base wind |
| `MAX_TOTAL_GUST_KN` | 28 | Hard gust ceiling |
| `MIN_WATER_LEVEL` | 0.20 m | Below this the mudflat is too dry |
| `START_HOUR` / `END_HOUR` | 0 / 23 | Availability window (end exclusive) |
| `FORECAST_DAYS` | 8 | Forecast horizon |

`MODEL = "icon_seamless"` uses the 2.2 km ICON-D2 for days 1-2 and blends into
the 7 km ICON-EU for the rest.

> Note: the time window is **half-open** (`START_HOUR <= hour < END_HOUR`), so
> `END_HOUR = 20` means the last rideable hour is 19:00. Use `24` to cover a
> full day.

Spots and their allowed (onshore) wind sectors live in `SPOTS` in
`wind_forecast.py`. A sector may wrap through 0/360.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard |
| `wind_forecast.py` | Data fetching, filtering rules, threshold config |
| `profiles.py` | `users.json` read/write, validation, day scopes |
| `alert_service.py` | Scheduled mail worker |
| `users.json` | Profile data (**not** in git) |
| `.env` | Mail credentials (**not** in git) |
| `.streamlit/config.toml` | Streamlit runtime config |

## Troubleshooting

**Profiles are not saved in Docker.** `users.json` was missing before
`docker compose up`, so Docker created a directory. Fix:

```bash
docker compose down
rm -rf users.json && echo '{}' > users.json
docker compose up -d
```

The app shows a warning banner when it cannot create the file.

**No mails are sent.** Run `.venv/bin/python alert_service.py --list`. It prints
which variables are missing. Remember a mail is only sent when a rideable window
exists in your chosen day scope.

**Login rejected (`535`).** Most providers require an app-specific password
rather than your normal account password.

**Port rejected after repeated attempts.** Some hosts temporarily block an IP
after failed logins. The service falls back to `SMTP_FALLBACK_PORTS`
automatically.
