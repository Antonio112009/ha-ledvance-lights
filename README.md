# Ledvance Lights

[![HACS Validation](https://github.com/Antonio112009/ha-ledvance-lights/actions/workflows/hacs.yml/badge.svg)](https://github.com/Antonio112009/ha-ledvance-lights/actions/workflows/hacs.yml)
[![CI](https://github.com/Antonio112009/ha-ledvance-lights/actions/workflows/ci.yml/badge.svg)](https://github.com/Antonio112009/ha-ledvance-lights/actions/workflows/ci.yml)

Home Assistant custom integration for controlling **Ledvance Smart+ WiFi** lights locally via the Tuya protocol — no cloud required.

## Features

- Local control over your network (no cloud dependency)
- Auto-discovery of devices on the local network
- Supports brightness, colour temperature, HSV colour, and scene effects
- Diagnostics support for troubleshooting

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → **⋮** → **Custom repositories**.
3. Add `https://github.com/Antonio112009/ha-ledvance-lights` with category **Integration**.
4. Install **Ledvance Lights**.
5. Restart Home Assistant.

### Manual

1. Copy the `custom_components/ha_ledvance_lights` folder into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **Ledvance Lights**.
3. Follow the setup flow — you can scan for devices on your network or enter details manually.
4. You will need the device's **Local Key** (obtainable from the Tuya IoT Platform).

## Requirements

- Ledvance Smart+ WiFi light(s)
- Device Local Key from the [Tuya IoT Platform](https://iot.tuya.com/)

## License

This project is provided as-is for personal use.
