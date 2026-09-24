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

LAT = float(os.getenv("WINDY_MAP_LAT", "30.687"))
LON = float(os.getenv("WINDY_MAP_LON", "30.210"))
ZOOM = float(os.getenv("WINDY_MAP_ZOOM", "6"))
WIDTH = int(os.getenv("WINDY_MAP_WIDTH", "1400"))
HEIGHT = int(os.getenv("WINDY_MAP_HEIGHT", "760"))
WAIT_MS = int(os.getenv("WINDY_MAP_WAIT_MS", "25000"))
OUT = Path(os.getenv("WINDY_OUTPUT_DIR", "weather-maps"))
MIN_BYTES = int(os.getenv("WINDY_MIN_IMAGE_BYTES", "10000"))

# Overlay codes confirmed directly from the user's own working windy.com
# URLs, plus confirmed valid overlay codes from Windy's own documentation
# (docs.windy-plugins.com DataSpecifications) - swell3 and sst are
# explicitly excluded: Windy's own policy documents these as ECMWF-based
# data they're not licensed to provide to third parties.
LAYERS = {
    "wind": "wind",
    "radar": "radar",
    "rain": "rain",
    "temperature": "temp",
    "clouds": "clouds",
    "waves": "waves",
    "rainaccu": "rainAccu",
    "thunder": "thunder",
    "pressure": "pressure",
    "swell1": "swell1",
    "currents": "currents",
    "currentstide": "currentsTide",
    "wwaves": "wwaves",
    "swell2": "swell2",
    # "wavePower" and "sst" were replaced: the free embed does not support
    # them and silently showed the Wind layer instead (verified in the
    # 2026-09-24 report). Both of these are documented Windy overlay values;
    # if the embed ever falls back to Wind for them anyway, the similarity
    # check below drops them instead of publishing a mislabeled map.
    "swellperiod": "swellperiod",
    "gust": "gust",
}

# A layer whose image is this close to the Wind image rendered in the same run
# is treated as "the embed fell back to Wind" and dropped. Measured on real
# renders: fallbacks ~15, genuinely different layers 31-103 (mean abs pixel
# difference, 0-255 scale).
FALLBACK_DIFF_THRESHOLD = float(os.getenv("WINDY_FALLBACK_DIFF_THRESHOLD", "20"))

# Elements the embed widget can still show that we don't want in a PDF
# report image (its own small logo/attribution is deliberately NOT in this
# list - Windy's usage terms require "source: windy.com" to stay visible,
# and the report caption also credits it in text). Hidden defensively with
# try/except per-selector so a missing element on any given layer never
# fails the whole render.
_HIDE_SELECTORS = [
    "#embed-left",      # left search/location panel, if present
    "#mobile-search",
    "#social",
    # Standard Leaflet corner-control containers (Windy's map is Leaflet-
    # based) - catches the zoom +/- buttons, the layer-name picker pill,
    # the playback/timeline bar, and the attribution text seen in testing,
    # without needing Windy's exact (and likely obfuscated) class names.
    # The Windy.com logo is centered at the top, NOT in a corner, so this
    # never removes the required "source: windy.com" attribution.
    ".leaflet-top.leaflet-left",
    ".leaflet-top.leaflet-right",
    ".leaflet-bottom.leaflet-left",
    ".leaflet-bottom.leaflet-right",
    ".leaflet-control-zoom",
    ".leaflet-control-layers",
    ".leaflet-control-attribution",
]


def windy_url(layer):
    overlay = LAYERS[layer]
    return (
        "https://embed.windy.com/embed2.html"
        f"?lat={LAT}&lon={LON}&detailLat={LAT}&detailLon={LON}"
        f"&width={WIDTH}&height={HEIGHT}&zoom={ZOOM}"
        f"&level=surface&overlay={overlay}&product=ecmwf"
        "&menu=&message=false&marker=&calendar=now&pressure=1"
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


def _drop_wind_fallbacks(rendered):
    """Delete layers that are near-identical to Wind rendered in this run."""
    from PIL import Image, ImageChops, ImageStat
    if "wind" not in rendered:
        print("Similarity check skipped: Wind itself did not render.")
        return []
    ref = Image.open(OUT / "windy_wind.png").convert("RGB").resize((350, 190))
    dropped = []
    for layer in rendered:
        if layer == "wind":
            continue
        path = OUT / ("windy_%s.png" % layer)
        img = Image.open(path).convert("RGB").resize((350, 190))
        diff = sum(ImageStat.Stat(ImageChops.difference(ref, img)).mean) / 3
        verdict = "DROPPED (looks like Wind - layer not supported by the embed)" if diff < FALLBACK_DIFF_THRESHOLD else "ok"
        print("  similarity vs wind: %-13s %5.1f  %s" % (layer, diff, verdict))
        if diff < FALLBACK_DIFF_THRESHOLD:
            path.unlink()
            dropped.append(layer)
    return dropped


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Start clean: a layer that fails this run must not be re-published with
    # an old image under today's timestamp.
    for old_png in list(OUT.glob("windy_*.png")) + list(OUT.glob(".*.tmp.png")):
        old_png.unlink()
    generated = datetime.now(timezone.utc)
    rendered = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-dev-shm-usage"])

        failed_layers = []
        for layer in LAYERS:
            target = OUT / ("windy_%s.png" % layer)
            target_tmp = OUT / (".%s.tmp.png" % layer)
            url = windy_url(layer)
            print("Rendering %s: %s" % (layer, url))

            last_error = None
            for attempt in range(2):
                # A fresh, isolated context per layer (no shared cookies,
                # localStorage, or cache) - rules out the widget "remembering"
                # a previous layer's view state and ignoring this URL's
                # lat/lon/zoom/overlay params.
                context = browser.new_context(
                    viewport={"width": WIDTH, "height": HEIGHT},
                    device_scale_factor=1,
                )
                page = context.new_page()
                try:
                    page.goto(url, wait_until="load", timeout=60000)
                    page.wait_for_timeout(WAIT_MS)
                    _hide_extra_chrome(page)
                    page.screenshot(path=str(target_tmp), full_page=False)
                    if target_tmp.stat().st_size < MIN_BYTES:
                        raise RuntimeError("Suspiciously small screenshot: %s" % target_tmp)
                    target_tmp.replace(target)
                    rendered.append(layer)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    print("  attempt %d for %s failed: %s" % (attempt + 1, layer, e))
                    if target_tmp.exists():
                        target_tmp.unlink()
                finally:
                    context.close()
            if last_error is not None:
                # Some layers (swell3, sst) are speculative - a premium
                # paywall, an unsupported overlay code, or a genuine
                # timeout must not take down the other confirmed-working
                # layers. Skip this one and keep going; whatever file
                # existed here from a previous successful run (if any) is
                # left untouched rather than overwritten with a failure.
                print("  SKIPPING '%s' after retries: %s" % (layer, last_error))
                failed_layers.append(layer)
        browser.close()

        if failed_layers:
            print("Layers that failed and were skipped this run: %s" % ", ".join(failed_layers))

    dropped = _drop_wind_fallbacks(rendered)
    print("Published %d of %d layers.%s" % (len(rendered) - len(dropped), len(LAYERS),
          (" Dropped as Wind fallback: " + ", ".join(dropped)) if dropped else ""))

    # Machine-readable freshness marker consumed by reports/windy_maps.py.
    (OUT / "generated_at_utc.txt").write_text(
        generated.isoformat().replace("+00:00", "Z") + "\n", encoding="utf-8"
    )
    (OUT / "latest.txt").write_text(
        generated.strftime("%Y%m%d_%H%M%S_UTC") + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
