"""Outlet switches for the Anthem valve.

One switch per outlet, showing state and accepting commands — the same element does both,
like the Konnect app. Because ``is_on`` reads the valve's reported state rather than
remembering what Home Assistant last sent, a switch follows changes from **any** origin:
the app, the physical touchscreen, a preset, or another automation.

Outlets are addressed **per zone**, matching the hardware: a multi-outlet Anthem is
physically two valve bodies joined, and every API surface addresses them separately. That
also removes a whole class of bug — a global "outlet 1-6" numbering has to be split across
zones differently on every model (2+2 on a K-28211, 3+3 on a K-28212), and getting that
split wrong silently operates the wrong outlet.

Turning one on re-sends the complete valve command with that outlet's bit set and every
other outlet in both zones preserved, at whatever the zone's temperature and flow numbers
hold. The valve accepts no partial write.

Switches are **optimistic**: the toggle moves immediately and the reported state corrects it
about a second later when the valve echoes back. Without that, every tap would sit visibly
stuck for the round trip (measured 1.1-2.1 s on real hardware).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.entity import EntityCategory

from .const import (
    CONF_RESTART_ON_RUNTIME_CUTOFF,
    CONF_WARMUP_AUTO_RESTORE,
    DOMAIN,
    ENDLESS_SHOWER_NOT_SET_UP,
    ENDLESS_SHOWER_MATCH_DURATIONS,
    ENDLESS_SHOWER_ON,
    SHOWER_ON_PRESET_ID,
    WARMUP_AUTO_RESTORE_DELAY_SECONDS,
    WARMUP_AUTO_RESTORE_NO_TARGET,
    WARMUP_AUTO_RESTORE_ON,
)
from .coordinator import KohlerAnthemPlusCoordinator, describe_duration
from .entity import KohlerControllerEntity, KohlerValveEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a switch per outlet, per zone, when the account has a valve."""
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []

    if coordinator.gcs_device is not None:
        # An Anthem Plus controller has no per-outlet command: outlets are chosen by
        # activating a favourite, so a controller-only account gets no outlet switches.
        model = coordinator.model
        entities.append(ShowerSwitch(coordinator))
        entities.append(EndlessShowerSwitch(coordinator))
        entities.append(WarmupAutoRestoreSwitch(coordinator))
        entities.extend(
            ZoneOutletSwitch(coordinator, zone, outlet)
            for zone in model.zones
            for outlet in range(1, model.outlets_in_zone(zone) + 1)
        )
    if coordinator.hub_device is not None:
        entities += [HubShowerSwitch(coordinator), HubSystemSwitch(coordinator)]

    async_add_entities(entities)


