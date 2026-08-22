"""Binary sensors.

Two unrelated groups live here:

* **Valve diagnostics** — stream health, and per-zone and at-temperature readings. Mostly
  disabled by default; they matter when something is not behaving, not day to day.
* **Controller outlets** — created *only* on accounts with no Anthem Valve. Where a valve
  exists it owns the outlets, as switches.

The controller's view of a session driven through the valve's own API is unreliable —
measured across 95 such episodes: 51 reported immediately, 12 late, 32 never, and
preset-driven openings never (0 of 15). Outlet entities sourced from it on such an account
would freeze through an unpredictable share of showers, which is worse than not existing.
See ``anthem_plus.models.resolve_outlet_source``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .anthem_plus.models import OutletStateSource, resolve_outlet_source
from .const import DOMAIN, EXPOSE_CONTROLLER_WATER_STATE
from .coordinator import KohlerAnthemPlusCoordinator
from .entity import KohlerControllerEntity, KohlerValveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up valve diagnostics, and controller outlets where they are the only source."""
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    if coordinator.gcs_device is not None:
        entities += [
            ValveAtTemperatureSensor(coordinator),
            MqttConnectionSensor(coordinator),
            ValvePresetActiveSensor(coordinator),
        ]
        # One per zone the model actually has. A single-zone valve must not get a "Zone 2"
        # that is permanently off — `model.zones` is the only correct source for this.
        entities += [
            ValveZoneActiveSensor(coordinator, zone) for zone in coordinator.model.zones
        ]

    # Music is independent of the water path: it comes from MUSIC_STS, which the controller
    # reports for its own amplifier regardless of what drives the valve.
    #
    # Skipped only when the controller has positively told us there is no amplifier. The
    # check is `not known or music` rather than plain `music`, because an unread or failed
    # configuration leaves every capability False — indistinguishable from a real "no
    # accessories". Erring towards creating it means a missed read costs a sensor reading
    # unknown, not a silently absent entity.
    if coordinator.hub_device is not None:
        # The controller's own copy of the stream-health diagnostic. Same stream as the
        # valve's, deliberately duplicated per device — see `MqttConnectionMixin`.
        entities.append(ControllerMqttConnectionSensor(coordinator))

        capabilities = coordinator.hub_capabilities

        def attached(present: bool) -> bool:
            """Whether to create an accessory entity.

            ``not known or present``, never plain ``present``: an unread or failed
            configuration leaves every capability False, which is indistinguishable from a
            genuine "no accessories". Erring towards creating means a missed read costs a
            sensor reading unknown, not a silently absent entity.
            """
            return not capabilities.known or present

        # Gated on `hub-configuration.parts`, which is the ONLY source of what hardware
        # exists. Message arrival cannot be used: the controller emits STEAM_STS and
        # LIGHT_STS on this system despite `parts` reporting both NotConnected — 10 and 12
        # messages respectively — so subscribing would create entities for hardware nobody
        # owns, permanently reading OFF.
        if attached(capabilities.music):
            entities.append(ControllerMusicSensor(coordinator))
        if attached(capabilities.light):
            entities.append(ControllerLightSensor(coordinator))
        if attached(capabilities.steam):
            entities.append(ControllerSteamSensor(coordinator))

    # Everything derived from SHOWER_VALVE_STS is created on a controller-only account,
    # where it is the only water state there is — and, since 2026-08-18, on a both-devices
    # account too, via EXPOSE_CONTROLLER_WATER_STATE.
    #
    # It does put two contradicting answers on one dashboard during a valve-driven session:
    # the valve reports an open outlet, the controller `status: OFF` with an all-zero array.
    # They are answering different questions and both answers are true. See
    # EXPOSE_CONTROLLER_WATER_STATE for why the second one is worth a row.
    source = resolve_outlet_source(
        coordinator.gcs_device is not None, coordinator.hub_device is not None
    )
    controller_water = source is OutletStateSource.HUB_MQTT or (
        coordinator.hub_device is not None and EXPOSE_CONTROLLER_WATER_STATE
    )
    if controller_water:
        model = coordinator.model
        entities += [
            ControllerOutletSensor(coordinator, zone, outlet)
            for zone in model.zones
            for outlet in range(1, model.outlets_in_zone(zone) + 1)
        ]

    async_add_entities(entities)


