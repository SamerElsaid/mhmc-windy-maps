# MHMC Windy Weather Maps - Setup

This phase adds five Windy.com weather-map images to the daily MHMC PDF:

- Wind
- Clouds
- Pressure
- Temperature
- Rain

## Architecture

Bluehost Shared Hosting does **not** need Chromium. A GitHub Actions runner opens
Windy's official `/screenshot` pages and publishes the PNGs under `weather-maps/`.
The report server downloads those PNGs over HTTPS.

No OpenWeatherMap or Open-Meteo map tiles are used for these five report maps.
RaspberryShake is not part of this phase.

## Geographic viewport

Default viewport:

- Latitude: 29.8
- Longitude: 31.0
- Zoom: 5
- Image size: 1400 x 760 px

This is intended to cover Egypt, the Mediterranean in front of Egypt, and the Red Sea.
The three values can later be tuned in `.github/workflows/windy-maps.yml` without changing
report code.

## GitHub steps

1. Create a **public** GitHub repository for this project.
2. Upload the project, including `.github/workflows/windy-maps.yml` and `tools/render_windy_maps.py`.
3. Do **not** upload any `.env` file, database password, SMTP password, IOC API key, or other secret.
4. Open **Actions** -> **Render MHMC Windy Weather Maps** -> **Run workflow** for the first test.
5. Confirm that the repository contains:
   `weather-maps/windy_wind.png`, `windy_clouds.png`, `windy_pressure.png`,
   `windy_temperature.png`, `windy_rain.png`, and `generated_at_utc.txt`.
6. In the Bluehost `reports/.env`, set:

   `WINDY_ASSET_BASE_URL=https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/weather-maps`

7. Test the report manually before enabling/depending on the daily schedule.

## Timing

The workflow is scheduled for 05:30 UTC (07:30 Egypt), while the MHMC report cron is
08:05 Egypt. This leaves a buffer for the five screenshots to be rendered and published.

## Freshness protection

`reports/windy_maps.py` reads `generated_at_utc.txt`. If the remote asset set is older
than `WINDY_MAX_ASSET_AGE_HOURS` (default 26 hours), the report refuses to use stale maps.
This prevents yesterday's maps from silently appearing in today's report.

## Attribution

Windy staff state that screen captures may be used in media/projects provided the sentence
`source: windy.com` is present. The MHMC PDF includes this attribution on the Weather Maps page.
