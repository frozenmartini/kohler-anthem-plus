"""Valve status and diagnostics.

One headline entity, ``Status``, collapses what the valve is doing into a single value so a
dashboard needs one card rather than four booleans.

Everything else here is diagnostic and **disabled by default**: useful when something looks
wrong, noise otherwise. Enable them individually from the device page.

**No measured-temperature or measured-flow entities.** Bytes 4-6 of the status word carry
live sensor feedback, and on this hardware they read zero in every message ever captured —
including 239 with an outlet open. Entities that can only ever report ``unknown`` are noise,
so they were removed. The decode is intact and both values still appear as attributes on the
hex sensor, where a zero reads as data rather than as a broken entity.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .anthem_plus.models import OutletStateSource, resolve_outlet_source
from .anthem_plus.valve_hex import encode_word
from .const import DOMAIN, EXPOSE_CONTROLLER_WATER_STATE
from .coordinator import KohlerAnthemPlusCoordinator
from .entity import KohlerControllerEntity, KohlerValveEntity

# The four states the valve can be in, in priority order. "Warming Up" outranks "Water
# Running" because warmup does run water — reporting it as an ordinary shower would hide
# why the water started on its own.
STATE_RUNNING = "Water Running"
STATE_PAUSED = "Paused"
STATE_WARMING = "Warming Up"
STATE_IDLE = "Idle"
VALVE_STATES = [STATE_RUNNING, STATE_PAUSED, STATE_WARMING, STATE_IDLE]

# The controller's vocabulary is the valve's minus "Paused" — see `ControllerStatusSensor`.
# Same strings for the three it does have, so the two sensors can be compared directly and
# templated against interchangeably.
CONTROLLER_STATES = [STATE_RUNNING, STATE_WARMING, STATE_IDLE]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the valve sensors, or the controller's where it is the only water source."""
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    if coordinator.gcs_device is not None:
        entities += [
            ValveStatusSensor(coordinator),
            ValveLastUpdateSensor(coordinator),
            ValveHexSensor(coordinator, 1),
            OutletMaxRunTimeSensor(coordinator, 1),
        ]
        if coordinator.model.uses_valve2:
            entities.append(ValveHexSensor(coordinator, 2))

    # Controller-only accounts get the zone temperature from SHOWER_VALVE_STS. Not created
    # where a valve exists: the valve reports its own setpoint per zone, and the controller
    # goes stale the moment the valve is driven directly.
    source = resolve_outlet_source(
        coordinator.gcs_device is not None, coordinator.hub_device is not None
    )
    controller_water = source is OutletStateSource.HUB_MQTT or (
        coordinator.hub_device is not None and EXPOSE_CONTROLLER_WATER_STATE
    )
    if coordinator.hub_device is not None:
        # Diagnostic, and about the controller's *reporting* rather than the water, so it is
        # created on every account that has a controller — unlike everything gated below.
        entities.append(ControllerLastUpdateSensor(coordinator))

    if controller_water:
        entities += [
            ControllerZoneTemperatureSensor(coordinator, zone)
            for zone in coordinator.model.zones
        ]
        # Same gate as the outlet sensors, and for the same reason: this reports water state
        # from the controller, which contradicts the valve during a valve-driven session
        # (`status: OFF` with an all-zero outlet array while water runs). On a controller-only
        # account it is the authoritative answer; alongside a valve it is a comparison tool.
        entities.append(ControllerStatusSensor(coordinator))

    async_add_entities(entities)


