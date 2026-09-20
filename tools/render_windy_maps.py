#!/usr/bin/env python3
"""Render Windy.com weather-map layers to PNG using the embed widget.

This script is intended for GitHub Actions (or another machine with Chromium).
It is deliberately NOT run on Bluehost Shared Hosting.

NOTE (2026-09): the previously-documented "https://www.windy.com/screenshot"
chrome-free mode no longer behaves as documented - in testing it rendered the
full interactive site (search box, ads, sidebar menu, bottom timeline) and
did not honor the requested overlay layer at all (every layer came out as
the default Wind view). Switched to Windy's official embeddable widget
(embed.windy.com/embed2.html), which is purpose-built to be minimal chrome
and is the same widget used on countless third-party weather sites, with an
explicit `overlay` parameter that reliably switches layers.
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

LAT = float(os.getenv("WINDY_MAP_LAT", "30.118"))
LON = float(os.getenv("WINDY_MAP_LON", "31.572"))
ZOOM = int(os.getenv("WINDY_MAP_ZOOM", "6"))
WIDTH = int(os.getenv("WINDY_MAP_WIDTH", "1400"))
HEIGHT = int(os.getenv("WINDY_MAP_HEIGHT", "760"))
WAIT_MS = int(os.getenv("WINDY_MAP_WAIT_MS", "15000"))
OUT = Path(os.getenv("WINDY_OUTPUT_DIR", "weather-maps"))
MIN_BYTES = int(os.getenv("WINDY_MIN_IMAGE_BYTES", "10000"))

# Overlay codes confirmed directly from the user's own working windy.com
# URLs (e.g. https://www.windy.com/-Temperature-temp?temp,30.118,31.572,6) -
# these are live, verified codes, not guessed.
LAYERS = {
    "wind": "wind",
    "radar": "radar",
    "rain": "rain",
    "temperature": "temp",
    "clouds": "clouds",
    "waves": "waves",
    "rainaccu": "rainAccu",
    "thunder": "thunder",
}

# Elements the embed widget can still show that we don't want in a PDF
# report image (its own small logo/attribution is deliberately NOT in this
# list - Windy's usage terms require "source: windy.com" to stay visible,
# and the report caption also credits it in text). Hidden defensively with
# try/except per-selector so a missing element on any given layer never
# fails the whole render.
_HIDE_SELECTORS = [
    "#embed-left",      # left search/location panel, if present
    "#mobile-search",
    ".leaflet-control-zoom",
    ".leaflet-control-layers",
    "#social",
]


def windy_url(layer):
    overlay = LAYERS[layer]
    return (
        "https://embed.windy.com/embed2.html"
        f"?lat={LAT}&lon={LON}&detailLat={LAT}&detailLon={LON}"
        f"&width={WIDTH}&height={HEIGHT}&zoom={ZOOM}"
        f"&level=surface&overlay={overlay}&product=ecmwf"
        "&menu=&message=false&marker=&calendar=now&pressure="
        "&type=map&location=coordinates&detail=&metricWind=default"
        "&metricTemp=default&radarRange=-1"
    )


def _hide_extra_chrome(page):
    for selector in _HIDE_SELECTORS:
        try:
            page.evaluate(
                "(sel) => document.querySelectorAll(sel).forEach(el => el.style.display = 'none')",
                selector,
            )
        except Exception:
            pass  # best-effort - a missing/renamed element must never fail the render


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
            page.goto(url, wait_until="load", timeout=60000)
            page.wait_for_timeout(WAIT_MS)
            _hide_extra_chrome(page)
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
