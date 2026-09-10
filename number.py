"""Per-zone temperature for the Anthem valve.

One entity per zone, because the valve carries an independent temperature byte for each. A
zone maps to a valve: zone 1 is the primary, zone 2 the secondary. Zone 2 entities only
exist on models that have a second valve.

Setting the value re-sends the complete valve command — the valve accepts no partial write —
preserving whichever outlets are currently open and the current flow. That mirrors the
Konnect app, which POSTs a fresh command on every adjustment, and it means changing the
temperature mid-shower takes effect immediately rather than at the next start.

**Flow is a per-zone control here, restored 2026-09-10.** It was removed on 2026-08-13
because a first-gen Anthem touchscreen was observed rewriting both zones' flow the instant
its flow panel was opened, making a Home Assistant setpoint impossible to rely on. That
finding stands — the capture is in ``docs/gcs/api.md`` — but the conclusion drawn from it
was too broad: it came from **one** install, and it was applied to every valve
unconditionally, so owners whose valve honours a written flow byte had no control either.

Restored as a valve entity because flow is the valve's own capability: the codec encodes
and decodes byte 2 in full, ``async_apply_valve`` has always accepted ``zone1_flow`` /
``zone2_flow``, and the valve honours what it is given within its calibrated range. On an
install whose panel does fight it, the entity can be disabled; that is a better failure than
withholding the control from everyone.

The bounds are the valve's **own** reported limits, not a constant — ``zone_flow_limits``
reads the per-outlet minimum and maximum the hardware announces, so a valve with flow
control disabled reports a narrow range rather than being offered one it will not honour.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .anthem_plus.valve_hex import (
    FLOW_BYTE_MAX,
    FLOW_BYTE_MIN,
    FLOW_PER_PERCENT,
    celsius_to_unit,
    unit_to_celsius,
)
from .const import (
    DEFAULT_FLOW_PERCENT,
    DOMAIN,
    UI_TEMPERATURE_MAX_F,
    UI_TEMPERATURE_MIN_F,
)
from .coordinator import KohlerAnthemPlusCoordinator, Valve
from .entity import KohlerValveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a temperature and a flow number for each zone the valve has."""
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    # The controller offers no live temperature or flow control — only favourites — so a
    # controller-only account gets nothing here. One set per valve otherwise, each with
    # the zones its own layout has.
    entities: list[NumberEntity] = []
    for valve in coordinator.valves:
        for zone in valve.model.zones:
            entities.append(ZoneTemperatureNumber(coordinator, valve, zone))
            entities.append(ZoneFlowNumber(coordinator, valve, zone))
    async_add_entities(entities)


class ZoneNumberBase(KohlerValveEntity, NumberEntity):
    """Shared plumbing for the per-zone numbers."""

    # SLIDER rather than BOX: the range is now narrow enough (80-113 °F) that dragging is
    # quicker than typing, which was not true of the old 32-119 °F span.
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, coordinator: KohlerAnthemPlusCoordinator, valve: Valve, zone: int
    ) -> None:
        super().__init__(coordinator, valve)
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

    def __init__(
        self, coordinator: KohlerAnthemPlusCoordinator, valve: Valve, zone: int
    ) -> None:
        super().__init__(coordinator, valve, zone)
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
        await self._valve.async_apply_valve(**{key: value})