class ValveStatusSensor(KohlerValveEntity, SensorEntity):
    """What the shower is doing right now, as one value.

    The headline entity, and **the one place the two devices are deliberately merged.**
    Everything else water-related on a both-devices account reads the valve alone, because
    the controller cannot see a valve-driven session and would contradict it. Warm-up is the
    exception: the valve and the controller each have their *own* warm-up function, and
    either one running means water is about to move. Reading only the valve would miss a
    controller-initiated warm-up entirely.

    That asymmetry is intentional and runs one way only. `ControllerStatusSensor` stays
    purely HUB-derived — it exists to show what the controller believes, and folding valve
    state into it would destroy the comparison it is there to provide.
    """

    _attr_name = "Status"
    _attr_icon = "mdi:shower"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = VALVE_STATES

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_status"

    @property
    def _hub_warmup(self) -> bool:
        """Whether the controller reports a warm-up of its own.

        From `data.showerwarmup` on the controller's `SHOWER_VALVE_STS`. False on a
        valve-only account, where there is no controller to ask.
        """
        hub = self.coordinator.hub_state
        return bool(hub is not None and hub.shower_warmup)

    @property
    def native_value(self) -> str | None:
        state = self._state
        if state is None or state.valve1 is None:
            return None
        # Order matters: a paused session still has a temperature and outlets configured,
        # and warmup runs water without anyone having started a shower.
        if state.is_paused:
            return STATE_PAUSED
        if state.warmup_in_progress or self._hub_warmup:
            return STATE_WARMING
        if state.is_running:
            return STATE_RUNNING
        return STATE_IDLE

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Which device claimed the warm-up, so a merged value stays explainable.

        Without this, "Warming Up" on a both-devices account gives no clue which warm-up is
        running — and the two are independent, so the answer is genuinely useful when the
        wall panel and Home Assistant appear to disagree.
        """
        state = self._state
        return {
            "valve_warmup": bool(state and state.warmup_in_progress),
            "controller_warmup": self._hub_warmup,
        }


class ValveDiagnosticSensor(KohlerValveEntity, SensorEntity):
    """Base for the diagnostics: hidden unless deliberately enabled."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class ValveLastUpdateSensor(ValveDiagnosticSensor):
    """When the valve last reported.

    Carries the event's own timestamp rather than relying on ``last_changed``, which Home
    Assistant stamps when it writes the state — so a restart would otherwise reset it to
    the restart time.
    """

    _attr_name = "Last Update"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_last_update"

    @property
    def native_value(self) -> datetime | None:
        state = self._state
        if state is None or state.last_update is None:
            return None
        return datetime.fromtimestamp(state.last_update, tz=timezone.utc)


class ValveHexSensor(ValveDiagnosticSensor):
    """The valve command word for one zone.

    The single most useful thing to look at when behaviour is surprising: it shows exactly
    what the valve believes, before any decoding. It is also the **intended way to build a
    `kohler_anthem_plus.send_valve_hex` call** — set the shower up with the ordinary outlet
    switches and temperature controls, read the word off here, and paste it into the service.

    **Reports the 8-character command half**, uppercased. Two deliberate normalisations:

    * *Truncated* — the device sends 16 characters, whose second half is live sensor
      feedback. On this hardware measured temperature and flow read zero in every message
      ever captured, so the extra half is 8 zeroes that only make the value harder to copy.
      Nothing is lost: `measured_temperature_celsius`, `measured_flow_percent`, `error_code`
      and `error_flag` are all still published as attributes.
    * *Uppercased* — the device sends lowercase, `encode_word` emits uppercase. Before this,
      the sensor flipped case depending on whether the value arrived over MQTT or came from
      the REST seed, which is a poor thing to ask anyone to copy from.

    It must never rebuild the string from the decoded fields. The version that did was
    written against the superseded ``25.6 + byte1/10`` temperature reading and kept it after
    the codec moved to the 10-bit encoding. The two agree between 25.6 °C and 51.1 °C, so it
    looked right in every ordinary shower and produced nonsense at the edges — a 0 °C
    "full cold" setpoint, which the hardware genuinely accepts, rendered its temperature
    byte as ``-100``. So the truncation above is a slice of `raw`, never a re-encode.
    """

    _attr_icon = "mdi:hexadecimal"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_name = f"Zone {zone} Hex"
        self._attr_unique_id = f"{self._device_id}_zone_{zone}_hex"

    @property
    def _word(self):
        state = self._state
        if state is None:
            return None
        return state.valve1 if self._zone == 1 else state.valve2

    @property
    def native_value(self) -> str | None:
        word = self._word
        if word is None:
            return None
        # A REST-seeded word has no wire string. Encode the command half with the current
        # codec rather than showing nothing, so the sensor is useful before the first MQTT
        # message arrives after a restart. `encode_word` already returns 8 uppercase chars.
        if not word.raw:
            return encode_word(
                word.prefix,
                word.temperature_celsius,
                word.flow_percent,
                word.outlet_mask,
                paused=word.paused,
            )
        # Slice, never re-encode — see the class docstring.
        return word.raw[:8].upper()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        word = self._word
        if word is None:
            return {}
        return {
            "temperature_celsius": word.temperature_celsius,
            "flow_percent": word.flow_percent,
            # `flow_percent` is reported exactly as the word carries it — this sensor's job
            # is to be faithful to the raw word — but on an **idle** valve that number is not
            # the commanded flow. The corpus has 296 such words, in recurring pairs like
            # 34.5%/82.5%, with `totalFlow` collapsing to 2 in the same message and
            # everything back to normal seconds later. So the value is flagged rather than
            # hidden: read `flow_percent` only when this is True.
            "flow_is_live": bool(word.outlet_mask) and not word.paused,
            "flow_setpoint": word.flow_setpoint,
            "outlet_mask": f"0x{word.outlet_mask:02X}",
            "paused": word.paused,
            "prefix": f"0x{word.prefix:02X}",
            "at_temperature": word.at_temperature,
            "at_flow": word.at_flow,
            "error_flag": word.error_flag,
            "error_code": word.error_code,
            "measured_temperature_celsius": word.measured_temperature_celsius,
            "measured_flow_percent": word.measured_flow_percent,
            # Absent on a REST-seeded word, present on anything from MQTT.
            "from_device": bool(word.raw),
        }


