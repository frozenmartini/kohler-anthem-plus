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

from .const import (
    DEVICE_NAME_CONTROLLER,
    DEVICE_NAME_VALVE,
    DOMAIN,
    OUTLET_TYPE_NAMES,
)
from .coordinator import Controller, KohlerAnthemPlusCoordinator, Valve

__all__ = [
    "DEVICE_NAME_CONTROLLER",
    "DEVICE_NAME_VALVE",
    "KohlerControllerEntity",
    "KohlerValveEntity",
    "outlet_name",
    "slug",
    "zone_label",
]


def slug(name: str) -> str:
    """`Zone 2 Rainhead` -> `zone_2_rainhead`, for building a unique id from a name."""
    return "_".join(part.lower() for part in name.split())


def zone_label(valve: Valve, zone: int, label: str) -> str:
    """`Temperature` on a single-zone valve, `Zone 2 Temperature` on a two-zone one.

    With one zone there is nothing to disambiguate, and `Zone 1` on every entity of a
    3-outlet valve is noise. A two-zone valve keeps the prefix, because a bare
    `Temperature` would be ambiguous across zones.
    """
    prefix = f"Zone {zone} " if len(valve.model.zones) > 1 else ""
    return f"{prefix}{label}"


def outlet_name(valve: Valve, zone: int, outlet: int) -> str:
    """`Rainhead`, `Zone 2 Rainhead`, or `Zone 1 Outlet 1` when the fixture is unknown.

    Lives here rather than on the switch because the outlet's run-time sensor needs the
    same name — `Rainhead Max Run Time` beside `Rainhead` — and a sensor platform reaching
    into a switch platform for it would couple the two for no reason.

    Three rules, in order:

    * **The fixture name wins** where the valve's `outLetType` maps to a confirmed one —
      `Rainhead` says what the entity does in a way `Outlet 1` never can.
    * **The zone prefix is dropped on a single-zone valve**, per :func:`zone_label`.
    * **An unknown code falls back to the position** — `Zone 1 Outlet 3`. Naming an outlet
      after a code nobody has confirmed would be inventing a fixture; the number is honest.

    Read **once, at construction**. Per-outlet types arrive gradually over MQTT and via the
    REST seed, so a valve that has not announced yet names its outlets by position and picks
    up fixture names on the next restart. Renaming entities live would change their ids
    underneath running automations, which is worse than waiting.
    """

    def fixture_at(position: int) -> str | None:
        """The confirmed fixture name for a 1-based outlet in this zone, or None."""
        flat = (
            (position - 1) if zone == 1 else valve.model.outlets_valve1 + position - 1
        )
        limits = valve.gcs_state.outlet_limits.get(flat)
        code = None if limits is None else limits.outlet_type
        return None if code is None else OUTLET_TYPE_NAMES.get(code)

    fixture = fixture_at(outlet)
    if fixture is None:
        # No confirmed fixture: keep the position, and keep the zone even on a single-zone
        # valve so the fallback reads the way it always has.
        return f"Zone {zone} Outlet {outlet}"

    # **Two outlets of the same fixture type in one zone is legal** — a pair of body sprays,
    # or the two showerheads a K-28212 can carry. Naming both `Showerhead` would build the
    # same unique id twice, and Home Assistant drops the second silently: one outlet would
    # simply not exist, with no error to explain it. So a repeated fixture keeps its
    # position as a suffix, and only a repeated one does.
    same = [
        position
        for position in range(1, valve.model.outlets_in_zone(zone) + 1)
        if fixture_at(position) == fixture
    ]
    if len(same) > 1:
        return f"{zone_label(valve, zone, fixture)} {same.index(outlet) + 1}"
    return zone_label(valve, zone, fixture)


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
