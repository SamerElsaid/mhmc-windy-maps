#!/usr/bin/env python3
"""
fetch_ngl_velocities.py
--------------------------
Runs on GitHub Actions (see .github/workflows/windy-maps.yml), NOT on
Bluehost - this follows the exact same pattern already used for the Windy
weather maps: fetch/process something too heavy for shared hosting here,
publish a small ready-to-use file to the repo's 'maps' branch, and have
geophysics.php read that small file as a static asset.

Source: Nevada Geodetic Laboratory (NGL) MIDAS velocity solution -
https://geodesy.unr.edu/velocities/midas.IGS14.txt - a single plain-text
file covering >20,000 GNSS stations worldwide, updated weekly, no
registration or agreement required (open data). Column layout is
documented at https://geodesy.unr.edu/velocities/midas.readme.txt

This script keeps only stations within our region of interest and writes
a small JSON with just the fields the map needs (station code, position,
horizontal velocity). Full precision/metadata from NGL is not needed for
a map arrow, so the output is intentionally minimal.
"""

import json
import os
import sys
import urllib.request

NGL_URL = "https://geodesy.unr.edu/velocities/midas.IGS14.txt"

# Eastern Mediterranean / Red Sea region - matches and slightly exceeds the
# "East Med" map view already used elsewhere on the Geophysics page.
REGION_MIN_LAT = float(os.getenv("GNSS_MIN_LAT", "20"))
REGION_MAX_LAT = float(os.getenv("GNSS_MAX_LAT", "43"))
REGION_MIN_LON = float(os.getenv("GNSS_MIN_LON", "10"))
REGION_MAX_LON = float(os.getenv("GNSS_MAX_LON", "45"))

OUT_PATH = os.getenv("GNSS_OUT_PATH", "gnss/velocities.json")


def parse_midas_line(line):
    """Returns a dict for one station, or None if the line can't be parsed
    or the velocity looks unreasonable (a MIDAS fit gone wrong on a short
    or noisy series - NGL's own README notes these do occur)."""
    if not line.strip() or line.startswith("#"):
        return None
    parts = line.split()
    if len(parts) < 27:
        return None
    try:
        station = parts[0]
        ve_mm = float(parts[8]) * 1000.0   # column 9: east velocity, m/yr -> mm/yr
        vn_mm = float(parts[9]) * 1000.0   # column 10: north velocity, m/yr -> mm/yr
        ve_unc_mm = float(parts[11]) * 1000.0
        vn_unc_mm = float(parts[12]) * 1000.0
        lat = float(parts[24])             # column 25
        lon = float(parts[25])             # column 26
    except (ValueError, IndexError):
        return None

    # NGL writes longitudes in several conventions: -180..180, 0..360, and
    # -360..0 (e.g. Alexandria ALX2 is "-330.089", i.e. 29.911 E). Normalize
    # all of them to -180..180 before the bounding-box check.
    lon = ((lon + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    if not (-90.0 <= lat <= 90.0):
        return None

    # A MIDAS fit occasionally diverges on a short/gappy series and reports
    # an implausible plate velocity (tens of cm/yr) - drop those rather than
    # plot a wildly wrong arrow. Real tectonic rates here are a few cm/yr at most.
    if abs(ve_mm) > 200 or abs(vn_mm) > 200:
        return None

    return {
        "station": station, "lat": round(lat, 5), "lon": round(lon, 5),
        "ve_mm_yr": round(ve_mm, 2), "vn_mm_yr": round(vn_mm, 2),
        "ve_unc_mm_yr": round(ve_unc_mm, 2), "vn_unc_mm_yr": round(vn_unc_mm, 2),
    }


def in_region(rec):
    return (REGION_MIN_LAT <= rec["lat"] <= REGION_MAX_LAT
            and REGION_MIN_LON <= rec["lon"] <= REGION_MAX_LON)


def fetch_and_filter(text):
    stations = []
    skipped = 0
    for line in text.splitlines():
        rec = parse_midas_line(line)
        if rec is None:
            if line.strip() and not line.startswith("#"):
                skipped += 1
            continue
        if in_region(rec):
            stations.append(rec)
    return stations, skipped


def main():
    print("Fetching %s ..." % NGL_URL)
    req = urllib.request.Request(NGL_URL, headers={"User-Agent": "MHMC-EarlyWarning/1.0 (mhmc-eg.com)"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    total_lines = sum(1 for l in text.splitlines() if l.strip() and not l.startswith("#"))
    stations, skipped = fetch_and_filter(text)
    print("Parsed %d station lines, %d unparseable/implausible, %d fall inside the region (%.0f-%.0fN, %.0f-%.0fE)"
          % (total_lines, skipped, len(stations), REGION_MIN_LAT, REGION_MAX_LAT, REGION_MIN_LON, REGION_MAX_LON))

    if len(stations) < 3:
        print("FAILED: fewer than 3 stations found in region - looks wrong, not publishing.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    payload = {
        "source": "Nevada Geodetic Laboratory (NGL), MIDAS velocity solution",
        "source_url": "https://geodesy.unr.edu/velocities/midas.IGS14.txt",
        "reference_frame": "IGS14",
        "units": "mm/yr",
        "region": {"min_lat": REGION_MIN_LAT, "max_lat": REGION_MAX_LAT,
                   "min_lon": REGION_MIN_LON, "max_lon": REGION_MAX_LON},
        "stations": stations,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print("Wrote %s (%d stations, %.0f KB)" % (OUT_PATH, len(stations), os.path.getsize(OUT_PATH) / 1024))


if __name__ == "__main__":
    main()