class OutletMaxRunTimeSensor(ValveDiagnosticSensor):
    """The `maximumRunTime` the valve has reported for one outlet.

    Learned two ways: read over REST from `gcsadvancestate` at setup and on every MQTT
    reconnect (the 2026-08-17 correction — this was long believed unreadable on demand),
    and absorbed from the valve's unprompted one-outlet-at-a-time MQTT announcements.
    Both funnel through `coordinator._learn_run_times`. This sensor exists so a
    shower-time-limit change made on the panel or the app shows up in Home Assistant
    without waiting for a shower: watch this value after changing the limit, rather than
    guessing whether it took.

    **Reads `unknown` until this specific outlet has been learned at least once** —
    normally within seconds of Home Assistant starting, via the REST read, but genuinely
    unknown before that, not zero. It is also the same figure the run-time cutoff feature arms itself from
    (`coordinator.outlet_run_times`), so a value showing up here means that outlet is now
    protected by the cutoff, too.

    One outlet only, deliberately — every outlet observed on this install has agreed (all six
    at the same `maximumRunTime`), so a second one would just repeat this value. If a future
    install disagrees per outlet, `coordinator.outlet_run_times` already has the full map;
    only the entity is limited to one.
    """

    _attr_icon = "mdi:timer-cog-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, outlet: int) -> None:
        super().__init__(coordinator)
        self._outlet = outlet
        zone, _ = coordinator.model.outlet_location(outlet)
        self._attr_name = f"Zone {zone} Outlet {outlet} Max Run Time"
        self._attr_unique_id = f"{self._device_id}_outlet_{outlet}_max_run_time"

    @property
    def available(self) -> bool:
        """A learned setting, not a live reading — available once known, not gated on state."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> int | None:
        return self.coordinator.outlet_run_times.get(self._outlet)


class ControllerDiagnosticSensor(KohlerControllerEntity, SensorEntity):
    """Base for controller diagnostics: hidden unless deliberately enabled."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class ControllerLastUpdateSensor(ControllerDiagnosticSensor):
    """When the controller last reported.

    The counterpart to ``sensor.anthem_valve_last_update``, and **not redundant with it** —
    the two devices report on entirely separate schedules. The controller can go a whole
    valve-driven session without saying anything (32 of 95 measured episodes), so a
    controller timestamp that lags the valve's by an hour is normal here rather than a
    fault.

    Carries the event's own timestamp rather than relying on ``last_changed``, which Home
    Assistant stamps when it writes the state — so a restart would otherwise reset it to the
    restart time.
    """

    _attr_name = "Last Update"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_last_update"

    @property
    def native_value(self) -> datetime | None:
        state = self._state
        if state is None or state.last_update is None:
            return None
        return datetime.fromtimestamp(state.last_update, tz=timezone.utc)