class ValveAtTemperatureSensor(KohlerValveEntity, BinarySensorEntity):
    """On once the system reports reaching its temperature setpoint.

    The device's own ``atTemp`` judgement, not a comparison we make — it matches exactly
    when the touchscreen stops flashing and shows a solid setpoint.

    System-level: carried on the primary valve word even when another zone is the one
    delivering water, so it is right regardless of which zone the main shower is plumbed to.
    Expect a brief lag after a setpoint change, mirroring the screen's re-flash.
    """

    _attr_name = "At Temperature"
    _attr_icon = "mdi:thermometer-check"
    # `HEAT` gives the on/off states the labels "Hot"/"Normal" and the matching colour,
    # which reads better on a dashboard than a bare On/Off. The explicit icon is kept so the
    # thermometer survives — a device class supplies its own icon otherwise.
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_at_temperature"

    @property
    def is_on(self) -> bool | None:
        state = self._state
        return None if state is None else state.at_temperature


class ValveDiagnosticBinarySensor(KohlerValveEntity, BinarySensorEntity):
    """Base for valve diagnostics: hidden unless deliberately enabled."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class MqttConnectionMixin:
    """The MQTT-health entity, shared by both devices.

    **One stream serves the whole account**, so the valve's copy and the controller's copy
    always read the same value. That redundancy is deliberate: the connection is what every
    entity on *either* device depends on, and someone looking at the Anthem Plus device page
    should not have to know that the diagnostic lives on the valve. On a controller-only
    account there is no valve page for it to live on at all.

    Mixed in ahead of the device base so these properties win the MRO; the base supplies the
    device binding and the diagnostic category.
    """

    _attr_name = "MQTT Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        stream = self.coordinator.stream
        return None if stream is None else bool(stream.connected)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Stream and credential detail — never any token material.

        Credentials are reported separately from the connection state rather than folded
        into it. A dead stream and a rejected login need different fixes (wait, versus sign
        in again), so collapsing them into one boolean would hide which one happened.
        """
        stream = self.coordinator.stream
        auth = self.coordinator.auth
        expires_at = auth.access_token_expires_at
        attributes: dict[str, object] = {
            "credentials_present": auth.has_credentials,
            "access_token_expires_at": (
                datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
                if expires_at
                else None
            ),
        }
        if stream is not None:
            attributes["warming_up"] = stream.warming_up
            attributes["last_message_at"] = (
                datetime.fromtimestamp(
                    stream.last_message_at, tz=timezone.utc
                ).isoformat()
                if stream.last_message_at
                else None
            )
        return attributes


class MqttConnectionSensor(MqttConnectionMixin, ValveDiagnosticBinarySensor):
    """Whether the MQTT stream that carries all state is alive.

    This is the health signal that matters: with no polling interval, **push is the only
    way state changes reach Home Assistant**. If this is off, every entity is frozen at
    whatever it last saw, and nothing will correct it until the stream returns.

    It replaces an earlier ``Connection`` sensor that reported Kohler's own
    ``connectionState`` — whether the *cloud* considered the *valve* reachable. That was a
    fact about the plumbing, not about this integration, it had no push source so it went
    stale as soon as polling was removed, and a valve dropping off the cloud is fixed in the
    Konnect app rather than here.

    **Caveat: this reflects what the MQTT client believes.** A half-open socket reads
    connected until the 60 s keepalive fails. Pair it with ``sensor.anthem_valve_last_update``
    — a stale timestamp alongside ``connected`` is the signature of a dead-but-unnoticed
    stream.
    """

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_mqtt_connection"


