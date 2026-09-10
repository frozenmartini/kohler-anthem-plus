"""The Kohler Anthem Plus integration.

Supports both products in the Anthem line, and works with either or both on an account —
any number of each, every valve and every controller as its own device:

* **Anthem** (SKU ``GCS``) — the digital valve with built-in Wi-Fi. Full outlet,
  temperature, and flow control.
* **Anthem Plus** (SKU ``HUB``) — the Linux system controller that adds music, lighting,
  and steam. Controlled through favourites.

State is push-only over Azure IoT Hub MQTT — there is no polling interval. REST is read on
events: once at setup and again on every MQTT (re)connect, because the broker replays
nothing on connect. All protocol handling lives in the bundled ``anthem_plus`` package,
which has no Home Assistant imports and can be tested offline.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .coordinator import (
    DEV_CAPTURE_INSTALLED,
    KohlerAnthemPlusCoordinator,
    entry_reload_signature,
)
from .const import DOMAIN, ISSUE_NOT_SET_UP, ISSUE_OLD_CAPTURE_FOLDER, OLD_CAPTURE_DIR
from .repairs import inspect_old_capture_folder
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# ---------------------------------------------------------------------------
# Removed 2026-08-15 — valve reboot counter, controller ping, outage counter
# Removed 2026-09-10 — the "Start new MQTT capture" button (0.4.1)
# ---------------------------------------------------------------------------
# Config-entry keys the old diagnostics persisted. They are dead weight now, and leaving
# them would make `_async_update_listener` see a spurious difference on the first load.
_REMOVED_ENTRY_KEYS = (
    "gcs_reboot_count",
    "gcs_reboot_last",
    "hub_local_host",
    "hub_outage_count",
    "hub_outage_last",
    "hub_outage_last_seconds",
)

# Unique-ID suffixes of the entities those diagnostics created. Home Assistant keeps a
# registry row for every entity it has ever seen, so without this the three would linger as
# permanently unavailable rows that only a manual delete would clear.
_REMOVED_UNIQUE_ID_SUFFIXES = (
    "_reboot_count",
    "_local_outages",
    "_local_reachable",
    # The button rolled the author's always-on development capture, which no longer ships;
    # with nothing to roll, the button went too. One per config entry, on the first valve
    # (or the first controller of a controller-only account).
    "_new_mqtt_capture",
)


@callback
def _async_purge_removed_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Strip the removed diagnostics' stored state from Home Assistant.

    Covers both halves of "removed": the config-entry keys they persisted, and the entity
    registry rows they own. Runs on every setup and is a no-op once clean, so a downgrade
    followed by an upgrade cannot leave orphans behind.
    """
    stale = {key: entry.data[key] for key in _REMOVED_ENTRY_KEYS if key in entry.data}
    if stale:
        hass.config_entries.async_update_entry(
            entry,
            data={k: v for k, v in entry.data.items() if k not in _REMOVED_ENTRY_KEYS},
            options={
                k: v for k, v in entry.options.items() if k not in _REMOVED_ENTRY_KEYS
            },
        )
        _LOGGER.info(
            "Removed stale diagnostic keys from the config entry: %s",
            ", ".join(sorted(stale)),
        )
    elif any(key in entry.options for key in _REMOVED_ENTRY_KEYS):
        hass.config_entries.async_update_entry(
            entry,
            options={
                k: v for k, v in entry.options.items() if k not in _REMOVED_ENTRY_KEYS
            },
        )

    registry = er.async_get(hass)
    for row in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        if row.unique_id.endswith(_REMOVED_UNIQUE_ID_SUFFIXES):
            registry.async_remove(row.entity_id)
            _LOGGER.info("Removed retired diagnostic entity %s", row.entity_id)