class ControllerStatusSensor(KohlerControllerEntity, SensorEntity):
    """What the controller believes the shower is doing, from the controller's own data.

    Deliberately **three states, not four: the controller has no concept of "Paused".** That
    is not an omission here, it is absent from the protocol. Across 466 HUB messages in 32
    capture sessions, no attribute key resembling pause, hold, or suspend appears anywhere,
    and per-zone ``status`` takes exactly two values, ``ON`` and ``OFF`` — 264 and 256
    observations. Pause is a GCS concept: bit ``0x40`` of the valve command word. A paused
    session therefore surfaces here as ``Idle``, and the only way to distinguish it is
    ``sensor.anthem_valve_status``, which is on the other device by design.

    Sources, all HUB-native — nothing here reads the valve:

    * **Warming Up** — ``data.showerwarmup`` on ``SHOWER_VALVE_STS``
    * **Water Running** — any zone's ``status`` is ``ON``
    * **Idle** — everything else

    Warm-up outranks running because warm-up *is* running water: all 9 observed warm-up
    messages also had both zones ON, so testing "running" first would mask every one of them.

    Seeded from the ``hub-state`` REST read at setup and on each reconnect, then driven by
    MQTT — the same path as every other controller entity. Without that seed it would read
    ``unknown`` from every restart until the controller next said something, which has been
    as long as 11.9 hours.
    """

    _attr_name = "Status"
    _attr_icon = "mdi:shower"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONTROLLER_STATES

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_status"

    @property
    def native_value(self) -> str | None:
        state = self._state
        if state is None:
            return None
        if state.shower_warmup:
            return STATE_WARMING
        if state.is_running:
            return STATE_RUNNING
        return STATE_IDLE

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self._state
        if state is None:
            return {}
        return {
            # Exposed so a stale or never-populated warm-up reads as data rather than as a
            # confident False: None means no message has ever carried the field.
            "shower_warmup": state.shower_warmup,
            "zone_status": {
                number: zone.status for number, zone in sorted(state.zones.items())
            },
            # A standing reminder on the entity itself that this cannot say "Paused".
            "supports_paused": False,
        }


class ControllerZoneTemperatureSensor(KohlerControllerEntity, SensorEntity):
    """Temperature the controller reports for one zone.

    From ``SHOWER_VALVE_STS``, and **only created on a controller-only account** — where a
    valve exists, its own per-zone setpoint is authoritative and this would go stale the
    moment the valve is driven directly.

    Reported in the **account's** unit rather than Celsius: unlike the GCS valve word, which
    is always tenths of a degree Celsius, the controller sends whatever unit the account is
    configured for. Captured values of ``102`` alongside a 38.8 °C valve setpoint confirm it
    is following the Fahrenheit preference.

    ``null`` while the zone is off, which is why this has no ``state_class`` — it is a live
    reading, not a statistic, and gaps are normal rather than missing data.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_name = f"Zone {zone} Temperature"
        self._attr_unique_id = f"{self._device_id}_zone_{zone}_temperature"
        fahrenheit = coordinator.temperature_unit.lower().startswith("f")
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.FAHRENHEIT if fahrenheit else UnitOfTemperature.CELSIUS
        )

    @property
    def native_value(self) -> float | None:
        state = self._state
        zone = None if state is None else state.zones.get(self._zone)
        if zone is None or zone.temperature is None:
            return None
        try:
            return float(zone.temperature)
        except (TypeError, ValueError):
            return None