class ShowerSwitch(KohlerValveEntity, SwitchEntity):
    """Whole-shower stop, as ``switch.anthem_valve_shower``.

    **Off stops the system**, sending mask byte ``0x00`` on both zones while each zone keeps
    its own temperature — see ``async_stop_shower()``.

    It used to *pause* (``0x40``), which showed as "Paused" in the status sensor and reads
    better on a dashboard. That was given up on 2026-08-13 for a concrete reason: **a pause
    is byte-identical to the valve's own run-time cutoff**, which is internally
    ``{preset, action:"Off"}``. With the restart-on-cutoff option on, "Home Assistant stopped
    the shower" and "the valve timed out" were the same event on the wire, separated only by
    a 30 s grace window. Stopping with ``0x00`` makes them different by construction.

    **On activates preset ``SHOWER_ON_PRESET_ID``** — one call, no valve write. The valve has
    no "run my default", so a whole-shower start has to name a stored scene; the preset
    supplies the outlets, temperature, and flow that this entity cannot.

    Which means **what "on" does is stored on the valve, not here.** Edit the preset in the
    Konnect app and this switch starts something different, with no code change — the reason
    the id is a constant rather than a hardcoded literal.
    """

    _attr_icon = "mdi:shower"
    _attr_name = "Shower"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_shower"
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """True while water is actually flowing from any outlet, in either zone."""
        if self._optimistic is not None:
            return self._optimistic
        state = self._state
        if state is None or state.valve1 is None:
            return None
        return state.is_running

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        if state is None or state.valve1 is None:
            return {}
        return {"paused": state.is_paused}

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_command(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_command(False)

    async def _async_command(self, target: bool) -> None:
        """Start the preset, or stop with mask 0x00. Optimistic, like the outlet switches."""
        self._optimistic = target
        self.async_write_ha_state()
        try:
            if target:
                await self.coordinator.async_activate_preset(SHOWER_ON_PRESET_ID)
            else:
                await self.coordinator.async_stop_shower()
        except Exception:
            # The command failed, so stop showing a position the valve never reached.
            self._optimistic = None
            self.async_write_ha_state()
            raise


class EndlessShowerSwitch(KohlerValveEntity, SwitchEntity):
    """Whether to re-open a zone the valve closed on its own run-time limit.

    A switch rather than only a config-flow checkbox, because this is a behaviour someone
    will want to turn on for one shower and off again — and a setting buried behind
    *Configure* is neither visible on the device page nor reachable from an automation or a
    dashboard. As a switch it is all three.

    **What it does when on:** the valve shuts a zone off once it has been running for
    `maximumRunTime` (15 minutes here, per zone rather than per outlet — see
    `anthem_plus/runtime_cutoff.py`); this re-opens the outlets that were running so the
    shower carries on. It therefore **defeats a manufacturer cutoff, with no limit on
    repeats** — water keeps coming back for as long as somebody leaves it running, and the
    hardware stop is the thing being overridden. That is the owner's deliberate choice; see
    `CONF_RESTART_ON_RUNTIME_CUTOFF` in `const.py`. Every restart is logged at WARNING, and
    every decision, including the declines, goes to the cutoff debug log.

    ⚠️ **On an account with BOTH an Anthem valve and an Anthem Plus controller, the two Max
    Shower Durations must be set to the same value.** They are separate timers on separate
    devices and they signal differently — the valve **pauses** (`0x40`), the controller
    **stops** (`0x00`) — and this feature acts on the pause, because that is the only cut it
    can tell apart from somebody deliberately ending their shower. Measured across five case
    studies (`docs/case_studies/`), the valve fires marginally early and the controller
    marginally late, so with equal durations the valve always cuts first and there is always a
    pause to act on. **If the controller's is shorter, it stops the shower and nothing
    restarts it.** The warning is emitted at WARNING when this switch is turned on, but only
    where a controller is present — a valve-only install has nothing to match.

    State lives in the config entry's **options**, the same key the options flow writes, so
    the two always agree and the setting survives a restart. Writing options does not trigger
    a reload — `_async_update_listener` compares `entry.data`, which is untouched — and the
    coordinator reads the flag live, so a toggle takes effect on the next message rather than
    needing a restart.
    """

    _attr_name = "Endless Shower"
    _attr_icon = "mdi:timer-refresh-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_keep_water_running"

    @property
    def available(self) -> bool:
        """A setting, not a reading — usable even before any valve state has arrived."""
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.restart_on_runtime_cutoff

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_RESTART_ON_RUNTIME_CUTOFF: value}
        )
        if value:
            self._log_enabled_state()
        else:
            _LOGGER.info("Endless Shower disabled")
        # Turning it off clears the Repairs card as well as raising it — an unusable feature
        # nobody has switched on is not a problem worth a card.
        self.coordinator.async_refresh_setup_issue()
        self.async_write_ha_state()

    def _log_enabled_state(self) -> None:
        """Say plainly, at switch-on, whether this can actually do anything yet.

        Turning it on is not enough: a zone also needs a `maximumRunTime` from at least one
        of its outlets, which arrives only on an unprompted `READ_GCS_OUTLET_CONFIG_CFG` and
        cannot be requested. Until then the switch reads "on" while the feature is inert — a
        silent no-op that is indistinguishable from a broken one, and the exact thing that
        made an early test of this look like nothing was happening.

        Reported by zone, because that is what the valve times, with the outlet detail kept
        alongside since that is the form the valve announces it in.
        """
        waiting = self.coordinator.zones_awaiting_run_time
        known = self.coordinator.outlet_run_times

        if not known:
            _LOGGER.warning(ENDLESS_SHOWER_NOT_SET_UP)
            return

        if waiting:
            # Partly armed is reported the same way as not armed at all: from the owner's
            # side the situation and the remedy are identical, and naming the zones that
            # did report would only invite trusting a half-armed feature.
            _LOGGER.warning(ENDLESS_SHOWER_NOT_SET_UP)
            return

        _LOGGER.warning(ENDLESS_SHOWER_ON, describe_duration(known))

        # Both products on one account means two independent maximum-duration timers, and
        # Endless Shower can only act on the valve's. Say so at the moment the feature is
        # switched on, when the owner can still go and match them. Valve-only installs have
        # nothing to match, so they are not told to.
        if self.coordinator.hub_device is not None:
            _LOGGER.warning(ENDLESS_SHOWER_MATCH_DURATIONS, describe_duration(known))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Readiness, visible without going to the log.

        `armed_zones` empty while the switch is on means the feature is on but inert — the
        zone is the unit that matters, since the valve's timer is per zone.
        """
        known = self.coordinator.outlet_run_times
        return {
            "armed_zones": self.coordinator.armed_zones,
            "awaiting_run_time_limit_zones": self.coordinator.zones_awaiting_run_time,
            "armed_outlets": sorted(known),
            "run_time_limits_seconds": {str(k): v for k, v in sorted(known.items())},
            "awaiting_run_time_limit": self.coordinator.outlets_awaiting_run_time,
        }


class WarmupAutoRestoreSwitch(KohlerValveEntity, SwitchEntity):
    """Put the warmup mode back when something outside Home Assistant turns it off.

    **The problem this exists for.** The valve's warmup mode does not stay where it is put:
    the Anthem Plus hub writes it back to `warmUpDisabled` on every signed-in use of its web
    UI — a constant in the hub's login/UI routine, solved 2026-08-21 after six live
    reproductions in a day. Nothing reachable from outside the hub's firmware prevents it,
    so putting the mode back is the fix that exists. See `docs/gcs/api.md` §3h.

    **What this does.** When warmup goes to `warmUpDisabled` and this integration did not
    cause it — announced by the valve over MQTT, or discovered by the reconnect reseed after
    an MQTT outage (a hub sign-in during one causes exactly that; the reseed path acts since
    2026-08-22) — wait 60 seconds, re-check that it is still disabled, and set the mode back
    to the last enabled one seen on the valve. That target is remembered in the entry
    options, so it survives a restart and reinstates what the fixture actually had — never a
    default, because "all outlets" and "selected outlets" are different fixtures' worth of
    water. With no remembered mode it does nothing and says so.

    ⚠️ **This treats a symptom.** It cannot stop the hub's routine writing the field — that
    is hub firmware — and a restore is a write to Kohler's cloud like any other. It is off by
    default because only installs whose hub web UI gets used ever see the disable; turn it on
    when the reverting is actually bothering you.

    Three things it deliberately will not do:

    * **Undo you.** Choosing `Off` on the Warmup dropdown is a write this integration made,
      and a disable it caused is recognised and ignored. Otherwise `Off` would be unusable.
    * **Fight forever.** If the mode is disabled again after each restore, it stops after five
      consecutive attempts and logs why. A retry loop against something actively rewriting the
      field is not a fix, it is just traffic.
    * **Interrupt a shower.** The write is refused while water is running, mirroring the
      Konnect app. The next disable schedules another attempt.

    State lives in the config entry's options, read live by the coordinator, so a toggle takes
    effect on the next message rather than needing a restart.
    """

    _attr_name = "Warmup Auto-Restore"
    _attr_icon = "mdi:restore-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Off unless someone goes looking for it: this is a workaround for a device fault, not a
    # feature of the shower, and an owner who has never seen the mode revert does not need it.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_warmup_auto_restore"

    @property
    def available(self) -> bool:
        """A setting, not a reading — usable before any valve state has arrived."""
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.warmup_auto_restore

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What it would restore to, and how long it waits."""
        return {
            "restores_to": self.coordinator.last_warmup_mode,
            "delay_seconds": WARMUP_AUTO_RESTORE_DELAY_SECONDS,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        entry = self.coordinator.entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_WARMUP_AUTO_RESTORE: value}
        )
        if not value:
            _LOGGER.info("Warmup Auto-Restore disabled")
        elif self.coordinator.last_warmup_mode is None:
            # On but inert, which is indistinguishable from broken unless it says so — the
            # same failure mode Endless Shower's readiness logging exists to prevent.
            _LOGGER.warning(WARMUP_AUTO_RESTORE_NO_TARGET)
        else:
            _LOGGER.warning(
                WARMUP_AUTO_RESTORE_ON,
                self.coordinator.last_warmup_mode,
                WARMUP_AUTO_RESTORE_DELAY_SECONDS,
            )
        self.async_write_ha_state()


