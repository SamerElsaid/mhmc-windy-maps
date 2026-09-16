#!/usr/bin/env python3
"""Render the official Windy screenshot pages to PNG.

This script is intended for GitHub Actions (or another machine with Chromium).
It is deliberately NOT run on Bluehost Shared Hosting.
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

LAT = float(os.getenv("WINDY_MAP_LAT", "29.8"))
LON = float(os.getenv("WINDY_MAP_LON", "31.0"))
ZOOM = int(os.getenv("WINDY_MAP_ZOOM", "5"))
WIDTH = int(os.getenv("WINDY_MAP_WIDTH", "1400"))
HEIGHT = int(os.getenv("WINDY_MAP_HEIGHT", "760"))
WAIT_MS = int(os.getenv("WINDY_MAP_WAIT_MS", "15000"))
OUT = Path(os.getenv("WINDY_OUTPUT_DIR", "weather-maps"))
MIN_BYTES = int(os.getenv("WINDY_MIN_IMAGE_BYTES", "10000"))

LAYERS = {
    "wind": "wind",
    "clouds": "clouds",
    "pressure": "pressure",
    "temperature": "temp",
    "rain": "rain",
}


def windy_url(layer):
    return "https://www.windy.com/screenshot?%s,%s,%s,i:%s" % (
        LAT, LON, ZOOM, LAYERS[layer]
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-dev-shm-usage"])
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
        )
        for layer in LAYERS:
            target = OUT / ("windy_%s.png" % layer)
            target_tmp = OUT / (".%s.tmp.png" % layer)
            url = windy_url(layer)
            print("Rendering %s: %s" % (layer, url))
            page.goto(url, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(WAIT_MS)
            page.screenshot(path=str(target_tmp), full_page=False)
            if target_tmp.stat().st_size < MIN_BYTES:
                raise RuntimeError("Suspiciously small screenshot: %s" % target_tmp)
            target_tmp.replace(target)
        browser.close()

    # Machine-readable freshness marker consumed by reports/windy_maps.py.
    (OUT / "generated_at_utc.txt").write_text(
        generated.isoformat().replace("+00:00", "Z") + "\n", encoding="utf-8"
    )
    (OUT / "latest.txt").write_text(
        generated.strftime("%Y%m%d_%H%M%S_UTC") + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
