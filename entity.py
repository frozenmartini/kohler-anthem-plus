"""Shared entity bases.

Two kinds of device are registered, never merged, because they behave differently and their
state arrives on different schedules:

* **Anthem Valve** — a digital valve. Authoritative for outlets, temperature, and flow.
  An account can have several, each its own device bound to its own
  :class:`~.coordinator.Valve`.
* **Anthem Plus** — a system controller. Owns favourites, music, steam, and lighting. An
  account can have several — one per bathroom — and each is its own device, bound to its
  own :class:`~.coordinator.Controller`.

A valve and a controller are usually the same physical shower reached through two different
touchscreens, but presenting them as one device would imply a consistency that does not
exist.

The SKU strings ``GCS`` and ``HUB`` appear nowhere a user can see them. They exist only in
Kohler's API — not in the app, the manual, or on the hardware — so every user-facing string
uses the names Kohler itself shows: "Anthem" and "Anthem Plus".
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_NAME_CONTROLLER, DEVICE_NAME_VALVE, DOMAIN
from .coordinator import Controller, KohlerAnthemPlusCoordinator, Valve

__all__ = [
    "DEVICE_NAME_CONTROLLER",
    "DEVICE_NAME_VALVE",
    "KohlerControllerEntity",
    "KohlerValveEntity",
]


class KohlerValveEntity(CoordinatorEntity[KohlerAnthemPlusCoordinator]):
    """Base for entities belonging to one Anthem digital valve.

    Takes the :class:`~.coordinator.Valve` it belongs to, for the same reason the
    controller base takes a `Controller`: the coordinator holds every valve on the account,
    and an entity reads and commands exactly one. Unique ids are built on that valve's
    device id, so a single-valve install keeps every id it had.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, valve: Valve) -> None:
        super().__init__(coordinator)
        self._valve = valve
        self._device_id = valve.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, valve.device_id)},
            # "Anthem Valve" alone with one valve; suffixed with the Konnect name when
            # there are several — see `coordinator.valve_names`.
            name=valve.name,
            manufacturer="Kohler",
            # The valve's own layout — detected from the valve, else the model chosen at
            # setup — which is what is printed on the hardware, far more useful than the
            # API's "GCS".
            model=valve.model.sku,
            model_id=valve.model.name,
            serial_number=valve.gcs_device.serial_number,
        )

    @property
    def _state(self):
        return self._valve.gcs_state

    @property
    def available(self) -> bool:
        return super().available


class KohlerControllerEntity(CoordinatorEntity[KohlerAnthemPlusCoordinator]):
    """Base for entities belonging to one Anthem Plus system controller.

    Takes the :class:`~.coordinator.Controller` it belongs to, not just the coordinator:
    the coordinator holds every controller on the account, and an entity reads and commands
    exactly one of them. Unique ids are built on that controller's device id, so a
    single-controller install keeps every id it had before the list existed.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: KohlerAnthemPlusCoordinator, controller: Controller
    ) -> None:
        super().__init__(coordinator)
        self._controller = controller
        self._device_id = controller.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.device_id)},
            # "Anthem Plus" alone with one controller; suffixed with the Konnect name when
            # there are several — see `coordinator.controller_names`.
            name=controller.name,
            manufacturer="Kohler",
            model="Anthem+ System Controller",
            serial_number=controller.device.serial_number,
        )

    @property
    def _state(self):
        return self._controller.state

    @property
    def available(self) -> bool:
        """Available whenever the entry is — deliberately no freshness test.

        Session 10 flagged that 18 hours of silence looks healthy here; closed 2026-08-22 as
        designed. This integration is push-only, so silence is the normal state of an unused
        shower — "no messages" means "no changes", not "no data" — and the REST reseed
        refreshes controller state on every reconnect. A staleness timeout would mark a
        healthy-but-quiet system unavailable on every calm day, and the one honest probe (the
        local ping) was removed 2026-08-15 as the integration's only polling loop. The
        controller's Last Update sensor is the freshness surface instead. See
        `docs/hub/cloud_api.md` §5.1.
        """
        return super().available
