"""The shower as a single water-heater entity.

One entity per Anthem valve, collapsing what is otherwise a temperature number, a shower
switch, a favourite picker and a warm-up select into the standard Home Assistant card: a
temperature dial plus an operation mode. Nothing here is a new capability — every command
routes through the same `Valve` methods the individual entities use — so the two views
stay consistent and either can be ignored.

**Why a water heater and not a `climate` entity.** `climate` models a space whose
temperature is measured and driven towards a target. This hardware measures nothing: bytes
4-6 of the status word read zero in every message ever captured (see `sensor.py`), so a
`current_temperature` would be permanently `unknown` and every climate card would render
half-empty. `water_heater` asks only for a setpoint, which is exactly what the valve has.

> ### ⚠️ No `pause` operation, deliberately
>
> kenyonj/kohler-konnect-ha exposes `off / warmup / running / pause`, and copying that
> fourth mode here would undo a fix this project made on 2026-08-13. **A pause (`0x40`) is
> byte-identical to the valve's own run-time cutoff**, which is internally
> `{preset, action:"Off"}`. With Endless Shower armed, "Home Assistant paused the shower"
> and "the valve timed out" become the same event on the wire, separated only by a 30 s
> grace window — and the restart logic would fight the user's own pause.
>
> `async_stop_shower` writes `0x00` instead, which is outside the restart-eligible set by
> shape rather than by timing. So `off` here stops rather than pauses, and a pause started
> from the touchscreen is *reported* (`STATE_PAUSED` below) but never *commanded*. See
> `coordinator.Valve.async_stop_shower` and `anthem_plus/runtime_cutoff.py`.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .anthem_plus.const import WARMUP_DISABLED
from .anthem_plus.valve_hex import celsius_to_unit, unit_to_celsius
from .const import (
    DOMAIN,
    SHOWER_ON_PRESET_ID,
    UI_TEMPERATURE_MAX_F,
    UI_TEMPERATURE_MIN_F,
)
from .coordinator import KohlerAnthemPlusCoordinator, Valve
from .entity import KohlerValveEntity

# The operation modes offered. Deliberately three, not four — see the module docstring for
# why `pause` is absent.
OPERATION_OFF = "off"
OPERATION_SHOWER = "shower"
OPERATION_WARMUP = "warmup"
OPERATION_MODES = [OPERATION_OFF, OPERATION_SHOWER, OPERATION_WARMUP]

# Reported, never commanded: a pause started on the touchscreen or by the valve's own
# run-time cutoff. Present in `state` so the card tells the truth, and absent from
# `operation_list` so nobody can select it.
STATE_PAUSED = "paused"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """One water heater per valve. Controllers get none — they have no setpoint to drive.

    A controller cannot set a temperature at all: its only water command is
    `valvecontrol {valveOnOff}` plus favourite activation, so a water-heater entity on one
    would be a temperature dial that silently does nothing. See `entity.py`.
    """
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AnthemShowerWaterHeater(coordinator, valve) for valve in coordinator.valves
    )


class AnthemShowerWaterHeater(KohlerValveEntity, WaterHeaterEntity):
    """The shower: a setpoint and an operation mode.

    **Zone 1 only.** The valve's word carries a setpoint per zone, and a water heater has
    exactly one `target_temperature`. Presenting zone 1's is the honest reduction — it is
    the zone a single-zone valve has, and the primary one otherwise. A two-zone valve keeps
    its per-zone control through the existing `Zone N Temperature` numbers, which this
    entity does not replace.
    """

    _attr_name = "Shower"
    _attr_icon = "mdi:shower"
    _attr_operation_list = OPERATION_MODES
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, valve: Valve) -> None:
        super().__init__(coordinator, valve)
        self._attr_unique_id = f"{self._device_id}_water_heater"
        # Held between a command and the valve reporting back, matching the shower switch
        # and the favourite picker. Activation takes 1-2 s on real hardware, and a control
        # that snaps back before the water moves reads as a failed command.
        self._optimistic: str | None = None

        unit = coordinator.temperature_unit
        fahrenheit = unit.lower().startswith("f")
        self._attr_temperature_unit = (
            UnitOfTemperature.FAHRENHEIT if fahrenheit else UnitOfTemperature.CELSIUS
        )
        # The same Home Assistant-side gate the Zone N Temperature numbers use, for the
        # same reason: the valve accepts 0 °C ("full cold") through 48.8 °C and the codec
        # encodes all of it, but a shower dial offering freezing water is a footgun. The
        # touchscreen and presets are unaffected by this narrowing.
        if fahrenheit:
            self._attr_min_temp = float(UI_TEMPERATURE_MIN_F)
            self._attr_max_temp = float(UI_TEMPERATURE_MAX_F)
        else:
            self._attr_min_temp = float(
                round(unit_to_celsius(UI_TEMPERATURE_MIN_F, "Fahrenheit"))
            )
            self._attr_max_temp = float(
                round(unit_to_celsius(UI_TEMPERATURE_MAX_F, "Fahrenheit"))
            )

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    @property
    def current_operation(self) -> str | None:
        """What the shower is doing, in this entity's vocabulary.

        Priority matches `sensor.ValveStatusSensor` — pause outranks warm-up outranks
        running — so the card and the Status sensor never disagree. The one difference is
        vocabulary: this entity's modes are lowercase command words, because Home Assistant
        renders `operation_list` entries as the selectable options.
        """
        if self._optimistic is not None:
            return self._optimistic
        state = self._state
        if state is None or state.valve1 is None:
            return None
        if state.is_paused:
            # Reported, not offered. A card showing this has one selectable way out —
            # `off`, or `shower` to resume by restarting the preset.
            return STATE_PAUSED
        if state.warmup_in_progress:
            return OPERATION_WARMUP
        if state.is_running:
            return OPERATION_SHOWER
        return OPERATION_OFF

    @property
    def target_temperature(self) -> float | None:
        """Zone 1's setpoint, in the account's unit.

        Rounded to a whole degree to match the Zone 1 Temperature number, so the two
        controls never show different values for the same underlying word.
        """
        state = self._state
        if state is None or state.valve1 is None:
            return None
        return round(
            celsius_to_unit(
                state.valve1.temperature_celsius, self.coordinator.temperature_unit
            )
        )

    @property
    def current_temperature(self) -> None:
        """Always ``None`` — this hardware measures nothing.

        Bytes 4-6 of the status word carry live sensor feedback and read zero in every
        message ever captured, including 239 with an outlet open. Returning the setpoint
        here would make the card look complete while inventing a measurement, which is
        worse than an honest blank. See `sensor.py`.
        """
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        if state is None:
            return {}
        return {
            # True while the touchscreen or the valve's run-time cutoff is holding the
            # session. Surfaced because `paused` is not in `operation_list`, so an
            # automation cannot discover it from the mode alone.
            "paused": state.is_paused,
            "warmup_in_progress": bool(state.warmup_in_progress),
            # Whether `warmup` will do anything if selected — see `async_set_operation_mode`.
            "warmup_available": state.warmup_enabled,
            "system_state": state.system_state,
        }

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set zone 1's setpoint. Safe mid-shower: outlets are preserved.

        `async_apply_valve` rebuilds both words from current state with only this field
        overridden, which is what makes adjusting temperature while water runs safe. Note
        its one asymmetry: flow does not carry forward and is rewritten to 100 %.
        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._valve.async_apply_valve(zone1_temperature=float(temperature))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Start the shower, start warm-up, or stop the water."""
        if operation_mode == OPERATION_OFF:
            await self._async_command(OPERATION_OFF, self._valve.async_stop_shower())
            return

        if operation_mode == OPERATION_SHOWER:
            # The valve has no "run my default", so a whole-shower start names the stored
            # scene `SHOWER_ON_PRESET_ID` — the same one the Shower switch activates. What
            # that preset contains is edited in the Konnect app, not here.
            await self._async_command(
                OPERATION_SHOWER,
                self._valve.async_activate_preset(SHOWER_ON_PRESET_ID),
            )
            return

        if operation_mode == OPERATION_WARMUP:
            state = self._state
            # Warm-up disabled at the fixture is the one failure the cloud hides: it
            # accepts the command with HTTP 200 and the device ignores it. Refusing here
            # is the difference between a silent no-op and a message that names the cause.
            if state is not None and state.warmup_enabled is False:
                raise HomeAssistantError(
                    "Warm-up is disabled on this Anthem valve, so the command would be "
                    "accepted and then ignored. Enable it from the Warmup control, the "
                    "Konnect app, or the touchscreen first."
                )
            await self._async_command(
                OPERATION_WARMUP, self._valve.async_set_warmup(_warmup_start_mode(state))
            )
            return

        raise HomeAssistantError(
            f"{operation_mode!r} is not an operation this shower supports. "
            f"Choose one of: {', '.join(OPERATION_MODES)}."
        )

    # ------------------------------------------------------------------ #
    # Optimistic state, mirroring the shower switch
    # ------------------------------------------------------------------ #
    async def _async_command(self, mode: str, action) -> None:
        self._optimistic = mode
        self.async_write_ha_state()
        try:
            await action
        except Exception:
            # The command failed, so stop showing a mode the valve never reached.
            self._optimistic = None
            self.async_write_ha_state()
            raise

    @callback
    def _handle_coordinator_update(self) -> None:
        """Drop the optimistic mode once the valve's own report agrees with it."""
        if self._optimistic is not None:
            state = self._state
            if state is not None and state.valve1 is not None:
                self._optimistic = None
        super()._handle_coordinator_update()


def _warmup_start_mode(state: Any) -> str:
    """Which warm-up mode to write when the card asks for `warmup`.

    Reuses whatever the valve is already set to, so selecting `warmup` honours the choice
    made in the Warmup select rather than overriding it. Falls back to all-outlets only
    when the valve has never reported a mode — the broadest option, and the one the
    touchscreen offers by default.
    """
    mode = None if state is None else state.warmup_mode
    if mode and mode != WARMUP_DISABLED:
        return str(mode)
    return "warmUpAllOutletsWithNoStartDelay"
