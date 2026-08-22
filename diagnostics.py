"""Diagnostics for Kohler Anthem Plus — the "Download diagnostics" button.

One report, three buttons: the config entry and both device pages (Anthem Valve, Anthem
Plus) all produce the **same** payload, by design — a hardware report should describe the
whole installation, because the two products are one plumbing system and half a picture has
repeatedly misled this project (see ``docs/architecture.md``). The only per-button
difference is the ``requested_for`` field saying which button was pressed.

What this is for: **hardware validation reports.** Every claim in this integration is
verified against exactly one installation (a K-28212 + controller), and the support matrix
in the README only moves on evidence. This file is the evidence: model and outlet split as
detected, which devices exist, what the valve and controller are reporting, whether limits
arrived. A user on unverified hardware attaches this JSON to a "hardware report" issue and
that model's row can be marked verified.

What deliberately stays out: credentials (refresh token), account identity (username,
tenant id), and device identity (device ids, serial numbers, the mobile registration id).
Kohler device serials double as cloud addresses, so they are redacted the same way tokens
are — presence and SKU are enough for validation. Preset and favourite *names* are the
owner's own words and stay out too; counts carry the signal.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_MOBILE_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    CONF_TENANT_ID,
    DOMAIN,
)
from .coordinator import KohlerAnthemPlusCoordinator

# Entry.data/options keys whose VALUES are secrets or identity. Everything else in the
# entry is validation-relevant configuration (model choice, outlet split, units, learned
# run times) and passes through.
TO_REDACT = {
    CONF_USERNAME,
    CONF_REFRESH_TOKEN,
    CONF_TENANT_ID,
    CONF_MOBILE_DEVICE_ID,
}


def _word(word: Any) -> dict[str, Any] | None:
    """One zone's valve word: the wire hex verbatim, then the decoded reading.

    ``raw`` is the word exactly as it arrived (empty for a word seeded from REST, which
    carries no wire form) — included first because the raw word is what settles disputes
    when a decode is questioned on foreign hardware.
    """
    if word is None:
        return None
    return {
        "raw": word.raw or None,
        "temperature_celsius": word.temperature_celsius,
        "flow_percent": word.flow_percent,
        "outlet_mask": word.outlet_mask,
        "paused": word.paused,
        "at_temperature": word.at_temperature,
        "at_flow": word.at_flow,
        "error_flag": word.error_flag,
        "measured_temperature_celsius": word.measured_temperature_celsius,
        "measured_flow_percent": word.measured_flow_percent,
    }


def _build(
    coordinator: KohlerAnthemPlusCoordinator, requested_for: str
) -> dict[str, Any]:
    """The whole installation, as this integration currently understands it."""
    model = coordinator.model
    gcs = coordinator.gcs_state
    hub = coordinator.hub_state
    caps = coordinator.hub_capabilities

    payload: dict[str, Any] = {
        "requested_for": requested_for,
        "model": {
            "sku": model.sku,
            "name": model.name,
            "outlets_valve1": model.outlets_valve1,
            "outlets_valve2": model.outlets_valve2,
            "total_outlets": model.total_outlets,
            "zones": model.zones,
        },
        "devices": {
            "valve_present": coordinator.gcs_device is not None,
            "controller_present": coordinator.hub_device is not None,
        },
        "entry": {
            "data": async_redact_data(dict(coordinator.entry.data), TO_REDACT),
            "options": async_redact_data(dict(coordinator.entry.options), TO_REDACT),
        },
        "stream": {
            "mqtt_connected": bool(coordinator.stream and coordinator.stream.connected),
        },
    }

    if gcs is not None:
        payload["valve"] = {
            "zone_words": {
                str(zone): _word(gcs.zone_word(zone)) for zone in model.zones
            },
            "is_running": gcs.is_running,
            "is_paused": gcs.is_paused,
            "warmup_mode": gcs.warmup_mode,
            "warmup_in_progress": gcs.warmup_in_progress,
            "active_preset_id": gcs.active_preset_id,
            "presets": {
                "slots_seen": len(gcs.presets),
                "selectable": sum(1 for p in gcs.presets.values() if p.is_selectable),
                "experiences": sum(1 for p in gcs.presets.values() if p.is_experience),
                "empty": sum(1 for p in gcs.presets.values() if p.is_empty),
            },
            # Keyed by the device's own 0-based outLetId. Fills in gradually over MQTT
            # and REST; a missing outlet means "never announced", not zero.
            "outlet_limits": {
                str(outlet_id): {
                    "minimum_flow_byte": lim.minimum_flow_byte,
                    "maximum_flow_byte": lim.maximum_flow_byte,
                    "maximum_run_time": lim.maximum_run_time,
                    "default_flow_byte": lim.default_flow_byte,
                }
                for outlet_id, lim in sorted(gcs.outlet_limits.items())
            },
            "last_update": gcs.last_update,
        }
        payload["endless_shower"] = {
            "enabled": coordinator.restart_on_runtime_cutoff,
            "run_times_seconds": {
                str(k): v for k, v in sorted(coordinator.outlet_run_times.items())
            },
            "armed_zones": coordinator.armed_zones,
            "zones_awaiting_run_time": coordinator.zones_awaiting_run_time,
            "flowing_for_seconds": {
                str(zone): coordinator.zone_flowing_for(zone) for zone in model.zones
            },
        }
        payload["warmup"] = {
            "mode": gcs.warmup_mode,
            "auto_restore": coordinator.warmup_auto_restore,
            "restores_to": coordinator.last_warmup_mode,
        }

    if hub is not None:
        payload["controller"] = {
            "zones": {
                str(zone): {
                    "status": getattr(z, "status", None),
                    "outlets": list(getattr(z, "outlets", ()) or ()),
                }
                for zone, z in sorted(hub.zones.items())
            },
            "is_running": hub.is_running,
            "shower_warmup": hub.shower_warmup,
            "music_on": hub.music_on,
            "steam_on": hub.steam_on,
            "light_on": hub.light_on,
            "favorites_count": len(coordinator.favorites or []),
            "active_favorite": hub.active_favorite_id is not None,
            "capabilities": {
                "known": caps.known,
                "water": caps.water,
                "music": caps.music,
                "light": caps.light,
                "steam": caps.steam,
            },
            "last_update": hub.last_update,
        }

    return payload


def _coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> KohlerAnthemPlusCoordinator:
    return hass.data[DOMAIN][entry.entry_id]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Diagnostics from the integration card."""
    return _build(_coordinator(hass, entry), "config_entry")


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Diagnostics from either device page — same report, whichever button was pressed."""
    coordinator = _coordinator(hass, entry)
    requested_for = "unknown_device"
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        if coordinator.gcs_device and identifier == coordinator.gcs_device.device_id:
            requested_for = "valve"
        elif coordinator.hub_device and identifier == coordinator.hub_device.device_id:
            requested_for = "controller"
    return _build(coordinator, requested_for)
