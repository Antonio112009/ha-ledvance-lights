"""Tuya local protocol library for Ledvance Lights."""

from .device import TuyaDevice
from .scanner import scan_devices

__all__ = ["TuyaDevice", "scan_devices"]
