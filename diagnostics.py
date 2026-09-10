"""Diagnostics for Kohler Anthem Plus — the "Download diagnostics" button.

One report, many buttons: the config entry and every device page (the Anthem Valve and
each Anthem Plus controller) all describe the **whole installation**, by design — a
hardware report should cover everything, because the products are one plumbing system and
half a picture has repeatedly misled this project (see ``docs/architecture.md``). Every
device appears in ``valves`` and ``controllers`` whichever button was pressed.

Two things do follow the button: ``requested_for``, naming it, and the singular ``valve``
/ ``controller`` blocks, which describe **that** device. Those singular keys exist only so
a report from a single-device account reads as it always has; on an account with several,
pressing the second valve's button and getting the first valve's limits under a
``valve_1`` label is precisely the half-picture this module is meant to prevent.

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
    PRESET_HIDDEN_IDS,
)
from .coordinator import Controller, KohlerAnthemPlusCoordinator, Valve

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


def _valve_report(valve: Valve) -> dict[str, Any]:
    """One valve's state, limits, and its own Endless Shower and warm-up settings."""
    gcs = valve.gcs_state
    model = valve.model
    return {
        # The layout this valve actually decodes with — its own, which can differ from the
        # entry's `model` when the account has several valves.
        "model": {
            "sku": model.sku,
            "outlets_valve1": model.outlets_valve1,
            "outlets_valve2": model.outlets_valve2,
        },
        "zone_words": {str(zone): _word(gcs.zone_word(zone)) for zone in model.zones},
        "is_running": gcs.is_running,
        "is_paused": gcs.is_paused,
        "warmup_mode": gcs.warmup_mode,
        "warmup_in_progress": gcs.warmup_in_progress,
        "active_preset_id": gcs.active_preset_id,
        # The valve's own session flag, beside the decoded `is_running`/`is_paused` above.
        # A disagreement between them is worth seeing in a bug report.
        "system_state": gcs.system_state,
        "water": {
            # Raw and filtered both, so a report shows whether the glitch filter fired and
            # by how much — see `GcsState._accept_total_flow`.
            "total_flow_raw": gcs.total_flow,
            "total_flow_published": gcs.total_flow_gallons,
            "glitch_frames_ignored": gcs.total_flow_glitches,
            # Undocumented unit; recorded so the question can be settled from real reports.
            "total_volume": gcs.total_volume,
        },
        "presets": {
            "slots_seen": len(gcs.presets),
            # **`selectable` counts before the hidden ids are removed; `offered` counts
            # after.** They differ by the default-shower slot (`PRESET_HIDDEN_IDS`), which
            # is startable but never listed, so a valve with no user favourites reports
            # `selectable: 1` and `offered: 0`. Reading the first as "one usable
            # favourite" and expecting the picker to show it is a mistake this pair of
            # numbers exists to prevent — `offered` is what the dropdown actually holds.
            "selectable": sum(1 for p in gcs.presets.values() if p.is_selectable),
            "offered": len(gcs.selectable_presets(hidden=PRESET_HIDDEN_IDS)),
            "hidden_ids_present": sorted(
                p.preset_id
                for p in gcs.presets.values()
                if p.preset_id in PRESET_HIDDEN_IDS and not p.is_empty
            ),
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
                # The valve's own type code for this outlet, unmapped. Recorded so the
                # codes seen across real installs can be compared with what the Konnect
                # app shows for the same fixture — only three of them are documented, and
                # a name map has to be built from evidence rather than guessed.
                "outlet_type": lim.outlet_type,
            }
            for outlet_id, lim in sorted(gcs.outlet_limits.items())
        },
        "last_update": gcs.last_update,
        "cloud_connected": valve.cloud_watch.connected,
        "endless_shower": {
            "enabled": valve.restart_on_runtime_cutoff,
            "run_times_seconds": {
                str(k): v for k, v in sorted(valve.outlet_run_times.items())
            },
            "armed_zones": valve.armed_zones,
            "zones_awaiting_run_time": valve.zones_awaiting_run_time,
            "flowing_for_seconds": {
                str(zone): valve.zone_flowing_for(zone) for zone in model.zones
            },
        },
        "warmup": {
            "mode": gcs.warmup_mode,
            "auto_restore": valve.warmup_auto_restore,
            "restores_to": valve.last_warmup_mode,
        },
    }


