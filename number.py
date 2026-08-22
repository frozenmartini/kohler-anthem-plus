"""Per-zone temperature for the Anthem valve.

One entity per zone, because the valve carries an independent temperature byte for each. A
zone maps to a valve: zone 1 is the primary, zone 2 the secondary. Zone 2 entities only
exist on models that have a second valve.

Setting the value re-sends the complete valve command — the valve accepts no partial write —
preserving whichever outlets are currently open and the current flow. That mirrors the
Konnect app, which POSTs a fresh command on every adjustment, and it means changing the
temperature mid-shower takes effect immediately rather than at the next start.

**There is deliberately no flow entity.** The codec encodes and decodes flow correctly and
the valve honours a flow byte we write — but the Anthem Plus touchscreen overwrites both
zones with its own linked scaling and a calibration-derived ceiling the moment anyone touches its
flow control, so a Home Assistant setpoint could not be relied on to stay put. Removed
rather than shipped as something that silently disagrees with the wall panel. The evidence
and the full findings are in ``docs/gcs/api.md``; re-adding it is a UI change only, since
nothing was removed from the protocol layer.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .anthem_plus.valve_hex import celsius_to_unit, unit_to_celsius
from .const import DOMAIN, UI_TEMPERATURE_MAX_F, UI_TEMPERATURE_MIN_F
from .coordinator import KohlerAnthemPlusCoordinator
from .entity import KohlerValveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a temperature number for each zone the valve has.

    No flow number, deliberately — see the module docstring.
    """
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.gcs_device is None:
        # The controller offers no live temperature or flow control — only favourites.
        return

    zones = [1, 2] if coordinator.model.uses_valve2 else [1]
    entities: list[NumberEntity] = []
    for zone in zones:
        entities.append(ZoneTemperatureNumber(coordinator, zone))
    async_add_entities(entities)


class ZoneNumberBase(KohlerValveEntity, NumberEntity):
    """Shared plumbing for the per-zone numbers."""

    # SLIDER rather than BOX: the range is now narrow enough (80-113 °F) that dragging is
    # quicker than typing, which was not true of the old 32-119 °F span.
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone

    @property
    def _word(self):
        state = self._state
        if state is None:
            return None
        return state.valve1 if self._zone == 1 else state.valve2


class ZoneTemperatureNumber(ZoneNumberBase):
    """Temperature setpoint for one zone.

    Presented in the account's unit as a whole number, with 0.1 °C resolution underneath, so
    a whole degree Fahrenheit is always representable.

    The bottom of the range is a real setting, not a rounding artefact: **0 °C / 32 °F means
    "full cold"** — the valve stops mixing hot and delivers whatever the supply provides.
    It will not produce freezing water; on the system captured, the cold supply bottomed out
    near 60 °F while the setpoint read 32 °F.
    """

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_step = 1

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, zone: int) -> None:
        super().__init__(coordinator, zone)
        # "Zone N <thing>", matching the outlet switches. Home Assistant sorts a device
        # page alphabetically within each category, so leading with the zone keeps a zone's
        # controls together instead of scattering Flow/Temperature away from its outlets.
        self._attr_name = f"Zone {zone} Temperature"
        self._attr_unique_id = f"{self._device_id}_temperature_zone_{zone}"
        unit = coordinator.temperature_unit
        fahrenheit = unit.lower().startswith("f")
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.FAHRENHEIT if fahrenheit else UnitOfTemperature.CELSIUS
        )
        # Bounds are a **Home Assistant-side gate**, not the device's range — see
        # `UI_TEMPERATURE_MIN_F` / `UI_TEMPERATURE_MAX_F`. The valve still accepts 0 °C
        # ("full cold") through 48.8 °C, the codec still encodes all of it, and the
        # touchscreen or a preset can still take it outside these numbers. Narrowing this
        # only decides what the slider offers.
        if fahrenheit:
            low = float(UI_TEMPERATURE_MIN_F)
            high = float(UI_TEMPERATURE_MAX_F)
        else:
            # Rounded, not floored/ceiled: these are presentation bounds, and 26.7/45.0
            # showing as 27/45 is friendlier than 27/45 with a hidden fraction.
            low = float(round(unit_to_celsius(UI_TEMPERATURE_MIN_F, "Fahrenheit")))
            high = float(round(unit_to_celsius(UI_TEMPERATURE_MAX_F, "Fahrenheit")))
        self._attr_native_min_value = low
        self._attr_native_max_value = high

    @property
    def native_value(self) -> float | None:
        word = self._word
        if word is None:
            return None
        return round(
            celsius_to_unit(
                word.temperature_celsius, self.coordinator.temperature_unit
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        key = "zone1_temperature" if self._zone == 1 else "zone2_temperature"
        await self.coordinator.async_apply_valve(**{key: value})

