"""The Kohler Anthem Plus integration.

Supports both products in the Anthem line, and works with either or both on an account:

* **Anthem** (SKU ``GCS``) — the digital valve with built-in Wi-Fi. Full outlet,
  temperature, and flow control.
* **Anthem Plus** (SKU ``HUB``) — the Linux system controller that adds music, lighting,
  and steam. Controlled through favourites.

State is push-based over Azure IoT Hub MQTT, with a slow REST poll as a safety net. All
protocol handling lives in the bundled ``anthem_plus`` package, which has no Home Assistant
imports and can be tested offline.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import KohlerAnthemPlusCoordinator
from .const import DOMAIN
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kohler Anthem Plus from a config entry."""
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
    async_register_services(hass, coordinator)

    # Deliberately no "GCS"/"HUB" here: those strings exist only inside Kohler's API and
    # appear nowhere the owner can see them — not the app, the manual, or the hardware.
    found = ", ".join(
        filter(
            None,
            (
                f"Anthem Valve ({coordinator.gcs_device.device_id})"
                if coordinator.gcs_device
                else None,
                f"Anthem Plus ({coordinator.hub_device.device_id})"
                if coordinator.hub_device
                else None,
            ),
        )
    )
    _LOGGER.info(
        "Kohler Anthem Plus ready (%s), valve model %s with %d outlets",
        found or "no devices",
        coordinator.model.sku,
        coordinator.model.total_outlets,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = True
    if PLATFORMS:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown_stream()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            # Only once the last entry is gone: the services are shared, so removing them
            # while another entry is still loaded would break it.
            async_unregister_services(hass)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when something other than the rotating token changed.

    The coordinator writes the refresh token back on every poll because B2C rotates it.
    That goes through ``async_update_entry``, which fires this listener — but reloading on a
    bare token rotation would tear down and rebuild every platform, flapping all entities to
    ``unavailable`` and dropping the MQTT connection along with its warm-up.
    """
    coordinator: KohlerAnthemPlusCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None:
        from .const import CONF_REFRESH_TOKEN

        current = {k: v for k, v in entry.data.items() if k != CONF_REFRESH_TOKEN}
        loaded = {
            k: v
            for k, v in coordinator.entry.data.items()
            if k != CONF_REFRESH_TOKEN
        }
        if current == loaded:
            return
    await hass.config_entries.async_reload(entry.entry_id)