async def _async_offer_old_capture_cleanup(hass: HomeAssistant) -> None:
    """Raise, or clear, the Repairs card for a `kohler_anthem_plus_raw` folder left behind.

    Every install before 0.4.1 wrote the author's development capture there, unasked and
    unbounded. Nothing ships that writes it now, so a folder that exists is a leftover — a
    few megabytes, inert. Deleting it silently from someone's config directory is not this
    integration's call, so a repair offers it instead: Submit deletes, Ignore keeps.

    Skipped entirely on the author's install, where `_dev/` still writes the folder.

    Transitional: see the sunset note at the top of `repairs.py`.
    """
    if DEV_CAPTURE_INSTALLED:
        return
    path = hass.config.path(OLD_CAPTURE_DIR)
    found = await hass.async_add_executor_job(inspect_old_capture_folder, path)
    if found is None:
        # Absent — and only absent: a folder that cannot be read comes back as present, so
        # the card is never cleared over a leftover that is still there. This branch also
        # clears a card left from a folder deleted by hand.
        ir.async_delete_issue(hass, DOMAIN, ISSUE_OLD_CAPTURE_FOLDER)
        return
    count, size, _foreign = found
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_OLD_CAPTURE_FOLDER,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_OLD_CAPTURE_FOLDER,
        translation_placeholders={
            "path": f"/config/{OLD_CAPTURE_DIR}",
            "count": str(count),
            "size_mb": f"{size / (1024 * 1024):.1f}",
        },
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kohler Anthem Plus from a config entry."""
    _async_purge_removed_diagnostics(hass, entry)
    await _async_offer_old_capture_cleanup(hass)
    coordinator = KohlerAnthemPlusCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # Services are global, not per entry — `async_register_services` is idempotent so this
    # is safe on every entry and every reload. It registers nothing for a HUB-only account:
    # `send_valve_hex` writes to a valve endpoint that such an account does not have.
    # With several valves the actions take a `device_id` to say which one.
    async_register_services(hass, coordinator)

    # Deliberately no "GCS"/"HUB" here: those strings exist only inside Kohler's API and
    # appear nowhere the owner can see them — not the app, the manual, or the hardware.
    found = ", ".join(
        filter(
            None,
            (
                # Every device, each by the name its device page will carry — and, for a
                # valve, the layout it decodes with, which is its own rather than the entry's.
                *(
                    f"{v.name} ({v.device_id}, {v.model.sku}, {v.model.total_outlets} outlets)"
                    for v in coordinator.valves
                ),
                *(f"{c.name} ({c.device_id})" for c in coordinator.controllers),
            ),
        )
    )
    _LOGGER.info("Kohler Anthem Plus ready (%s)", found or "no devices")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = True
    if PLATFORMS:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Repairs outlive the config entry, so an entry being removed would otherwise leave a
        # card pointing at an integration that is no longer installed. Deleting a missing
        # issue is a no-op, so this is safe on a plain reload too — setup re-raises it if the
        # condition still holds.
        coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # The per-valve ids, plus the entry-only id an install from before 2026-09-08 may
        # still be carrying.
        ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_NOT_SET_UP}_{entry.entry_id}")
        for valve in coordinator.valves:
            ir.async_delete_issue(hass, DOMAIN, valve.issue_id)
        await coordinator.async_shutdown_stream()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            # Only once the last entry is gone: the services are shared, so removing them
            # while another entry is still loaded would break it. The capture-folder card is
            # integration-wide the same way; left behind, it would point at a fix flow whose
            # code is no longer loaded.
            async_unregister_services(hass)
            ir.async_delete_issue(hass, DOMAIN, ISSUE_OLD_CAPTURE_FOLDER)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when the entry changed in a way that needs one.

    This integration writes to its own config entry while running — the rotating refresh
    token whenever B2C issues a new one, and ``maximumRunTime`` whenever the valve announces
    one, which it does unprompted and can do mid-shower. Every one of those writes fires this
    listener. Reloading on them would flap all entities to ``unavailable``, drop the MQTT
    connection with its warm-up, and reset the run-time cutoff's zone clocks while the valve's
    own timer kept running.

    So the decision is a comparison against ``coordinator.reload_signature``, the frozen
    snapshot taken when the coordinator was built. ``RELOAD_IGNORED_DATA_KEYS`` and
    ``RELOAD_IGNORED_OPTION_KEYS`` in ``const.py`` say what is excluded and why; anything
    else — including a key nobody anticipated — reloads.

    ⚠️ **Do not compare against ``coordinator.entry``.** That is the same object Home
    Assistant mutates in place, so it always equals ``entry`` and this listener becomes dead
    code that returns early every time. That was the defect here until 2026-08-17; see
    ``anthem_plus/entry_reload.py``.
    """
    coordinator: KohlerAnthemPlusCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None and entry_reload_signature(entry) == (
        coordinator.reload_signature
    ):
        return
    await hass.config_entries.async_reload(entry.entry_id)