class ControllerDiagnosticBinarySensor(KohlerControllerEntity, BinarySensorEntity):
    """Base for controller diagnostics: hidden unless deliberately enabled."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class ControllerMqttConnectionSensor(
    MqttConnectionMixin, ControllerDiagnosticBinarySensor
):
    """The controller's copy of the MQTT-health diagnostic. See :class:`MqttConnectionMixin`.

    Reports identically to the valve's copy — same stream, same account. Pair it with
    ``sensor.anthem_plus_last_update``: connected alongside a stale timestamp is the
    signature of a half-open socket that has not yet failed its keepalive.
    """

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_mqtt_connection"


class ValveZoneActiveSensor(KohlerValveEntity, BinarySensorEntity):
    """Whether this zone is actually delivering water.

    **"Active" means flowing, which is not the same as "has outlets assigned".** A paused
    valve keeps its assignment in byte 3 — `0x41` is "paused, outlet 1 still assigned" — but
    no water comes out. This reads the same definition the run-time cutoff detector uses:
    a non-empty mask *and* not paused. Anything else would make the two disagree on screen
    about the state one of them is acting on.

    Diagnostic but **enabled by default**, unlike the stream-health sensors: this is the
    clearest view of what the valve is doing, and its `flowing_for_seconds` attribute is the
    number that decides whether a run-time cutoff is imminent.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:water"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_name = f"Zone {zone} Active"
        self._attr_unique_id = f"{self._device_id}_zone_{zone}_active"

    @property
    def _word(self):
        state = self._state
        return None if state is None else state.zone_word(self._zone)

    @property
    def is_on(self) -> bool | None:
        word = self._word
        if word is None:
            return None
        return bool(word.outlet_mask) and not word.paused

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Enough to see *why* it reads as it does, and how close a cutoff is.

        `seconds_remaining` is the useful one during a shower. It is None when the limit is
        unknown, when the zone is idle, or after a reconnect — the detector drops its timings
        across a gap rather than reporting a duration it cannot stand behind, and this shows
        that honestly instead of substituting a zero.
        """
        word = self._word
        if word is None:
            return {}
        model = self.coordinator.model
        base = sum(model.outlets_in_zone(z) for z in model.zones if z < self._zone)
        attributes: dict[str, object] = {
            "outlet_mask": f"0x{word.outlet_mask:02X}",
            # The outlets this zone would resume to — present even while paused, which is
            # exactly when `is_on` is False but the assignment still matters.
            "assigned_outlets": [
                base + bit + 1
                for bit in range(model.outlets_in_zone(self._zone))
                if word.outlet(bit)
            ],
            "paused": word.paused,
        }
        flowing_for = self.coordinator.zone_flowing_for(self._zone)
        attributes["flowing_for_seconds"] = (
            None if flowing_for is None else round(flowing_for, 1)
        )
        limits = self.coordinator.run_time_limits_for_zone(self._zone)
        attributes["run_time_limit_seconds"] = list(limits)
        attributes["seconds_remaining"] = (
            None
            if flowing_for is None or not limits
            else round(min(limits) - flowing_for, 1)
        )
        return attributes


class ValvePresetActiveSensor(KohlerValveEntity, BinarySensorEntity):
    """Whether a stored preset or experience is currently driving the valve.

    From `presetOrExperienceId`, and it answers **"is a preset driving this"** — never "is
    water running". Two consequences worth knowing, both measured:

    * It **latches for the whole session.** Changing temperature, flow, or which outlets are
      open does not clear it, so it stays on even once the shower bears no resemblance to the
      preset as saved.
    * It is cleared by **both pause and stop** — any `0x40` or `00`/`00`.

    Opening an outlet directly leaves this off with water flowing, which is the normal case
    for anything driven from Home Assistant.

    It also has a bearing on the run-time cutoff: a cutoff during a preset-driven session
    pauses *every* zone the preset owns, not only the one that expired.

    **Known false negative: a preset started during warm-up.** The valve applies the preset's
    valve word but never sets `presetOrExperienceId`, so this reads OFF while the preset is
    demonstrably in effect — and it does not correct itself when warm-up ends, because
    warm-up ending pauses the valve and ends the session. All 12 `warmUpInProgress` samples
    in the capture corpus carry a preset id of `0`. This is the device's behaviour, not a
    decode problem, and it is reported rather than papered over: guessing "a preset is
    probably running" from a warm-up flag would be inventing state. Pair it with
    `select.anthem_valve_warmup` and the valve word if the distinction matters. Full evidence in `docs/gcs/api.md`.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Preset Active"
    _attr_icon = "mdi:playlist-star"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_preset_active"

    @property
    def is_on(self) -> bool | None:
        state = self._state
        return None if state is None else state.active_preset_id is not None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self._state
        if state is None:
            return {}
        preset_id = state.active_preset_id
        preset = state.presets.get(preset_id) if preset_id is not None else None
        return {
            "preset_id": preset_id,
            # None rather than a placeholder when the id is one no stored preset matches:
            # ids are slots, and an experience run from the controller shares the id space
            # without appearing in `presets` at all.
            "preset_name": preset.name if preset else None,
        }