class ZoneFlowNumber(ZoneNumberBase):
    """Flow setpoint for one zone, as a percentage.

    Writes byte 2 of that zone's valve word through the same ``async_apply_valve`` path the
    temperature uses, so the outlets currently open are preserved and a change mid-shower
    takes effect immediately.

    **The range is the valve's own.** ``zone_flow_limits`` returns the minimum and maximum
    flow bytes this zone's first outlet reports — the same pair the Konnect app bounds its
    slider with — falling back to the protocol limits (8-100 %) only when the valve has not
    announced them yet. A valve with flow control disabled therefore offers the narrow range
    it will actually honour rather than a full sweep it will ignore.

    > ⚠️ **A first-gen Anthem touchscreen may overwrite this.** Opening that panel's flow
    > control was captured rewriting *both* zones before any adjustment was made, applying
    > its own linked scaling and a calibration-derived ceiling. On such an install a
    > setpoint written here can change on its own, which is why this entity was withdrawn
    > between 2026-08-13 and 2026-09-10. If yours behaves that way, disable this entity —
    > the protocol layer is unaffected either way.

    **While the shower is off, this reads the last flow Home Assistant wrote, or 100 %.**
    It deliberately does not echo the valve's idle byte, which is not the flow setting: one
    install carries transient junk there, and another carries *stable* junk — 24.5 % and
    26.5 %, unmoving across hours, while the owner's panel held 100 % on both valves. A
    number that does not move is more convincing than one that flickers, not less, so
    neither is shown as a setpoint.

    A control has to display something, so the entity remembers what it last wrote and
    falls back to `DEFAULT_FLOW_PERCENT` — which is also what `async_apply_valve` sends when
    no flow is specified, so the displayed value and the commanded value agree. Once water
    is running the valve's own byte is authoritative and is shown directly.

    `flow_is_live` says which of the two you are looking at.
    """

    _attr_icon = "mdi:water-percent"
    _attr_native_unit_of_measurement = PERCENTAGE
    # The byte is 2 units per percent, so 0.5 % is the finest step the wire can carry.
    # Whole percents keep the slider usable and every value exactly representable.
    _attr_native_step = 1

    def __init__(
        self, coordinator: KohlerAnthemPlusCoordinator, valve: Valve, zone: int
    ) -> None:
        super().__init__(coordinator, valve, zone)
        self._attr_name = f"Zone {zone} Flow"
        self._attr_unique_id = f"{self._device_id}_flow_zone_{zone}"
        # What to show when the valve's own byte cannot be trusted — see the class
        # docstring. `DEFAULT_FLOW_PERCENT` is what `async_apply_valve` writes when no flow
        # is given, so an untouched entity displays exactly what a command would send.
        self._last_written: float = DEFAULT_FLOW_PERCENT

    @property
    def native_min_value(self) -> float:
        """The valve's own minimum for this zone, read live rather than fixed at setup.

        Per-outlet limits arrive gradually over MQTT, so a bound captured in ``__init__``
        would be the fallback for as long as the valve stayed quiet.
        """
        state = self._state
        if state is None:
            return FLOW_BYTE_MIN / FLOW_PER_PERCENT
        low, _ = state.zone_flow_limits(self._zone)
        return low / FLOW_PER_PERCENT

    @property
    def native_max_value(self) -> float:
        state = self._state
        if state is None:
            return FLOW_BYTE_MAX / FLOW_PER_PERCENT
        _, high = state.zone_flow_limits(self._zone)
        return high / FLOW_PER_PERCENT

    @property
    def native_value(self) -> float | None:
        """The valve's byte while water runs; otherwise what we last wrote, or 100 %.

        See the class docstring for why the idle byte is not echoed.
        """
        state = self._state
        if state is not None and state.flow_is_live:
            word = self._word
            if word is not None:
                return word.flow_percent
        return self._last_written

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Whether water is moving, and the valve's own bounds for this zone.

        `flow_is_live` is **information, not a warning**: it says an outlet is open, which
        is worth knowing when reading history, but the value is trustworthy either way on
        hardware whose idle byte is stable. See `GcsState.flow_is_live`.

        The bounds are published too, because a valve with flow control disabled reports a
        narrow range and a slider that will not move needs to say why.
        """
        state = self._state
        if state is None:
            return {}
        low, high = state.zone_flow_limits(self._zone)
        return {
            # False means the value above is what Home Assistant last wrote, not a reading
            # from the valve — see the class docstring.
            "flow_is_live": state.flow_is_live,
            # The byte the valve is actually holding, whatever it means. Published so the
            # idle-byte behaviour stays observable rather than merely asserted.
            "reported_flow_percent": state.flow_percent,
            "minimum_percent": low / FLOW_PER_PERCENT,
            "maximum_percent": high / FLOW_PER_PERCENT,
            # True where the valve reports a single-point range — flow control is off at
            # the fixture, so the slider is fixed and that is the hardware's doing.
            "flow_control_available": low != high,
        }

    async def async_set_native_value(self, value: float) -> None:
        key = "zone1_flow" if self._zone == 1 else "zone2_flow"
        await self._valve.async_apply_valve(**{key: float(value)})
        # Remembered so an idle valve shows what was asked for rather than reverting to the
        # byte it happens to be holding. Recorded only after the write is accepted.
        self._last_written = float(value)
        self.async_write_ha_state()

