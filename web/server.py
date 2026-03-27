"""Web-based test interface for Ledvance Tuya device communication.

Run:
    python web/server.py

Then open http://localhost:8888 in your browser.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aiohttp import web

# Add project root to path so we can import our tuya library
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from custom_components.ha_ledvance_lights.const import (  # noqa: E402
    DP_BRIGHTNESS,
    DP_COLOR_HSV,
    DP_COLOR_TEMP,
    DP_MODE,
    DP_POWER,
    ha_brightness_to_tuya,
    hs_to_tuya_hex,
    kelvin_to_tuya_ct,
    parse_hsv_hex,
    tuya_brightness_to_ha,
    tuya_ct_to_kelvin,
)
from custom_components.ha_ledvance_lights.tuya.device import TuyaDevice  # noqa: E402
from custom_components.ha_ledvance_lights.tuya.scanner import (  # noqa: E402
    detect_version,
    scan_devices,
)

routes = web.RouteTableDef()


def _get_device(data: dict) -> TuyaDevice:
    """Create a TuyaDevice from request data."""
    dev = TuyaDevice(
        dev_id=data["device_id"],
        address=data["ip_address"],
        local_key=data["local_key"],
        version=data.get("version", "3.3"),
    )
    dev.set_socketTimeout(5)
    dev.set_socketRetryLimit(1)
    return dev


@routes.get("/")
async def index(request: web.Request) -> web.Response:
    html_path = Path(__file__).parent / "index.html"
    return web.Response(text=html_path.read_text(), content_type="text/html")


@routes.post("/api/status")
async def api_status(request: web.Request) -> web.Response:
    data = await request.json()
    dev = _get_device(data)
    result = await asyncio.get_running_loop().run_in_executor(None, dev.status)

    # Enrich with human-readable values
    if "dps" in result:
        dps = result["dps"]
        enriched = {}
        if str(DP_POWER) in dps:
            enriched["power"] = "ON" if dps[str(DP_POWER)] else "OFF"
        if str(DP_MODE) in dps:
            enriched["mode"] = dps[str(DP_MODE)]
        if str(DP_BRIGHTNESS) in dps:
            tuya_val = dps[str(DP_BRIGHTNESS)]
            ha_val = tuya_brightness_to_ha(tuya_val)
            enriched["brightness"] = {
                "tuya": tuya_val,
                "ha": ha_val,
                "percent": round(ha_val / 255 * 100),
            }
        if str(DP_COLOR_TEMP) in dps:
            tuya_val = dps[str(DP_COLOR_TEMP)]
            enriched["color_temp"] = {
                "tuya": tuya_val,
                "kelvin": tuya_ct_to_kelvin(tuya_val),
            }
        if str(DP_COLOR_HSV) in dps:
            hsv_hex = dps[str(DP_COLOR_HSV)]
            if isinstance(hsv_hex, str) and len(hsv_hex) >= 12:
                h, s = parse_hsv_hex(hsv_hex)
                enriched["color"] = {"hue": h, "saturation": s}
        result["enriched"] = enriched

    return web.json_response(result)


@routes.post("/api/power")
async def api_power(request: web.Request) -> web.Response:
    data = await request.json()
    dev = _get_device(data)
    on = data.get("on", True)
    result = await asyncio.get_running_loop().run_in_executor(None, dev.set_status, on, DP_POWER)
    return web.json_response(result)


@routes.post("/api/brightness")
async def api_brightness(request: web.Request) -> web.Response:
    data = await request.json()
    dev = _get_device(data)
    ha_val = int(data["value"])
    tuya_val = ha_brightness_to_tuya(ha_val)
    result = await asyncio.get_running_loop().run_in_executor(None, dev.set_value, DP_BRIGHTNESS, tuya_val)
    return web.json_response(result)


@routes.post("/api/color_temp")
async def api_color_temp(request: web.Request) -> web.Response:
    data = await request.json()
    dev = _get_device(data)
    kelvin = int(data["kelvin"])
    tuya_val = kelvin_to_tuya_ct(kelvin)
    values = {str(DP_MODE): "white", str(DP_COLOR_TEMP): tuya_val}
    result = await asyncio.get_running_loop().run_in_executor(None, dev.set_multiple_values, values)
    return web.json_response(result)


@routes.post("/api/color")
async def api_color(request: web.Request) -> web.Response:
    data = await request.json()
    dev = _get_device(data)
    h = float(data["hue"])
    s = float(data["saturation"])
    brightness = int(data.get("brightness", 255))
    tuya_brightness = ha_brightness_to_tuya(brightness)
    hex_val = hs_to_tuya_hex(h, s, tuya_brightness)
    values = {str(DP_MODE): "colour", str(DP_COLOR_HSV): hex_val}
    result = await asyncio.get_running_loop().run_in_executor(None, dev.set_multiple_values, values)
    return web.json_response(result)


@routes.post("/api/detect_version")
async def api_detect_version(request: web.Request) -> web.Response:
    """Detect protocol version, then try to get status with each version."""
    data = await request.json()
    ip = data["ip_address"]
    dev_id = data["device_id"]
    local_key = data["local_key"]

    # Step 1: Quick probe to guess version from response structure
    hint = await asyncio.get_running_loop().run_in_executor(None, detect_version, ip)

    # Step 2: Order versions — hint first, then others
    all_versions = ["3.3", "3.4", "3.5"]
    if hint and hint in all_versions:
        versions = [hint] + [v for v in all_versions if v != hint]
    else:
        versions = all_versions

    # Step 3: Try each version until status succeeds
    for ver in versions:
        dev = TuyaDevice(dev_id=dev_id, address=ip, local_key=local_key, version=ver)
        dev.set_socketTimeout(5)
        dev.set_socketRetryLimit(1)
        result = await asyncio.get_running_loop().run_in_executor(None, dev.status)
        if result and "dps" in result:
            return web.json_response({
                "version": ver,
                "hint": hint,
                "status": result,
            })

    return web.json_response({
        "version": None,
        "hint": hint,
        "error": "Could not connect with any version. Check device ID and local key.",
    })


@routes.post("/api/scan")
async def api_scan(request: web.Request) -> web.Response:
    data = await request.json()
    timeout = float(data.get("timeout", 5))
    network = data.get("network", "")
    devices = await asyncio.get_running_loop().run_in_executor(None, scan_devices, timeout, network)
    return web.json_response({"devices": devices})


@routes.post("/api/raw")
async def api_raw(request: web.Request) -> web.Response:
    """Send a raw DPS command."""
    data = await request.json()
    dev = _get_device(data)
    dps = data.get("dps", {})
    result = await asyncio.get_running_loop().run_in_executor(None, dev.set_multiple_values, dps)
    return web.json_response(result)


def main() -> None:
    app = web.Application()
    app.add_routes(routes)
    print("Starting Ledvance Tuya test server at http://localhost:8888")
    web.run_app(app, host="0.0.0.0", port=8888)


if __name__ == "__main__":
    main()