class ControllerAccessorySensor(KohlerControllerEntity, BinarySensorEntity):
    """Base for the controller's accessory on/off sensors.

    Each is created only when ``hub-configuration.parts`` reports the hardware attached, and
    each reads a single boolean the controller pushes for that subsystem. Independent of the
    water path — these are the controller's own hardware, reported the same way whatever
    drives the shower, so they are unaffected by the valve-versus-controller split that
    governs the outlet entities.

    All three are on/off only. The controller reports no detail on these channels, and the
    REST equivalents are cached: ``amplifierSettings.monoVolume`` was observed not following
    a live volume change made on the touchscreen, so a volume entity built on it would lie.
    """

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{self._device_id}_{key}"

    @property
    def is_on(self) -> bool | None:
        state = self._state
        return None if state is None else getattr(state, f"{self._key}_on")


class ControllerMusicSensor(ControllerAccessorySensor):
    """Whether the controller's amplifier is playing. From ``MUSIC_STS``.

    The only accessory exercised live on the tested system — 24 clean state transitions in
    the captures. Note ``parts`` reports the amplifier under **``amplifier``**, while the
    ``music`` key is null, so a presence check must look at both.
    """

    _attr_name = "Music"
    _attr_icon = "mdi:music"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator, "music")


class ControllerLightSensor(ControllerAccessorySensor):
    """Whether the controller's lighting is on. From ``LIGHT_STS``.

    **Never exercised** — no lighting is attached to the tested system, and the captured
    ``LIGHT_STS`` messages arrive with an empty ``attributes`` array, so even the parse is
    unverified against a system that has the hardware.
    """

    _attr_name = "Light"
    _attr_icon = "mdi:lightbulb"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator, "light")


class ControllerSteamSensor(ControllerAccessorySensor):
    """Whether the steam generator is running. From ``STEAM_STS``.

    **Never exercised** — no steam is attached to the tested system. The captured messages
    do carry a populated attribute (``status``, ``totaltime``, ``temperature``,
    ``starttime``), so the shape is known even though the ON case has never been seen.
    """

    _attr_name = "Steam"
    _attr_icon = "mdi:hot-tub"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator, "steam")


class ControllerOutletSensor(KohlerControllerEntity, BinarySensorEntity):
    """One outlet within one zone, as the controller reports it.

    **This is the controller's belief, not the plumbing.** It does not observe a
    valve-driven session, so during one it reads OFF with an all-zero array while water is
    running — the **Anthem Valve** outlet sensors are what answer "is water coming out of
    this outlet". What these rows answer instead is "does the controller know", which is
    what decides whether its ``stopall`` and its 60-minute session ceiling apply.

    ``coordinator.hub_water_is_running`` is the any-of over exactly these, and backs both
    Anthem Plus switches, so a switch here can never disagree with the rows beneath it.

    Addressed per zone for the same reason as the valve's switches: the controller's data is
    per zone, and a global numbering needs a model-dependent split that can be got wrong.
    Each zone reports a **6-slot array padded regardless of hardware**, so only the leading
    slots belonging to that zone's valve carry meaning — reading all six would give a
    2-outlet valve six outlets.
    """

    _attr_icon = "mdi:shower-head"

    def __init__(
        self, coordinator: KohlerAnthemPlusCoordinator, zone: int, outlet: int
    ) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._outlet = outlet
        self._attr_name = f"Zone {zone} Outlet {outlet}"
        self._attr_unique_id = f"{self._device_id}_zone_{zone}_outlet_{outlet}"

    @property
    def is_on(self) -> bool | None:
        state = self._state
        if state is None:
            return None
        zone = state.zones.get(self._zone)
        if zone is None:
            return None
        if self._outlet - 1 >= len(zone.outlets):
            return None
        return zone.outlets[self._outlet - 1]
