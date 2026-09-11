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

import math
from typing import Any

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
    flow_byte_to_percent,
    flow_percent_to_byte,
    unit_to_celsius,
)
from .const import (
    DEFAULT_FLOW_PERCENT,
    DOMAIN,
    UI_TEMPERATURE_MAX_F,
    UI_TEMPERATURE_MIN_F,
)
from .coordinator import KohlerAnthemPlusCoordinator, Valve
from .entity import ZoneWordEntity, zone_label


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


class ZoneNumberBase(ZoneWordEntity, NumberEntity):
    """Shared plumbing for the per-zone numbers.

    `__init__` and `_word` come from `ZoneWordEntity`.
    """

    # SLIDER rather than BOX: the range is now narrow enough (92-118 °F) that dragging is
    # quicker than typing, which was not true of the old 32-119 °F span.
    _attr_mode = NumberMode.SLIDER


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
        self._attr_name = zone_label(valve, zone, "Temperature")
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
        """The valve's setpoint, **clamped into this entity's declared range.**

        The bounds are a Home Assistant-side gate, not the device's: the valve accepts
        0 °C ("full cold") through 48.8 °C, and the touchscreen or a preset can put it
        there. Reporting a value outside `native_min_value`/`native_max_value` leaves the
        slider with no position it can render and, in Celsius, a 0 °C setpoint reads as a
        plain `0` against a 27-45 range — which looks like a broken entity rather than a
        deliberate setting.

        Clamped rather than widened because the narrow range is the point: it keeps the
        slider usable for the temperatures people actually shower at. The unclamped reading
        is published as `reported_temperature` so nothing is hidden, and a value that is
        being clamped says so in `out_of_range`.
        """
        word = self._word
        if word is None:
            return None
        value = round(
            celsius_to_unit(word.temperature_celsius, self.coordinator.temperature_unit)
        )
        return min(max(value, self._attr_native_min_value), self._attr_native_max_value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The valve's real setpoint, and whether this entity is clamping it."""
        word = self._word
        if word is None:
            return {}
        reported = round(
            celsius_to_unit(word.temperature_celsius, self.coordinator.temperature_unit)
        )
        return {
            "reported_temperature": reported,
            "out_of_range": not (
                self._attr_native_min_value <= reported <= self._attr_native_max_value
            ),
        }

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
    # **Whole percents, by the owner's decision.** The wire resolves to 0.5 % — one byte is
    # half a percent — and 0.7.4 briefly exposed that. It was reverted here because a control
    # is for choosing a flow, not for mirroring the device's internal precision: half-percent
    # steps double the travel needed to cross the range and offer a distinction nobody can
    # feel in a shower.
    #
    # The cost is deliberate and bounded. Where the valve reports a half value — both of the
    # owner's valves do, 24.5 % and 26.5 % — `native_value` rounds it for display, so the
    # entity reads 25 % and 27 % while the valve holds the half. Adjusting the slider then
    # writes the whole number, moving the real flow by at most 0.5 %: below the resolution of
    # anything a person notices, and it only happens when the control is actually used.
    #
    # Every whole percent is exactly representable (percent * 2 is always an integer byte),
    # so nothing is lost on the write path.
    _attr_native_step = 1

    def __init__(
        self, coordinator: KohlerAnthemPlusCoordinator, valve: Valve, zone: int
    ) -> None:
        super().__init__(coordinator, valve, zone)
        self._attr_name = zone_label(valve, zone, "Flow")
        self._attr_unique_id = f"{self._device_id}_flow_zone_{zone}"
        # The chosen flow lives on the valve rather than on this entity, because the outlet
        # switches need it too: toggling an outlet rewrites the whole word, and without a
        # shared value it would reset the flow this entity had set. Seeded with
        # `DEFAULT_FLOW_PERCENT`, which is what an unspecified write sends anyway.
        self._valve.zone_flow.setdefault(zone, DEFAULT_FLOW_PERCENT)

    @property
    def native_min_value(self) -> float:
        """The valve's own minimum for this zone, read live rather than fixed at setup.

        Per-outlet limits arrive gradually over MQTT, so a bound captured in ``__init__``
        would be the fallback for as long as the valve stayed quiet.
        """
        state = self._state
        if state is None:
            return FLOW_BYTE_MIN / FLOW_PER_PERCENT
        low, high = state.zone_flow_limits(self._zone)
        # Rounded UP, and away from the forbidden side: an odd limit byte would otherwise put
        # the bound on a half and, with a whole-number step, every position on the slider
        # would carry that .5 — defeating the point. Ceiling rather than round, so the bound
        # never sits below what the valve will accept.
        return math.ceil(flow_byte_to_percent(low, high))

    @property
    def native_max_value(self) -> float:
        state = self._state
        if state is None:
            return FLOW_BYTE_MAX / FLOW_PER_PERCENT
        _, high = state.zone_flow_limits(self._zone)
        # The ceiling **is** 100 % by definition — percent is a ratio against it, so the
        # maximum can only be 100. Kept as arithmetic rather than a literal so the two bounds
        # visibly come from the same place.
        return math.floor(flow_byte_to_percent(high, high))

    @property
    def native_value(self) -> float | None:
        """The valve's byte while water runs; otherwise what we last wrote, or 100 %.

        See the class docstring for why the idle byte is not echoed.
        """
        state = self._state
        if state is not None and state.flow_is_live:
            word = self._word
            if word is not None:
                # Re-derived from the raw byte against **this zone's own ceiling** rather
                # than read off `word.flow_percent`, which `decode_word` computes with the
                # 200 default. Identical wherever the ceiling is 200; correct where it is
                # not. See `flow_byte_to_percent`.
                _, high = state.zone_flow_limits(self._zone)
                # Rounded to the step. The valve resolves finer than this control does, so an
                # unrounded value would sit between two positions the slider can occupy —
                # Home Assistant would render a number the user cannot return to.
                # `word.flow_percent` was decoded against the 200 default, so multiplying
                # it back recovers the raw byte exactly — `decode_word` does `byte * 100 /
                # 200`, and this undoes precisely that. Cheaper and less invasive than
                # threading per-valve limits through the decoder, which has 28 call sites
                # and no per-valve context.
                byte = round(word.flow_percent * FLOW_PER_PERCENT)
                return round(flow_byte_to_percent(byte, high))
        return self._valve.zone_flow.get(self._zone, DEFAULT_FLOW_PERCENT)

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
            # The outlet's own ceiling, in raw byte units. Published because percent is a
            # ratio against it: two valves showing "50 %" are at the same fraction of their
            # own maximum, not necessarily the same flow.
            "maximum_flow_byte": high,
            # False means the value above is what Home Assistant last wrote, not a reading
            # from the valve — see the class docstring.
            "flow_is_live": state.flow_is_live,
            # The byte the valve is actually holding, whatever it means. Published so the
            # idle-byte behaviour stays observable rather than merely asserted.
            "reported_flow_percent": state.flow_percent,
            "minimum_percent": flow_byte_to_percent(low, high),
            "maximum_percent": flow_byte_to_percent(high, high),
            # True where the valve reports a single-point range — flow control is off at
            # the fixture, so the slider is fixed and that is the hardware's doing.
            "flow_control_available": low != high,
        }

    async def async_set_native_value(self, value: float) -> None:
        key = "zone1_flow" if self._zone == 1 else "zone2_flow"
        # `async_apply_valve` takes a percent and encodes it against the 200 default, so a
        # zone with a different ceiling needs the percent restated in those terms: the byte
        # this percent means on **this** zone, expressed as the percent that produces the
        # same byte at 200. Identity wherever the ceiling is 200, which is every device in
        # the corpus.
        state = self._state
        if state is not None:
            _, high = state.zone_flow_limits(self._zone)
            byte = flow_percent_to_byte(float(value), high)
            value = flow_byte_to_percent(byte, FLOW_BYTE_MAX)
        await self._valve.async_apply_valve(**{key: float(value)})
        # Remembered on the valve so an idle entity shows what was asked for rather than
        # the byte it happens to be holding, and so an outlet toggle preserves it. Recorded
        # only after the write is accepted.
        self._valve.zone_flow[self._zone] = float(value)
        self.async_write_ha_state()