def _controller_report(controller: Controller) -> dict[str, Any]:
    """One controller's state, capabilities and layout. Device id deliberately absent."""
    hub = controller.state
    caps = controller.capabilities
    model = controller.model
    return {
        # The layout this controller actually decodes with — its own, which can differ
        # from the entry's `model` above when the account has several controllers.
        "model": {
            "sku": model.sku,
            "outlets_valve1": model.outlets_valve1,
            "outlets_valve2": model.outlets_valve2,
        },
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
        "favorites_count": len(controller.favorites or []),
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


def _build(
    coordinator: KohlerAnthemPlusCoordinator,
    requested_for: str,
    valve_index: int = 0,
    controller_index: int = 0,
) -> dict[str, Any]:
    """The whole installation, as this integration currently understands it.

    ``valve_index`` / ``controller_index`` say which device the singular ``valve`` /
    ``controller`` blocks should describe — the one whose Download-diagnostics button was
    pressed. The full ``valves`` / ``controllers`` lists are unaffected and always carry
    every device; see the note beside those blocks for why the singular keys still exist.
    """
    model = coordinator.model

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
            "valve_present": bool(coordinator.valves),
            "valve_count": len(coordinator.valves),
            "controller_present": bool(coordinator.controllers),
            # More than one is a configuration this project has never seen run; the count
            # is what tells a report from such an account apart.
            "controller_count": len(coordinator.controllers),
        },
        "entry": {
            "data": async_redact_data(dict(coordinator.entry.data), TO_REDACT),
            "options": async_redact_data(dict(coordinator.entry.options), TO_REDACT),
        },
        "stream": {
            "mqtt_connected": bool(coordinator.stream and coordinator.stream.connected),
        },
    }

    # One entry per valve, in the cloud's order. `valve`, `endless_shower` and `warmup`
    # (singular) are kept so reports from before 2026-09-08 and after read the same on a
    # single-valve account; `valves` carries all of them, each with its own
    # `endless_shower` and `warmup` nested inside.
    #
    # **The singular block describes the valve whose button was pressed, not always the
    # first.** Until 2026-09-09 it was hardcoded to index 0, so a report downloaded from
    # the second valve's page carried `requested_for: valve_1` above a `valve` block
    # describing valve 0 — two valves on one account can differ in exactly the fields this
    # block is read for (a 30-minute and a 60-minute run-time limit, on the account that
    # found this). The full picture was always present in `valves`; the label was the lie,
    # which is the failure mode this module's header exists to warn about.
    reports = [_valve_report(valve) for valve in coordinator.valves]
    if reports:
        # Defensive: an out-of-range index would be a caller bug, but a diagnostics report
        # that raises is a report nobody can attach to an issue.
        primary = reports[valve_index] if 0 <= valve_index < len(reports) else reports[0]
        payload["valve"] = {
            k: v for k, v in primary.items() if k not in ("endless_shower", "warmup")
        }
        payload["endless_shower"] = primary["endless_shower"]
        payload["warmup"] = primary["warmup"]
        payload["valves"] = reports

    # One entry per controller, in the cloud's order. `controller` (singular) is kept so
    # reports from before 2026-09-08 and after read the same on a single-controller
    # account; `controllers` carries all of them. Follows the pressed device for the same
    # reason as the valve block above.
    reports = [_controller_report(controller) for controller in coordinator.controllers]
    if reports:
        payload["controller"] = (
            reports[controller_index]
            if 0 <= controller_index < len(reports)
            else reports[0]
        )
        payload["controllers"] = reports

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
    """Diagnostics from any device page.

    The whole-installation payload is the same whichever button was pressed — that is the
    point of this module. What follows the button is `requested_for` and the singular
    `valve` / `controller` blocks, which describe the device whose page it came from.
    """
    coordinator = _coordinator(hass, entry)
    requested_for = "unknown_device"
    # Default to the first of each, which is what the config-entry button reports and what
    # every single-device account has always produced.
    valve_index = 0
    controller_index = 0
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        for index, valve in enumerate(coordinator.valves):
            if identifier == valve.device_id:
                requested_for = (
                    "valve" if len(coordinator.valves) == 1 else f"valve_{index}"
                )
                valve_index = index
        for index, controller in enumerate(coordinator.controllers):
            if identifier == controller.device_id:
                # Plain "controller" with one, as every report so far has said; an index
                # into `controllers` when there are several, since ids are redacted.
                requested_for = (
                    "controller"
                    if len(coordinator.controllers) == 1
                    else f"controller_{index}"
                )
                controller_index = index
    return _build(coordinator, requested_for, valve_index, controller_index)
