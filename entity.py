"""Shared entity bases.

Two devices are registered, never merged, because they behave differently and their state
arrives on different schedules:

* **Anthem Valve** — the digital valve. Authoritative for outlets, temperature, and flow.
* **Anthem Plus** — the system controller. Owns favourites, music, steam, and lighting.

They are usually the same physical shower reached through two different touchscreens, but
presenting them as one device would imply a consistency that does not exist.

The SKU strings ``GCS`` and ``HUB`` appear nowhere a user can see them. They exist only in
Kohler's API — not in the app, the manual, or on the hardware — so every user-facing string
uses the names Kohler itself shows: "Anthem" and "Anthem Plus".
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KohlerAnthemPlusCoordinator

# Device display names. These also decide entity_id prefixes, because Home Assistant builds
# entity ids from the device name plus the entity name — so "Anthem Valve" + "Outlet 1"
# yields `binary_sensor.anthem_valve_outlet_1`.
DEVICE_NAME_VALVE = "Anthem Valve"
DEVICE_NAME_CONTROLLER = "Anthem Plus"


class KohlerValveEntity(CoordinatorEntity[KohlerAnthemPlusCoordinator]):
    """Base for entities belonging to the Anthem digital valve."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.gcs_device
        assert device is not None
        self._device_id = device.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=DEVICE_NAME_VALVE,
            manufacturer="Kohler",
            # The valve model the user selected at setup, which is what is printed on the
            # hardware — far more useful than the API's "GCS".
            model=coordinator.model.sku,
            model_id=coordinator.model.name,
            serial_number=device.serial_number,
        )

    @property
    def _state(self):
        return self.coordinator.gcs_state

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.gcs_state is not None


class KohlerControllerEntity(CoordinatorEntity[KohlerAnthemPlusCoordinator]):
    """Base for entities belonging to the Anthem Plus system controller."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.hub_device
        assert device is not None
        self._device_id = device.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=DEVICE_NAME_CONTROLLER,
            manufacturer="Kohler",
            model="Anthem+ System Controller",
            serial_number=device.serial_number,
        )

    @property
    def _state(self):
        return self.coordinator.hub_state

    @property
    def available(self) -> bool:
        """Available whenever hub state exists — deliberately no freshness test.

        Session 10 flagged that 18 hours of silence looks healthy here; closed 2026-08-22 as
        designed. This integration is push-only, so silence is the normal state of an unused
        shower — "no messages" means "no changes", not "no data" — and the REST reseed
        refreshes hub state on every reconnect. A staleness timeout would mark a
        healthy-but-quiet system unavailable on every calm day, and the one honest probe (the
        local ping) was removed 2026-08-15 as the integration's only polling loop. The
        controller's Last Update sensor is the freshness surface instead. See
        `docs/hub/cloud_api.md` §5.1.
        """
        return super().available and self.coordinator.hub_state is not None