class ZoneOutletSwitch(KohlerValveEntity, SwitchEntity):
    """One outlet within one zone, readable and controllable.

    Entity id is ``switch.anthem_valve_zone_<z>_outlet_<n>``: Home Assistant composes it
    from the device name ("Anthem Valve") and the entity name ("Zone z Outlet n").
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
        # Holds the requested position until the valve reports back. None means "no
        # pending command — show what the valve says".
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic is not None:
            return self._optimistic
        state = self._state
        if state is None or state.zone_word(self._zone) is None:
            return None
        return state.zone_outlets(self._zone)[self._outlet - 1]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The assignment a paused session will resume to.

        A paused valve keeps its outlet bits set while no water flows, so ``is_on`` is off
        and this stays on — the difference between "not running" and "not selected".
        """
        state = self._state
        if state is None or state.zone_word(self._zone) is None:
            return {}
        assigned = state.zone_outlets(self._zone, flowing=False)
        return {"assigned": assigned[self._outlet - 1]}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Real state has arrived, so the optimistic guess is no longer needed."""
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, target: bool) -> None:
        self._optimistic = target
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_zone_outlet(
                self._zone, self._outlet, target
            )
        except Exception:
            # The command failed, so stop showing the position we never reached.
            self._optimistic = None
            self.async_write_ha_state()
            raise


class HubShowerSwitch(KohlerControllerEntity, SwitchEntity):
    """The controller's own shower, via ``valvecontrol {valveOnOff}``.

    **The only bare on/off in the whole system.** It works because the controller stores its
    own default water configuration, so "on" has a meaning without naming a scene. The GCS
    valve has no equivalent — every start there must specify the complete valve state, which
    is why the valve's shower switch activates a preset instead.

    Off stops **water only**, leaving music, steam, and lighting untouched. For a true
    system-wide stop use the System switch, which calls ``stopall``.

    ``is_on`` follows reported state rather than what we last sent, so a shower started from
    the touchscreen or the app shows up here too.

    **It reports the controller's view only — never the valve's.** A shower driven straight
    at the valve through ``solowritesystem`` — which is every shower Home Assistant starts —
    reaches this switch only if the controller happens to register it, which is unreliable
    (51 of 95 immediately, 12 late, 32 never; preset-driven ones never). That is the
    intended reading, not a gap: the switch shows what the controller knows, and its own
    ``valvecontrol OFF`` can only stop a session the controller is party to. For whether
    water is physically running, read the **Anthem Valve** device's Shower switch and outlet
    sensors, which are authoritative.

    See ``coordinator.hub_water_is_running`` for the 2026-08-18 measurement that made this
    the rule.
    """

    _attr_name = "Shower"
    _attr_icon = "mdi:shower"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_shower"
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic is not None:
            return self._optimistic
        return self.coordinator.hub_water_is_running

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, target: bool) -> None:
        self._optimistic = target
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_hub_shower(target)
        except Exception:
            self._optimistic = None
            self.async_write_ha_state()
            raise


class HubSystemSwitch(KohlerControllerEntity, SwitchEntity):
    """Is anything running **that the controller knows about**, and the one control that
    stops all of it.

    ``is_on`` is true when **any** subsystem is active — water, music, steam, or lighting —
    so it answers "is the shower room doing something" in a single row, with an attribute
    breakdown naming which. Off calls ``stopall``, the only command that idles everything.

    **All four subsystems are the controller's own view, water included.** A shower driven
    at the valve through ``solowritesystem`` is invisible here, because it is invisible to
    the controller — and ``stopall``, this switch's off action, would not stop it either.
    Scoping the switch to what its own off action can reach is the point: it stays honest
    about both. The **Anthem Valve** device owns the question "is water running".

    **The two directions are deliberately asymmetric, and this is the honest part.** There is
    no "start everything" concept: the controller cannot turn on music and steam and water
    from one command, and inventing a meaning would be guesswork. So turning it **on** runs
    the controller's default shower (``valvecontrol ON``) — the nearest thing to "on" the
    hardware offers — while turning it **off** stops every subsystem.

    If that asymmetry is unwanted, the alternative is a read-only binary sensor plus a
    separate stop button. That is arguably cleaner but costs two dashboard rows for what is
    usually one glance and one tap.
    """

    _attr_name = "System"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_system"
        self._optimistic: bool | None = None

    @property
    def _subsystems(self) -> dict[str, bool | None]:
        state = self._state
        if state is None:
            return {}
        return {
            # The controller's own outlet arrays, deliberately — not the valve's. Reading
            # the valve here made this switch report sessions the controller had never been
            # told about; see `coordinator.hub_water_is_running`.
            "water": self.coordinator.hub_water_is_running,
            "music": state.music_on,
            "steam": state.steam_on,
            "light": state.light_on,
        }

    @property
    def is_on(self) -> bool | None:
        if self._optimistic is not None:
            return self._optimistic
        subsystems = self._subsystems
        if not subsystems:
            return None
        return any(bool(v) for v in subsystems.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which subsystems are on, so "System: on" is never a mystery.

        Accessories the controller does not have report ``None`` rather than ``False``: it
        emits STEAM_STS and LIGHT_STS even for hardware that is not installed, so a flat
        False would imply a steam generator that is merely idle.
        """
        return dict(self._subsystems)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Water only — see the class docstring on why "on" cannot mean everything.
        await self._async_set(True, self.coordinator.async_set_hub_shower(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False, self.coordinator.async_stop_hub())

    async def _async_set(self, target: bool, action) -> None:
        self._optimistic = target
        self.async_write_ha_state()
        try:
            await action
        except Exception:
            self._optimistic = None
            self.async_write_ha_state()
            raise
