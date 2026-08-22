"""Coordinator: holds the MQTT stream, the REST client, and per-device state.

State is **push-only**. MQTT carries every change as it happens and there is no polling
interval at all — REST is read on events, never on a clock.

Three things this has to get right:

* **Cold start.** MQTT is event-driven and silent until the shower next changes, so a
  restart would leave every entity unknown. One REST read at setup seeds everything.
* **Reconnects.** The broker replays nothing on connect: measured across 27 sessions, the
  first message is always a change event and six sessions received nothing for hours. So
  every connect re-seeds, which is what makes dropping the poll safe.
* **Token rotation.** B2C issues a new refresh token on every refresh and invalidates the
  old one. Losing it strands the account, so it is written back to the config entry
  whenever it changes.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .anthem_plus import (
    AnthemMqttStream,
    AuthError,
    AuthUnavailable,
    Device,
    DeviceOffline,
    Envelope,
    GcsDevice,
    GcsState,
    HubCapabilities,
    HubDevice,
    HubState,
    KohlerAuth,
    KohlerClient,
    KohlerError,
    CutoffDebugLog,
    WARMUP_README,
    RawMqttLog,
    ZoneCutoff,
    ZoneCutoffDetector,
    ZoneReading,
    MSG_GCS_SOLO_STATUS,
    MSG_GCS_WARMUP_STATUS,
    WARMUP_DISABLED,
    WARMUP_MODES_CURRENT,
    journal_event,
    restore_target,
    should_restore_warmup,
    get_valve_model,
    model_for_topology,
    unit_to_celsius,
)
from .anthem_plus.entry_reload import reload_signature
from .anthem_plus.state import outlet_limits_from_settings
from .anthem_plus.valve_hex import (
    UNUSED_VALVE_WORD,
    VALVE1_PREFIX,
    VALVE2_PREFIX,
    VALVE_STOP_MASK,
    ValveHexError,
    decode_word,
    encode_word,
    normalize_word,
)
from .const import (
    CONF_MOBILE_DEVICE_ID,
    CONF_OUTLET_RUN_TIMES,
    CONF_REFRESH_TOKEN,
    CONF_RESTART_ON_RUNTIME_CUTOFF,
    CONF_TEMPERATURE_UNIT,
    CONF_TENANT_ID,
    CONF_VALVE_MODEL,
    CONF_ZONE_OUTLETS,
    CUTOFF_DEBUG_LOG_KEEP_FILES,
    ENABLE_WARMUP_DEBUG_LOG,
    WARMUP_CONTEXT_AFTER_SECONDS,
    WARMUP_CONTEXT_BEFORE_SECONDS,
    WARMUP_CONTEXT_MAX_MESSAGES,
    WARMUP_DEBUG_LOG_KEEP_FILES,
    DEFAULT_FLOW_PERCENT,
    DEFAULT_PRESET_ID,
    DEFAULT_PRESET_TIMER_SECONDS,
    DOMAIN,
    ENABLE_CUTOFF_DEBUG_LOG,
    ENABLE_RAW_MQTT_LOG,
    RAW_MQTT_LOG_DIR,
    RAW_MQTT_LOG_KEEP_FILES,
    RAW_MQTT_LOG_MAX_BYTES,
    RELOAD_IGNORED_DATA_KEYS,
    ENDLESS_SHOWER_MATCH_DURATIONS,
    ENDLESS_SHOWER_NOT_SET_UP,
    ENDLESS_SHOWER_NOTHING_TO_RESTORE,
    ENDLESS_SHOWER_ON,
    CONF_LAST_WARMUP_MODE,
    CONF_WARMUP_AUTO_RESTORE,
    WARMUP_AUTO_RESTORE_DELAY_SECONDS,
    WARMUP_AUTO_RESTORE_GIVING_UP,
    WARMUP_AUTO_RESTORE_MAX_CONSECUTIVE,
    WARMUP_AUTO_RESTORE_NO_TARGET,
    WARMUP_AUTO_RESTORE_SETTLED_SECONDS,
    WARMUP_READBACK_DELAYS,
    WARMUP_SELF_WRITE_GRACE_SECONDS,
    ENDLESS_SHOWER_RESTARTED,
    ISSUE_NOT_SET_UP,
    RELOAD_IGNORED_OPTION_KEYS,
    SCAN_INTERVAL,
    SYNC_DEFAULT_PRESET_TIMER,
)

_LOGGER = logging.getLogger(__name__)


def entry_reload_signature(entry: ConfigEntry) -> tuple[Any, ...]:
    """Fingerprint the parts of a config entry that are worth a reload.

    Shared by the coordinator, which takes one at setup, and `_async_update_listener` in
    `__init__.py`, which takes one per update and compares. Both must apply the same
    exclusions or the comparison means nothing, so there is one call site for the pair of
    key sets rather than two that can drift.
    """
    return reload_signature(
        entry.data,
        entry.options,
        ignore_data=RELOAD_IGNORED_DATA_KEYS,
        ignore_options=RELOAD_IGNORED_OPTION_KEYS,
    )


def describe_zones(zones: list[int]) -> str:
    """Name a set of zones the way the owner's hardware actually looks.

    A two-zone K-28212 has zones worth naming; a single-zone K-28209/K-28210 has exactly one
    and "zone(s) 1" reads like a template nobody finished. Shared with `switch.py` so both
    log paths phrase it identically.
    """
    if not zones:
        return "no zones"
    if len(zones) == 1:
        return f"zone {zones[0]}"
    return f"zones {', '.join(str(zone) for zone in zones)}"


def describe_duration(run_times: dict[int, int]) -> str:
    """Max Shower Duration in minutes, the way the Konnect app states it.

    Reads outlet 1 — zone 1's first outlet — because the app presents one duration for the
    whole system and every install seen has all outlets on the same value. Falls back to the
    lowest-numbered outlet that has reported, so a partly-learned valve still names a real
    number instead of nothing.
    """
    if not run_times:
        return "?"
    seconds = run_times.get(1) or run_times[min(run_times)]
    return f"{seconds / 60:g}"


def _command_half(value: str, field: str) -> str:
    """Validate a user-supplied valve word, accepting either length the system shows.

    `normalize_word` truncates to the first 8 characters, which is right for device data —
    the valve reports 16-character words whose second half is sensor feedback. But it means
    a 10-character typo silently becomes a valid, *different* command, and this input reaches
    something that opens water valves.

    So the length is checked first, and only the two lengths a person could legitimately have
    are allowed: **8** (a command word) or **16** (what `sensor.anthem_valve_zone_N_hex`
    displays, so it can be pasted straight in). Anything else is a mistake, not a shorthand.
    """
    text = str(value or "").strip()
    if len(text) not in (8, 16):
        raise HomeAssistantError(
            f"{field}: expected 8 characters (a command word) or 16 (as shown by the "
            f"Zone Hex sensor), got {len(text)}: {value!r}"
        )
    try:
        return normalize_word(text)
    except ValveHexError as err:
        raise HomeAssistantError(f"{field}: {err}") from err


def _describe_word(word: str) -> str:
    """Plain-language reading of a command word, for logs and service responses.

    Deliberately tolerant: this only ever annotates something that has already been
    validated and is about to be sent, so a decode failure must not block the write.
    """
    try:
        decoded = decode_word(word)
    except ValveHexError:
        return "undecodable"
    if word == UNUSED_VALVE_WORD:
        return "unused / closed"
    open_outlets = [
        str(index + 1) for index in range(3) if decoded.outlet_mask >> index & 1
    ]
    return (
        f"{decoded.temperature_celsius:.1f}C, {decoded.flow_percent:.0f}% flow, "
        f"outlets {','.join(open_outlets) or 'none'}"
        f"{', paused' if decoded.paused else ''}"
    )


def credential_is_dead(err: Exception) -> bool:
    """True when `err` means the stored credential was rejected, not that Kohler was down.

    The distinction decides whether to prompt the user, so getting it wrong is expensive in
    both directions: prompt on a network blip and reauth cards appear whenever the WAN
    flaps; miss a real rejection and the entry sits silently dead. `AuthUnavailable` is the
    only `AuthError` raised without Kohler having actually rejected anything, and
    `KohlerError` is not an auth failure at all.
    """
    return isinstance(err, AuthError) and not isinstance(err, AuthUnavailable)


class KohlerAnthemPlusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Owns the connection and the per-device state objects."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        # `config_entry` must be passed on modern Home Assistant: without it
        # `async_config_entry_first_refresh()` refuses to run. Older releases do not accept
        # the keyword at all, so fall back rather than hard-failing on them.
        # `update_interval=SCAN_INTERVAL` disables interval polling entirely. State is
        # push-only: MQTT carries every change, and the REST reads happen on two *events* —
        # setup, and every MQTT (re)connect — rather than on a clock.
        #
        # ⚠️ **That was one event short of the truth until 2026-08-21.**
        # `async_config_entry_first_refresh()` runs immediately after `async_setup()` and the
        # base class turns it into a third read of everything. `_async_update_data` now
        # short-circuits that one, so the sentence above is enforced rather than merely
        # intended — see the comment there before removing it.
        #
        # `_async_update_data()` still exists and still works; with no interval it runs only
        # when something asks, which is what `homeassistant.update_entity` does. That is the
        # manual refresh, and there is no automatic one.
        try:
            super().__init__(
                hass,
                _LOGGER,
                name=DOMAIN,
                update_interval=SCAN_INTERVAL,
                config_entry=entry,
            )
        except TypeError:
            super().__init__(
                hass,
                _LOGGER,
                name=DOMAIN,
                update_interval=SCAN_INTERVAL,
            )
        # Kept under our own name rather than relying on the base class's `config_entry`,
        # whose presence varies by release.
        self.entry = entry
        # The entry as it looked when this coordinator was built, frozen. Home Assistant
        # mutates the `ConfigEntry` object in place, so `self.entry` is a live view and
        # cannot serve as a "before" — comparing it against the entry compares an object
        # with itself. `_async_update_listener` compares against this instead.
        self.reload_signature = entry_reload_signature(entry)
        # The stored split wins over the SKU: an install that matches no catalogue model
        # still reloads correctly, and a SKU label can never silently change topology.
        stored = entry.data.get(CONF_ZONE_OUTLETS)
        if isinstance(stored, (list, tuple)) and len(stored) == 2:
            self.model = model_for_topology(int(stored[0]), int(stored[1]))
        else:
            self.model = get_valve_model(entry.data[CONF_VALVE_MODEL])
        self.temperature_unit: str = entry.data.get(CONF_TEMPERATURE_UNIT, "Fahrenheit")

        session = async_get_clientsession(hass)
        self.auth = KohlerAuth(session, entry.data.get(CONF_REFRESH_TOKEN))
        self.client = KohlerClient(session, self.auth, entry.data.get(CONF_TENANT_ID))

        self.gcs_device: Device | None = None
        self.hub_device: Device | None = None
        self.gcs: GcsDevice | None = None
        self.hub: HubDevice | None = None
        self.gcs_state: GcsState | None = None
        # Warmup auto-restore bookkeeping. `_warmup_self_write_*` is the same idea as
        # `ZoneCutoffDetector.note_local_write`: a change we caused must not be treated
        # as the device misbehaving, or turning warmup off from the dropdown would be
        # undone a minute later.
        self._warmup_self_write_at: float | None = None
        self._warmup_self_write_mode: str | None = None
        self._warmup_restore_task: asyncio.Task | None = None
        self._warmup_restores = 0
        self._warmup_restored_at: float | None = None
        self.hub_state: HubState | None = None
        self.hub_capabilities = HubCapabilities()
        self.favorites: list[dict[str, Any]] = []
        self.stream: AnthemMqttStream | None = None
        self.raw_log: RawMqttLog | None = None
        # One-shot: `async_setup` seeds, then `async_config_entry_first_refresh()` runs
        # milliseconds later and would seed the identical state all over again. See
        # `_async_update_data`.
        self._seeded_during_setup = False
        # The raw `gcs-preset` payload from the most recent seed, held only long enough for
        # `_async_sync_default_preset_timer` to consume it on the next line of `async_setup`.
        # Cleared on use — it feeds a write path, and a stale payload is a silent edit.
        self._seeded_presets: Any = None
        # CUTOFF DEBUG LOG: built in `async_setup`, once `hass.config.path` is usable.
        self.cutoff_log: CutoffDebugLog | None = None
        self.warmup_log: CutoffDebugLog | None = None
        # Rolling record of recent messages, so a warmup disable can be journalled
        # with what surrounded it. Bounded by count and trimmed by age on read.
        self._recent_messages: deque = deque(maxlen=WARMUP_CONTEXT_MAX_MESSAGES)
        # Tracks how long each zone has been flowing, so a valve-timer close can be told from
        # a real stop. Always fed, even with the option off — the cost is a dict update per
        # message, and it means enabling the option takes effect immediately rather than from
        # the next time the shower happens to start.
        self._cutoff = ZoneCutoffDetector()
        # Last outlet masks seen with water actually running. The valve wipes every mask at
        # a run-time cutoff, so this is the only record of what to restore.
        self._last_open_masks: dict[int, int] | None = None
        # Same idea, for flow. Exists for the zone a preset-off pauses *alongside* the one
        # that actually hit its limit — `ZoneCutoff.reading` only ever covers the zone whose
        # own duration matched, so without this the co-paused zone has no flow source and
        # falls back to `DEFAULT_FLOW_PERCENT` on restore. See `_remember_open_masks`.
        self._last_open_flows: dict[int, float] | None = None
        # Per-outlet `maximumRunTime`, keyed by the device's own 0-based `outLetId`.
        # Restored from the config entry so the cutoff feature works from the first second
        # after a restart — see `CONF_OUTLET_RUN_TIMES` for why it has to be remembered.
        self._run_times: dict[int, int] = {
            int(key): int(value)
            for key, value in (entry.data.get(CONF_OUTLET_RUN_TIMES) or {}).items()
        }

    # ------------------------------------------------------------------ #
    # Setup / teardown
    # ------------------------------------------------------------------ #
    async def async_setup(self) -> None:
        """Discover devices, seed state from REST, then start the MQTT stream."""
        try:
            customer = await self.client.async_get_customer()
        except AuthUnavailable as err:
            # Kohler unreachable, not a bad credential — retry setup, do not ask the user
            # to sign in again.
            raise ConfigEntryNotReady(f"Cannot reach Kohler: {err}") from err
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except KohlerError as err:
            raise ConfigEntryNotReady(f"Cannot reach Kohler: {err}") from err

        self.temperature_unit = customer.temperature_unit or self.temperature_unit
        self.gcs_device = next(iter(customer.gcs_devices), None)
        self.hub_device = next(iter(customer.hub_devices), None)
        if self.gcs_device is None and self.hub_device is None:
            raise ConfigEntryNotReady("No Anthem devices on this account")

        if self.gcs_device is not None:
            self.gcs = GcsDevice(
                self.client,
                self.gcs_device.device_id,
                self.temperature_unit,
                self.model,
            )
            self.gcs_state = GcsState(self.model, self.temperature_unit)
        if self.hub_device is not None:
            self.hub = HubDevice(
                self.client, self.hub_device.device_id, self.temperature_unit
            )
            self.hub_state = HubState(self.model)

        try:
            await self._async_seed_state()
        except AuthUnavailable as err:
            # Same split as the customer read above. The seed swallows `KohlerError` per
            # read ("failures for one device do not blank the other"), but the token layer
            # under every read raises `AuthError`, which is not a `KohlerError` — left bare,
            # a rejection here escaped `async_setup_entry` as an unhandled exception: no
            # reauth prompt, no retry, an entry stuck on "Failed to set up". Found 2026-08-21
            # while proving the startup-read fold; fixed 2026-08-22.
            raise ConfigEntryNotReady(f"Cannot reach Kohler: {err}") from err
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        # `async_config_entry_first_refresh()` follows immediately in `async_setup_entry` and
        # would repeat every read above for nothing. Claimed here, spent in
        # `_async_update_data`.
        self._seeded_during_setup = True
        await self._async_sync_default_preset_timer()
        self._persist_refresh_token()

        # One identity for the life of this config entry. Generated on first setup and
        # persisted, so restarts and reconnects reuse it instead of leaving a trail of
        # dead registrations on the Kohler account.
        mobile_device_id = self.entry.data.get(CONF_MOBILE_DEVICE_ID)
        first_registration = not mobile_device_id
        if first_registration:
            mobile_device_id = uuid.uuid4().hex[:16]
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_MOBILE_DEVICE_ID: mobile_device_id},
            )

        # RAW MQTT LOG: constructed unconditionally and switched on at runtime, so capture
        # can be started from the UI mid-session without a reload. Nothing touches the disk
        # until a message arrives while it is on. See `anthem_plus/raw_log.py`.
        self.raw_log = RawMqttLog(
            self.hass.config.path(RAW_MQTT_LOG_DIR),
            forced=ENABLE_RAW_MQTT_LOG,
            max_bytes=RAW_MQTT_LOG_MAX_BYTES,
            keep_files=RAW_MQTT_LOG_KEEP_FILES,
        )
        # Open the file up front when capture is already on, so it is findable immediately
        # rather than after the next push — which can be hours away. Executor, not the loop:
        # this creates a directory and opens a file.
        await self.hass.async_add_executor_job(self.raw_log.prepare)

        # CUTOFF DEBUG LOG: same directory as the raw capture on purpose — the two are read
        # together, joined on `ts`. See `anthem_plus/cutoff_log.py`.
        self.cutoff_log = CutoffDebugLog(
            self.hass.config.path(RAW_MQTT_LOG_DIR),
            forced=ENABLE_CUTOFF_DEBUG_LOG,
            keep_files=CUTOFF_DEBUG_LOG_KEEP_FILES,
        )
        self._cutoff.journal = self.cutoff_log
        await self.hass.async_add_executor_job(self.cutoff_log.prepare)

        # WARMUP JOURNAL: a second journal in the same directory, on the same clock, for a
        # different open question — see `WARMUP_README`. Separate from the cutoff log because
        # the two are read for different reasons and `pause_resolution.py` and friends glob
        # `cutoff_*.jsonl`; mixing warmup records into that corpus would silently change what
        # those tools count.
        self.warmup_log = CutoffDebugLog(
            self.hass.config.path(RAW_MQTT_LOG_DIR),
            forced=ENABLE_WARMUP_DEBUG_LOG,
            keep_files=WARMUP_DEBUG_LOG_KEEP_FILES,
            prefix="warmup",
            readme=WARMUP_README,
            readme_fields={
                "before": int(WARMUP_CONTEXT_BEFORE_SECONDS),
                "after": int(WARMUP_CONTEXT_AFTER_SECONDS),
            },
            label="Warmup journal",
        )
        await self.hass.async_add_executor_job(self.warmup_log.prepare)
        # BASELINE: what mode was in force when this file opened, from the REST seed above.
        #
        # Without it a journal is unreadable on its own. **The valve never volunteers its
        # warmup mode on connect** — measured 2026-08-21 over all 74 raw captures: 17 hold a
        # `GCS_WARM_STS` at all, and in 16 the first one lands between 137 s and 7 h after
        # the log opened. The 17th, at +1.7 s, only looks like a connect announcement: it is
        # the echo of our own write on 08-21 at 03:40:10Z, which landed in a file that had
        # opened 1.7 s earlier *because* persisting the mode reloaded the entry — the bug
        # `cde9bf4` fixed, so that artefact cannot recur.
        #
        # So a file that records a `disabled` an hour in has no record of what was displaced
        # or since when, and an empty file cannot be told apart from a broken one.
        #
        # Written here rather than in `_async_seed_state` because the first seed runs before
        # this log exists, and this is the one place that happens exactly once per file.
        self._warmup_journal(
            "baseline",
            mode=None if self.gcs_state is None else self.gcs_state.warmup_mode,
            auto_restore=self.warmup_auto_restore,
            restores_to=self.last_warmup_mode,
            source="rest",
        )

        self.stream = AnthemMqttStream(
            self.client,
            self._handle_envelope,
            on_connect=self._handle_connected,
            on_auth_error=self._handle_auth_error,
            mobile_device_id=mobile_device_id,
            raw_log=self.raw_log,
            # Only a brand-new identity can plausibly need provisioning time. A reused one
            # has connected before, so silence from it is real silence.
            expect_warmup=first_registration,
        )
        try:
            await self.stream.async_start()
        except (AuthError, KohlerError) as err:
            # State is already seeded, so the integration is usable but frozen until the
            # stream recovers. A warning rather than a setup failure — the reconnect loop
            # keeps trying, and each success re-seeds.
            _LOGGER.warning("Kohler MQTT stream did not start: %s", err)
            if credential_is_dead(err):
                self._handle_auth_error(err)

        # Say at startup whether the cutoff feature can act. The switch keeps its state
        # across restarts, so without this the only warning would be the one printed when
        # somebody last toggled it — possibly weeks ago, on a different set of known limits.
        self._journal(
            "arm",
            enabled=self.restart_on_runtime_cutoff,
            run_times=self.outlet_run_times,
            awaiting=self.outlets_awaiting_run_time,
            zone_limits={z: list(v) for z, v in self._zone_limits().items()},
        )
        if self.restart_on_runtime_cutoff:
            if self._run_times:
                # Stated positively on every start, at WARNING so it shows under default
                # logging. Silence is ambiguous — "armed" and "the feature quietly stopped
                # working" look identical from the log — and this is a feature that can
                # restart water with nobody present, so it should announce itself.
                _LOGGER.warning(
                    ENDLESS_SHOWER_ON, describe_duration(self.outlet_run_times)
                )
                # Both products on one account means two independent maximum-duration
                # timers, and Endless Shower can only act on the valve's. Repeated here on
                # every start for exactly the reason ENDLESS_SHOWER_ON is: the switch
                # survives restarts, so `switch.py`'s copy of this warning may have been
                # printed weeks ago and scrolled away. Until 2026-08-19 this was emitted
                # only at toggle time, which left the mismatch invisible on every start
                # after the first.
                #
                # What a mismatch costs, measured: `docs/case_studies/07_the_controller_
                # sweeps.md`. Seven controller cutoffs ended showers that did not come back,
                # and nothing in the log said why.
                if self.hub_device is not None:
                    _LOGGER.warning(
                        ENDLESS_SHOWER_MATCH_DURATIONS,
                        describe_duration(self.outlet_run_times),
                    )
            else:
                _LOGGER.warning(ENDLESS_SHOWER_NOT_SET_UP)
        self.async_refresh_setup_issue()

    @callback
    def async_refresh_setup_issue(self) -> None:
        """Raise or clear the Repairs card for an Endless Shower that cannot act.

        Called wherever either half of the condition can change: at setup, when the valve
        announces a limit, and when the switch is toggled. Idempotent — Home Assistant keeps
        one issue per id, so re-creating an existing one is a no-op and deleting a missing
        one is too.

        The condition is `zones_awaiting_run_time`, not "nothing known at all", so a valve
        that has reported one zone but not the other still raises it. Half-armed is not armed
        for the zone that has no limit, and that is exactly the silent case worth surfacing.
        """
        issue_id = f"{ISSUE_NOT_SET_UP}_{self.entry.entry_id}"
        if self.restart_on_runtime_cutoff and self.zones_awaiting_run_time:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_NOT_SET_UP,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def _handle_auth_error(self, err: Exception) -> None:
        """Surface a rejected credential as a reauth prompt.

        Push-only removed the last thing that ran on a clock, and with it the only path that
        regularly reached ``ConfigEntryAuthFailed``. `_async_update_data` still raises it,
        but with ``SCAN_INTERVAL = None`` it fires only on a manual
        ``homeassistant.update_entity``. So without this, an expired or revoked refresh
        token leaves the entry looking healthy — MQTT down, entities frozen at their last
        values rather than unavailable, and no prompt anywhere — while the reconnect loop
        retries forever against a credential that will never be accepted.

        `async_start_reauth` is idempotent; the stream also latches, so repeated failures
        do not stack up flows.
        """
        _LOGGER.error(
            "Kohler rejected the stored credential (%s); reauthentication required", err
        )
        self.entry.async_start_reauth(self.hass)

    @property
    def outlet_run_times(self) -> dict[int, int]:
        """Learned `maximumRunTime` per outlet, keyed by **1-based** outlet number.

        Empty until the valve announces, which it does unprompted and one outlet at a time.
        An outlet missing from here cannot be restarted after a cutoff — there is nothing to
        compare its run length against — so callers that report readiness must consult this
        rather than assuming the feature is live.
        """
        return {outlet_id + 1: seconds for outlet_id, seconds in self._run_times.items()}

    @property
    def armed_zones(self) -> list[int]:
        """Zones the cutoff feature can actually act on.

        The unit that matters, since the valve times per zone: a zone is armed as soon as
        *any* of its outlets has reported a `maximumRunTime`, because that is enough to have
        something to compare the zone's flow duration against. Outlet-level readiness is
        still reported alongside — it is what the valve announces — but a zone with one
        known outlet is protected, not half-protected.
        """
        return [zone for zone, limits in self._zone_limits().items() if limits]

    @property
    def zones_awaiting_run_time(self) -> list[int]:
        """Zones where no outlet has reported a limit yet. Empty means fully armed."""
        return [zone for zone, limits in self._zone_limits().items() if not limits]

    @property
    def outlets_awaiting_run_time(self) -> list[int]:
        """Outlets with no known limit yet, 1-based. Empty means every outlet reported."""
        known = self._run_times
        return [
            outlet
            for outlet in range(1, self.model.total_outlets + 1)
            if (outlet - 1) not in known
        ]

    @property
    def restart_on_runtime_cutoff(self) -> bool:
        """Whether to re-open an outlet the valve closed on its own run-time limit.

        Read live from the entry options rather than cached, so toggling the checkbox takes
        effect on the reload without needing a restart. Off unless explicitly enabled.
        """
        return bool(self.entry.options.get(CONF_RESTART_ON_RUNTIME_CUTOFF, False))

    @callback
    def _handle_connected(self) -> None:
        """Re-seed whenever the stream connects.

        This is what replaces interval polling. The broker sends no state on connect — only
        future change events — so without a read here a reconnect would leave every entity
        holding whatever it had before the gap, with nothing to correct it until the shower
        was next used.
        """
        # Durations measured across a disconnect are meaningless — we cannot know what the
        # outlets did while the stream was down, and the gap has been as long as 11.9 hours.
        # Dropping the timings means a session spanning a reconnect is simply not judged,
        # rather than judged on a number we made up.
        self._cutoff.forget()
        self.hass.async_create_task(self._async_reseed_after_connect())

    async def _async_reseed_after_connect(self) -> None:
        try:
            await self._async_seed_state()
        except (AuthError, KohlerError) as err:
            # The stream is up regardless; pushes will still arrive. Do not fail the entry
            # over a re-seed, and do not retry here — the next connect will try again.
            _LOGGER.warning("Kohler re-seed after MQTT connect failed: %s", err)
            if credential_is_dead(err):
                # A rejected credential is the one failure the next connect cannot fix,
                # and this path would otherwise absorb it silently.
                self._handle_auth_error(err)
            return
        self._persist_refresh_token()
        self.async_set_updated_data(self._snapshot())

    async def async_shutdown_stream(self) -> None:
        """Stop the MQTT stream on unload."""
        if self.stream is not None:
            await self.stream.async_stop()
            self.stream = None
        # The raw capture is closed by the stream's own teardown; this one has no stream to
        # ride on, so it is released here. Blocking close — off the loop.
        if self.cutoff_log is not None:
            await self.hass.async_add_executor_job(self.cutoff_log.close)
        if self.warmup_log is not None:
            await self.hass.async_add_executor_job(self.warmup_log.close)

    # ------------------------------------------------------------------ #
    # Push
    # ------------------------------------------------------------------ #
    def _handle_envelope(self, envelope: Envelope) -> None:
        """Apply an MQTT message and notify entities if it changed anything."""
        changed = False
        if (
            self.gcs_state is not None
            and self.gcs_device is not None
            and envelope.device_id == self.gcs_device.device_id
        ):
            was_warmup = self.gcs_state.warmup_mode
            changed |= self.gcs_state.apply_envelope(envelope)
            self._remember_message(envelope)
            self._handle_warmup_mode_change(
                was_warmup,
                self.gcs_state.warmup_mode,
                announced=envelope.code == MSG_GCS_WARMUP_STATUS,
            )
            self._remember_open_masks()
            self._check_runtime_cutoff()
        if (
            self.hub_state is not None
            and self.hub_device is not None
            and envelope.device_id == self.hub_device.device_id
        ):
            changed |= self.hub_state.apply_envelope(envelope)
            self._remember_message(envelope)
            if self.hub_state.favorites:
                self.favorites = self.hub_state.favorites
        if changed:
            self.async_set_updated_data(self._snapshot())

    @callback
    def _remember_open_masks(self) -> None:
        """Keep the last outlet masks seen while water was actually running.

        **A fallback record of what a cutoff has to be undone with.** When a zone hits its
        limit the valve does not close one outlet, it clears that zone's whole mask and sets
        the pause flag in the same message — so by the time the close is detected, the record
        of what was running has already been destroyed, and rebuilding from current state
        restores nothing.

        The detector keeps its own per-zone copy of the pre-pause mask, which is more precise
        and is what the restore prefers. This snapshot still earns its place for the zone the
        detector did *not* fire on: when a preset drives the shower, the cut pauses every
        zone the preset owns, and only this has any record of what the un-expired zone was
        doing (measured 2026-08-13 20:52:46 — zone 2 expired at 3600 s, zone 1 was paused at
        1831 s).

        **Flow is snapshotted here too, for the same zone.** `ZoneCutoff.reading` only ever
        covers the zone whose *own* duration matched a limit — the detector never classifies
        the co-paused zone as a cutoff at all (its duration matches nothing), so it has no
        reading of its own to hand back. This is the only surviving record of what it was
        running, same reasoning as the mask.

        Only updated while something is open **and nothing is paused**, which is precisely
        what makes it survive the cutoff message: an all-closed or paused snapshot never
        overwrites it, so this always holds the last genuinely-flowing moment for both zones
        together.
        """
        state = self.gcs_state
        if state is None:
            return
        masks = {
            zone: (word.outlet_mask if word else 0)
            for zone, word in ((1, state.valve1), (2, state.valve2))
        }
        if not any(masks.values()):
            return
        if any(word and word.paused for word in (state.valve1, state.valve2)):
            return
        self._last_open_masks = masks
        self._last_open_flows = {
            zone: word.flow_percent
            for zone, word in ((1, state.valve1), (2, state.valve2))
            if word is not None
        }

    @callback
    def _learn_run_times(self, state: GcsState) -> None:
        """Absorb any newly announced `maximumRunTime` and remember it across restarts.

        The valve announces one outlet at a time, unprompted, so this fills in gradually and
        is the only way the figure can ever be obtained — nothing can ask for it.
        """
        learned = {
            outlet_id: limits.maximum_run_time
            for outlet_id, limits in state.outlet_limits.items()
            if limits.maximum_run_time is not None
        }
        new = {k: v for k, v in learned.items() if self._run_times.get(k) != v}
        if not new:
            return
        self._run_times.update(new)
        _LOGGER.info(
            "Learned run-time limit for outlet(s) %s: %s — the run-time cutoff feature is "
            "armed for them",
            ", ".join(str(k + 1) for k in sorted(new)),
            ", ".join(f"{v}s" for _, v in sorted(new.items())),
        )
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={
                **self.entry.data,
                CONF_OUTLET_RUN_TIMES: {
                    str(k): v for k, v in sorted(self._run_times.items())
                },
            },
        )
        # The reason the Repairs card can look after itself: this is the moment the owner's
        # trip to the Konnect app pays off, and it needs no restart to be noticed.
        self.async_refresh_setup_issue()

    async def _async_sync_default_preset_timer(self) -> None:
        """Take the hidden default preset's own timer out of the way, once.

        Preset 1 carries a `time` the owner cannot see or edit — it appears in neither the
        touchscreen nor the Konnect app — and it silently overrides the outlet limit whenever
        it is lower. Normalising it here leaves the hardware `maximumRunTime` as the single
        thing that ends a shower. `SYNC_DEFAULT_PRESET_TIMER` in `const.py` carries the full
        reasoning, including why presets 2-10 are deliberately left alone.

        **This never fails setup.** It is a convenience, not a prerequisite: the integration
        works fine against a preset with the wrong timer, so a Kohler outage, a rejected
        write, or an unexpected payload is logged and stepped over. Nothing downstream reads
        its result.
        """
        if not SYNC_DEFAULT_PRESET_TIMER or self.gcs is None:
            return
        # Consume the seed's payload rather than re-reading `gcs-preset`, which
        # `_async_seed_state` fetched on the line before this one — the second read of the
        # same endpoint per start, folded 2026-08-21.
        #
        # ⚠️ **Taken and cleared in one step, deliberately.** This payload is echoed back to
        # the valve verbatim for every field except `time`, so it must never be reused on a
        # later pass; `None` here simply means this reads for itself, which is always safe.
        presets, self._seeded_presets = self._seeded_presets, None
        try:
            plan = await self.gcs.async_sync_preset_timer(
                DEFAULT_PRESET_ID, DEFAULT_PRESET_TIMER_SECONDS, presets=presets
            )
        except (KohlerError, AuthError, DeviceOffline) as err:
            _LOGGER.debug(
                "Could not check preset %s's run timer (harmless, setup continues): %s",
                DEFAULT_PRESET_ID,
                err,
            )
            return
        if plan.needed:
            _LOGGER.info(
                "Preset %s (%s) had a hidden %ss run timer that would stop a shower before "
                "the valve's own limit; rewrote it to %ss so the outlet limit is the only "
                "thing that ends a shower",
                DEFAULT_PRESET_ID,
                plan.name or "unnamed",
                plan.previous,
                DEFAULT_PRESET_TIMER_SECONDS,
            )
        else:
            _LOGGER.debug(
                "Preset %s run timer needs no change (%s)", DEFAULT_PRESET_ID, plan.reason
            )

    def _zone_limits(self) -> dict[int, tuple[int, ...]]:
        """The distinct `maximumRunTime` values configured for each zone's outlets.

        The valve reports this per outlet but **times it per zone** (see
        `anthem_plus/runtime_cutoff.py`), so there is no single "the" limit for a zone unless
        its outlets happen to agree — which they do on every install seen, all six at 900 s.

        Where they disagree, every distinct value is offered as a candidate rather than
        picking one. A mixed-limit zone has never been observed and there is no evidence for
        which value the valve would use; matching any of them means such a zone is still
        protected, and the cost is a handful of extra 10 s windows in a 15-minute session
        that would each also have to coincide with a `0x40` pause to fire.

        ⚠️ **`maximumRunTime` only. Preset timers are deliberately excluded — do not add
        them here.** A preset carries its own `time` (`GCS_PRESET_STS`), a *second*
        independent limit that stops a preset-driven session early whenever it is lower than
        `maximumRunTime`; this install currently runs a 1800 s preset under a 3600 s hardware
        gate, so it is the preset that stops the shower. Those stops land as
        `verdict: "ignored"` with a large `off_by`, and that is the intended outcome: the
        hardware gate cutting a shower short is what this feature exists to defeat, whereas a
        preset ending at its own configured duration is the system doing what the user asked.
        Restarting those would override a setting somebody chose on purpose. Owner's decision,
        2026-08-17 — see `docs/gcs/api.md`, "two independent timers".
        """
        limits: dict[int, set[int]] = {zone: set() for zone in self.model.zones}
        for outlet in range(1, self.model.total_outlets + 1):
            seconds = self._run_times.get(outlet - 1)
            if seconds is None:
                continue
            zone, _ = self.model.outlet_location(outlet)
            limits.setdefault(zone, set()).add(seconds)
        return {zone: tuple(sorted(values)) for zone, values in limits.items()}

    def run_time_limits_for_zone(self, zone: int) -> tuple[int, ...]:
        """The `maximumRunTime` candidates for one zone. Empty until the valve announces."""
        return self._zone_limits().get(zone, ())

    def zone_flowing_for(self, zone: int) -> float | None:
        """Seconds this zone has been flowing, from the cutoff detector's own clock.

        Fed on every message whether or not the restart option is on, so it is available
        regardless. None when the zone is idle, or after a reconnect until it next starts.
        """
        return self._cutoff.flowing_for(zone)

    @callback
    def _check_runtime_cutoff(self) -> None:
        """Re-open a zone the valve closed on its own timer, when the option is on.

        Off unless `restart_on_runtime_cutoff` is enabled — this **defeats a manufacturer
        cutoff**, and with no resume limit the water keeps coming back for as long as
        somebody leaves it running. That is the configured intent, not an oversight; the
        limit question was put to the owner and answered "unlimited". Every resume is logged
        at WARNING so there is always a record of water having been restarted automatically.

        **Per zone, not per outlet.** The valve's timer starts when a zone begins flowing and
        is not reset by outlet changes within that zone, so that is what has to be timed.
        Timing each outlet from its own opening — which this did until 2026-08-14 — fires
        only when a zone runs one unchanging outlet for the whole session, and misses
        everything else: 3 of 4 real cutoffs went undetected in the logs that exposed this.

        Temperature carries over because `async_apply_valve` preserves it, and flow follows
        `DEFAULT_FLOW_PERCENT` like every other write.

        Detection is duration-only and lives in `anthem_plus/runtime_cutoff.py`, which
        documents why that is sound. Nothing fires without a positive match, and every
        decision — including every *non*-match — is written to the cutoff debug log.
        """
        state = self.gcs_state
        if state is None:
            return

        self._learn_run_times(state)
        masks: dict[int, int] = {}
        paused: dict[int, bool] = {}
        readings: dict[int, ZoneReading] = {}
        for zone in self.model.zones:
            word = state.zone_word(zone)
            masks[zone] = word.outlet_mask if word else 0
            paused[zone] = bool(word and word.paused)
            if word is not None:
                # Fahrenheit unconditionally, whatever the account displays: this feeds a
                # diagnostic log that gets read alongside captures from other sessions, and
                # a unit that changes with a setting makes those incomparable.
                readings[zone] = ZoneReading(
                    flow_percent=round(word.flow_percent, 1),
                    temperature_f=round(word.temperature_celsius * 9 / 5 + 32, 1),
                )

        fired = self._cutoff.update(masks, paused, self._zone_limits(), readings)
        if not fired or not self.restart_on_runtime_cutoff:
            if fired:
                # Detected but not acted on. Without this line the debug log would show a
                # `cutoff` verdict and no restore, which reads like a bug rather than the
                # switch being off.
                self._journal(
                    "restore",
                    skipped="restart_on_runtime_cutoff is off",
                    zones=[cut.zone for cut in fired],
                )
            return

        # Detection and restart used to log a line each. One message now covers both, and it
        # is emitted only once the water is actually back — so it never claims a restart that
        # then failed. The cut time is captured here rather than in the restart, which runs a
        # few seconds later as a task.
        cut_at = dt_util.now()
        self.hass.async_create_task(self._async_restart_after_cutoff(fired, cut_at))

    @callback
    def _journal(self, event: str, **fields: Any) -> None:
        """Write to the cutoff debug log if it exists. No-op before setup finishes.

        This runs on the event loop, so the log deliberately refuses to open a file itself —
        see `CutoffDebugLog.wants_open`. When it asks for one, the open happens in an
        executor and the next record lands.
        """
        if self.cutoff_log is None:
            return
        self.cutoff_log.note(event, **fields)
        if self.cutoff_log.wants_open:
            self.hass.async_add_executor_job(self.cutoff_log.prepare)

    async def _async_restart_after_cutoff(
        self, fired: list[ZoneCutoff], cut_at: Any
    ) -> None:
        """Put back exactly what was flowing in the zones the valve cut.

        The valve clears the zone's mask in the same message that reports the cut, so current
        state says nothing about what the shower was doing. Two independent records survive
        it — the detector's own pre-pause mask, which is the precise instant before the cut,
        and `_last_open_masks` as a fallback — and either beats rebuilding from a mask that
        has already been wiped. Measured live: rebuilding from current state brought a
        four-outlet shower back as outlet 4 alone.

        **A second zone is restored too, but only if it is also paused.** Normally a cut
        pauses just the expiring zone and leaves the other's mask untouched — 10 of the 11
        cutoffs in the corpus. The exception is when a preset is driving the shower: the cut
        is internally `{preset, action:"Off"}`, so it pauses *every* zone the preset owns,
        and the zone that did not expire has had its mask wiped just as thoroughly. Its
        timing proves nothing (1831 s in the one captured instance), so the pause flag is
        what identifies it.

        A zone that is neither cut nor paused is re-sent exactly as it reads now, so anything
        changed there in the second between the cut and this write survives.

        **Flow is restored from `cut.reading`, not left to `DEFAULT_FLOW_PERCENT`.** This is
        deliberately a different rule from `async_apply_valve`'s ordinary writes, which never
        inherit flow — that rule exists so nothing silently *adopts* the touchscreen's last
        value on an unrelated write. A restore is not that: it is putting back a value this
        code itself observed running a moment before it force-closed the zone, which is
        squarely what "restore" should mean. Measured live 2026-08-14: a preset-driven shower
        running at 82.5% was cut and had been coming back at 100% — 2.9x on zone 1, which had
        no outlet open at all. `async_apply_valve` honours whatever flow byte it is given
        exactly, uncapped and unscaled against any ceiling (verified on hardware; see
        `docs/gcs/api.md#flow-the-valve-obeys-the-touchscreen-is-what-computes-limits`), so
        replaying the observed value reproduces the observed experience regardless of whether
        the valve is calibrated — there is no ceiling to reason about either way. **Covers the
        `also_paused` zone too**, from `_last_open_flows` — the same snapshot-of-last-resort
        `_last_open_masks` provides for its mask, and for the same reason: the detector never
        classifies that zone as a cutoff (its own duration matches nothing), so it has no
        `ZoneCutoff.reading` to draw on. Falls back to `DEFAULT_FLOW_PERCENT` only when
        neither source has a value for that zone.
        """
        state = self.gcs_state
        if self.gcs is None or state is None:
            return

        snapshot = self._last_open_masks or {}
        flow_snapshot = self._last_open_flows or {}
        masks: dict[int, int] = {}
        flows: dict[int, float] = {}
        also_paused: list[int] = []
        cut_zones = {cut.zone for cut in fired}
        for zone in self.model.zones:
            word = state.zone_word(zone)
            masks[zone] = word.outlet_mask if word else 0
            if zone in cut_zones or not (word and word.paused):
                continue
            # Paused alongside a cut it did not cause: the preset case above. Only the
            # snapshot can say what it was doing, since the detector never saw it expire.
            if snapshot.get(zone):
                masks[zone] = snapshot[zone]
                also_paused.append(zone)
                if zone in flow_snapshot:
                    flows[zone] = flow_snapshot[zone]
        for cut in fired:
            # The detector's mask is authoritative — it is the last mask seen flowing in that
            # exact zone. `_last_open_masks` covers the case where the detector was fed a
            # zero mask first (a snapshot ordering quirk), and 0 means "nothing to restore",
            # which is reported rather than silently sent.
            restore = cut.mask or snapshot.get(cut.zone, 0)
            if not restore:
                _LOGGER.warning(ENDLESS_SHOWER_NOTHING_TO_RESTORE)
            masks[cut.zone] = restore
            # The detector's own reading is authoritative for the zone it actually timed —
            # more precise than the snapshot, same precedence as the mask above.
            if cut.reading is not None:
                flows[cut.zone] = cut.reading.flow_percent
            elif cut.zone in flow_snapshot:
                flows[cut.zone] = flow_snapshot[cut.zone]

        self._journal(
            "restore",
            zones=[cut.zone for cut in fired],
            also_paused=also_paused,
            masks=masks,
            from_detector={cut.zone: cut.mask for cut in fired},
            from_snapshot=snapshot,
            was_flow_percent=dict(flows),
            was_temperature_f={
                cut.zone: cut.reading.temperature_f
                for cut in fired
                if cut.reading is not None
            },
            writing_flow_percent={
                zone: flows.get(zone, DEFAULT_FLOW_PERCENT)
                for zone in sorted(cut_zones | set(also_paused))
            },
            # True when every zone being restored — the cut zone(s) and any also_paused one —
            # had a captured flow to draw on, so the write below reproduces it exactly. False
            # means at least one zone had no reading and fell back to DEFAULT_FLOW_PERCENT —
            # a guess, not a restore.
            flow_preserved=all(zone in flows for zone in cut_zones | set(also_paused)),
        )
        if not any(masks.values()):
            return

        # Timed because this call, not our own logic, is where a slow restore comes from.
        # Measured over seven live cutoffs the decision above is a flat 0.4 ms while this
        # varies 0.64-5.05 s — so the only number worth recording is this one, and it belongs
        # in the cutoff log rather than `home-assistant.log`, which rotates away.
        started = time.monotonic()
        try:
            await self.async_apply_valve(
                zone_masks=masks, zone1_flow=flows.get(1), zone2_flow=flows.get(2)
            )
        except (KohlerError, HomeAssistantError) as err:
            # Never retried: a failed restart leaves the water off, which is the safe end
            # state, and a retry loop against a valve that is refusing is not.
            _LOGGER.warning("Restart after run-time cutoff failed: %s", err)
            self._journal("restore_failed", zones=[cut.zone for cut in fired], error=str(err))
            return
        restored = sorted(
            outlet
            for outlet in range(1, self.model.total_outlets + 1)
            for zone, bit in [self.model.outlet_location(outlet)]
            if masks.get(zone, 0) >> bit & 1
        )
        _LOGGER.warning(ENDLESS_SHOWER_RESTARTED, cut_at.strftime("%H:%M:%S"))
        self._journal(
            "restore_done",
            outlets=restored,
            write_seconds=round(time.monotonic() - started, 3),
        )
        # The valve does not reliably announce a restored zone — 17 of the corpus's 18
        # restores drew a GCS_SOLO_STS within 0.06-1.08 s, one drew nothing for 176.77 s
        # while the water ran — and the detector's clock used to start only on that
        # announcement. An anchor that late reads as "matches no limit" at the next cutoff
        # and leaves the water off with nothing saying why. The write that just succeeded is
        # when the water came back, so anchor there; a prompt announcement wins the race
        # harmlessly (`note_restore` skips zones already timed). Session 12 §3, fixed
        # 2026-08-22.
        self._cutoff.note_restore(
            {
                zone: masks[zone]
                for zone in cut_zones | set(also_paused)
                if masks.get(zone)
            },
            readings={
                cut.zone: cut.reading for cut in fired if cut.reading is not None
            },
        )

    def _snapshot(self) -> dict[str, Any]:
        """A cheap dict so DataUpdateCoordinator has something to hand entities.

        Entities read the state objects directly; this only carries freshness markers.
        """
        return {
            "gcs_last_update": self.gcs_state.last_update if self.gcs_state else None,
            "hub_last_update": self.hub_state.last_update if self.hub_state else None,
            "mqtt_connected": bool(self.stream and self.stream.connected),
        }

    # ------------------------------------------------------------------ #
    # Poll
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> dict[str, Any]:
        if self._seeded_during_setup:
            # **The first refresh after setup is not a refresh.** `async_setup_entry` calls
            # `async_setup()` and then `async_config_entry_first_refresh()` on the next line,
            # and the base class turns that into a `_async_update_data()` — so without this,
            # every start read the whole account twice, milliseconds apart, for state that
            # could not have changed in between. Measured 2026-08-21: **five duplicate REST
            # calls per start** (gcs-state, gcsadvancestate, presets, hub-state, favorites;
            # the hub configuration read is already skipped once `hub_capabilities.known`).
            #
            # What the first refresh is actually *for* is populating `coordinator.data`
            # before the platforms are forwarded — `async_setup` never calls
            # `async_set_updated_data`, so `data` is None until this returns. That needs the
            # snapshot, not the network.
            #
            # **Why this is safe, and not merely cheap.** `async_setup` ends by awaiting
            # `stream.async_start()`, which returns with the socket up — so `_handle_connected`
            # has already scheduled a full re-seed of its own by the time this runs. Anything
            # that changed in the gap between the setup read and the stream coming up is
            # caught by *that* read, which happens after the connection exists rather than
            # before it. This one was redundant with it, a few hundred milliseconds earlier
            # and strictly worse placed.
            #
            # ⚠️ **Only the first one.** A manual `homeassistant.update_entity` is the only
            # other way in — with `SCAN_INTERVAL = None` there is no clock — and that one
            # must read for real, so the flag is spent here and never set again.
            self._seeded_during_setup = False
            self._persist_refresh_token()
            return self._snapshot()
        try:
            await self._async_seed_state()
        except AuthUnavailable as err:
            raise UpdateFailed(f"Kohler auth service unreachable: {err}") from err
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except KohlerError as err:
            raise UpdateFailed(f"Kohler poll failed: {err}") from err
        self._persist_refresh_token()
        return self._snapshot()

    async def _async_seed_state(self) -> None:
        """Read current state over REST into the state objects.

        Runs at setup, on every MQTT connect, and on a manual `update_entity`. Failures for
        one device do not blank the other.
        """
        if self.gcs_device is not None and self.gcs_state is not None:
            try:
                payload = await self.client.async_get_gcs_state(
                    self.gcs_device.device_id
                )
                was_warmup = self.gcs_state.warmup_mode
                self.gcs_state.apply_rest_state(payload)
                mode_now = self.gcs_state.warmup_mode
                if was_warmup is not None and mode_now != was_warmup:
                    # The mode moved while we were not listening. `apply_rest_state` writes
                    # `warmup_mode` straight in, so this never reaches
                    # `_handle_warmup_mode_change` and nothing else would record it — the
                    # one way a disable can happen and leave no trace in the journal at all.
                    #
                    # This reseed runs on every MQTT reconnect, so the gap it covers is a
                    # change during a stream outage — which the hub web UI causes for real:
                    # any signed-in use of it writes `warmUpDisabled` (api.md §3h), and a
                    # sign-in while the stream is down lands exactly here.
                    #
                    # A discovered disable restores through the same machinery as an
                    # announced one: same decision function, same self-write grace, same
                    # single-flight guard — and `_async_restore_warmup` waits its delay and
                    # re-checks the *live* mode before writing, so "the REST read is of
                    # unknown age" costs nothing by write time. What a discovery still
                    # cannot have is a `before_window` — the wire context happened while
                    # there was no wire — so `source: "rest"` stays on the record and the
                    # `restoring` field says what was decided. Recorded-but-never-restored
                    # from 2026-08-21 until 2026-08-22 (owner's decision to wire it).
                    write_age, ours = self._warmup_write_status(mode_now)
                    restoring = should_restore_warmup(
                        was_warmup,
                        mode_now,
                        enabled=self.warmup_auto_restore,
                        self_write_mode=self._warmup_self_write_mode,
                        self_write_age=write_age,
                        grace_seconds=WARMUP_SELF_WRITE_GRACE_SECONDS,
                    )
                    self._warmup_journal(
                        "mode",
                        before=was_warmup,
                        after=mode_now,
                        ours=ours,
                        source="rest",
                        restoring=restoring,
                    )
                    if restoring:
                        self._schedule_warmup_restore(was_warmup)
                # The third way to learn a mode, and the one `_remember_warmup_mode`'s
                # docstring used to miss. MQTT alone forgets a mode set while the stream was
                # down; our own writes alone forget a mode set from the app or touchscreen;
                # and *both* forget a mode that was simply already in force when we started.
                #
                # That third gap disabled auto-restore for seven hours on 2026-08-20: the
                # valve was in `warmUpAllOutletsWithNoStartDelay`, read correctly over REST
                # at 19:35:32Z, then disabled at 20:36:28Z — and the restore was skipped with
                # "no enabled mode has ever been seen", because no *announcement* had
                # happened in that session. See `_async_restore_warmup`.
                mode = self.gcs_state.warmup_mode
                if mode is not None and mode != WARMUP_DISABLED:
                    self._remember_warmup_mode(mode)
            except KohlerError as err:
                _LOGGER.debug("Could not seed GCS state: %s", err)

            # Per-outlet limits, including `maximumRunTime` — the number Endless Shower
            # cannot act without.
            #
            # This used to arrive **only** over MQTT, unprompted and one outlet at a time,
            # which left a blind window of unknown length after a fresh install: the switch
            # read "on" while the feature was inert, and the owner was told to go change Max
            # Shower Duration in the Konnect app purely to provoke an announcement.
            # `gcsadvancestate` carries the same data and is readable on demand — it was
            # reachable all along, in a response this integration already fetched for
            # topology (see `docs/gcs/api.md` §1c, corrected 2026-08-17).
            #
            # Runs on every re-seed, not just the first: cheap, and it re-checks the limit
            # after a reconnect rather than trusting a value that may be hours stale.
            try:
                limits = outlet_limits_from_settings(
                    await self.client.async_get_gcs_settings(self.gcs_device.device_id)
                )
                if limits:
                    self.gcs_state.outlet_limits.update(limits)
                    # Same path an MQTT announcement takes, so the value is persisted and
                    # the cutoff detector is armed without waiting for the valve to speak.
                    self._learn_run_times(self.gcs_state)
            except KohlerError as err:
                _LOGGER.debug("Could not read outlet limits over REST: %s", err)

            # Presets push over MQTT on every create, edit, rename, and delete, so this is
            # only the seed — nothing re-reads them on a clock.
            try:
                presets = await self.client.async_get_gcs_presets(
                    self.gcs_device.device_id
                )
                self.gcs_state.apply_preset_list(presets)
                # Kept for `_async_sync_default_preset_timer`, which needs the *raw* record
                # — title, volume and each valve's `hexString` — none of which survive
                # `apply_preset_list`; `GcsPreset` keeps only id, name and is_experience.
                self._seeded_presets = presets
            except KohlerError as err:
                _LOGGER.debug("Could not read GCS presets: %s", err)

        if self.hub_device is not None and self.hub_state is not None:
            device_id = self.hub_device.device_id
            try:
                self.hub_state.apply_rest_state(
                    await self.client.async_get_hub_state(device_id)
                )
            except KohlerError as err:
                _LOGGER.debug("Could not seed HUB state: %s", err)
            # Zones, outlet types, and installed parts — installation-time facts that no
            # message ever pushes because nothing changes them at runtime. Read once and
            # keep it; re-reading on a timer polls forever for an event that happens when a
            # plumber visits.
            if not self.hub_capabilities.known:
                try:
                    config = await self.client.async_get_hub_configuration(device_id)
                    self.hub_capabilities = HubCapabilities.from_configuration(
                        config.get("configuration") or {}
                    )
                except KohlerError as err:
                    _LOGGER.debug("Could not read HUB configuration: %s", err)
            try:
                payload = await self.client.async_get_hub_favorites(device_id)
                favorites = payload.get("favorites")
                if isinstance(favorites, list):
                    # Favourite ids are reassigned when one is deleted, so this list is the
                    # only safe way to resolve a favourite — never hardcode an id.
                    self.favorites = favorites
            except KohlerError as err:
                if getattr(err, "status", None) == 404:
                    # Not a failure: this endpoint 404s when the account has **no** saved
                    # favourites, rather than returning an empty list. Confirmed 2026-08-17 —
                    # the route is handled (it answers with the application's own error
                    # envelope, unlike a genuine bad path), MQTT `FAVORITES_SNAPSHOT` agrees
                    # with `attributes: []`, and `docs/hub/cloud_api.md` §5.2 has a captured
                    # 200 from when this account still had one. Logging it as an error made
                    # three misleading lines per startup.
                    self.favorites = []
                    _LOGGER.debug("No HUB favourites are saved on this account")
                else:
                    _LOGGER.debug("Could not read HUB favourites: %s", err)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _persist_refresh_token(self) -> None:
        """Write the rotated refresh token back to the config entry."""
        token = self.auth.refresh_token
        if token and token != self.entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: token}
            )

    async def async_apply_valve(
        self,
        *,
        zone1_temperature: float | None = None,
        zone2_temperature: float | None = None,
        zone1_flow: float | None = None,
        zone2_flow: float | None = None,
        zone_masks: dict[int, int] | None = None,
        paused: bool = False,
    ) -> None:
        """Re-send both valve words with selected fields overridden.

        The valve accepts no partial write: every command carries the complete state of
        both zones. So changing one zone's temperature means rebuilding both words from
        current state and re-sending. Anything not overridden is preserved, including which
        outlets are open — which is what makes it safe to adjust temperature mid-shower.

        This mirrors the Konnect app, which POSTs a fresh ``solowritesystem`` on every
        temperature, flow, or outlet adjustment.

        **Flow is the one field that does not carry forward.** Omitting it writes
        ``DEFAULT_FLOW_PERCENT`` (100%), not the valve's current value. Every other field is
        preserved, so this is a deliberate asymmetry: with no flow entities in the UI, no
        caller here can ever *mean* a particular flow, and inheriting one let the touchscreen
        dictate what Home Assistant sent. Pass ``zone1_flow``/``zone2_flow`` explicitly to
        write a specific value — the codec has always supported it.

        Consequence worth knowing: adjusting temperature from Home Assistant mid-shower now
        also restores full flow, if the wall panel had reduced it.
        """
        if self.gcs is None or self.gcs_state is None:
            raise HomeAssistantError("No Anthem valve on this account")

        state = self.gcs_state
        # Masks are per zone throughout — no global outlet numbering is involved, so no
        # model-dependent mapping can be applied wrongly here.
        masks = {
            1: state.valve1.outlet_mask if state.valve1 else 0,
            2: state.valve2.outlet_mask if state.valve2 else 0,
        }
        if zone_masks:
            masks.update(zone_masks)

        def resolve(zone: int, temperature: float | None, flow: float | None):
            word = state.valve1 if zone == 1 else state.valve2
            celsius = (
                unit_to_celsius(temperature, self.temperature_unit)
                if temperature is not None
                else (word.temperature_celsius if word else 38.0)
            )
            # Flow does NOT inherit from the current word — see `DEFAULT_FLOW_PERCENT`.
            # Carrying it forward meant every Home Assistant write silently adopted whatever
            # the touchscreen last set, which is below 100% in 31% of captured words and has
            # been as low as 8%.
            percent = flow if flow is not None else DEFAULT_FLOW_PERCENT
            return celsius, percent

        celsius1, flow1 = resolve(1, zone1_temperature, zone1_flow)
        valve1 = encode_word(VALVE1_PREFIX, celsius1, flow1, masks[1], paused=paused)
        if self.model.uses_valve2:
            celsius2, flow2 = resolve(2, zone2_temperature, zone2_flow)
            valve2 = encode_word(VALVE2_PREFIX, celsius2, flow2, masks[2], paused=paused)
        else:
            valve2 = UNUSED_VALVE_WORD

        # Mark before sending, with **what** was written. A close that follows our own
        # *closing* write is ours, not the valve's timer, and must not be undone — otherwise
        # stopping the shower from Home Assistant near the limit would be read as a timeout
        # and immediately restarted. An *opening* write gets no such grace: it cannot cause a
        # close, and pretending it could swallowed a real cutoff on 2026-08-14.
        #
        # `paused=True` counts as closing whatever it touches, since the water stops either
        # way and the valve reports the mask cleared.
        self._cutoff.note_local_write(
            {zone: (0 if paused else mask) for zone, mask in masks.items()}
        )
        try:
            await self.gcs.async_write_valves(valve1, valve2)
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem valve is offline. Check that it is powered on and connected "
                "to Wi-Fi, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

    async def async_send_valve_hex(
        self, zone1_hex: str, zone2_hex: str | None = None
    ) -> dict[str, Any]:
        """POST raw command words to ``solowritesystem``. **This can run water.**

        The escape hatch for everything the entities do not model — an outlet combination,
        flow value, or temperature the UI cannot express. It is the same endpoint every other
        control path uses; the only difference is that the caller supplies the words.

        Both words are validated with ``normalize_word`` before anything is sent. Malformed
        input is rejected locally rather than posted to a device that opens water valves, and
        the decoded meaning is logged so the journal records what was actually asked for.

        ``zone2_hex`` omitted **re-sends zone 2's current state**, so zone 2 keeps doing
        whatever it was doing. It emphatically does *not* send ``00000000``.

        That sentinel means "no valve addressed", and on a two-valve system it is measured to
        make the device **discard the entire command** — `v1=00000000 v2=11849C01` opened
        nothing, while `v1=0185C800 v2=1185C801` opened valve 2 immediately
        (`docs/gcs/api.md`). So a blank zone 2 filled with zeroes would silently throw away
        the zone 1 word the caller had just carefully built. A valve that should stay shut
        gets a well-formed word with mask ``0x00``; only a valve that does not physically
        exist gets the sentinel, which is why a single-zone model still sends it here.

        The protocol has no partial write — every POST carries both zones — so "leave zone 2
        alone" can only be expressed by sending zone 2's own current word, which is what this
        does. Flow follows `DEFAULT_FLOW_PERCENT` like every other write.

        Returns the decoded interpretation of what was sent, so an automation or a person can
        confirm the word meant what they thought.
        """
        if self.gcs is None or self.gcs_state is None:
            raise HomeAssistantError("No Anthem valve on this account")

        word1 = _command_half(zone1_hex, "zone1_hex")

        # A typed-in sentinel is treated exactly like a blank field on a two-valve system.
        # It cannot mean anything useful there — it addresses no valve, so the device
        # discards the whole command, taking the zone 1 word with it — and "00000000 leaves
        # zone 2 alone" is the natural reading for anyone who has seen the sentinel at all.
        # Honouring it literally would satisfy nobody's intent and void the command instead.
        if zone2_hex and zone2_hex.strip("0") == "" and self.model.uses_valve2:
            _LOGGER.info(
                "send_valve_hex: zone2_hex was all zeroes, which addresses no valve; "
                "re-sending zone 2's current state instead so the command is not discarded"
            )
            zone2_hex = None

        if zone2_hex:
            word2 = _command_half(zone2_hex, "zone2_hex")
        elif not self.model.uses_valve2:
            # The only legitimate use of the sentinel: there is genuinely no second valve.
            word2 = UNUSED_VALVE_WORD
        else:
            # Re-send zone 2 as it stands — never the sentinel, which would risk the device
            # discarding the whole command. See the docstring.
            current = self.gcs_state.valve2
            word2 = encode_word(
                VALVE2_PREFIX,
                current.temperature_celsius if current else 38.0,
                DEFAULT_FLOW_PERCENT,
                current.outlet_mask if current else VALVE_STOP_MASK,
                paused=current.paused if current else False,
            )

        if word1 == UNUSED_VALVE_WORD:
            # Not blocked: this is the escape hatch, the failure mode is "nothing happens"
            # rather than unexpected water, and it is a documented experiment worth being
            # able to run. But it should never be a silent surprise.
            _LOGGER.warning(
                "send_valve_hex: zone1_hex is the all-zero sentinel, which addresses no "
                "valve — the device is expected to discard this entire command, zone 2 "
                "included. To close zone 1 instead, send a word with outlet mask 00."
            )

        decoded = {
            "zone1": _describe_word(word1),
            "zone2": _describe_word(word2),
        }
        _LOGGER.info(
            "send_valve_hex: zone1=%s (%s), zone2=%s (%s)",
            word1,
            decoded["zone1"],
            word2,
            decoded["zone2"],
        )

        # Same rule as `async_apply_valve`: only the zones this word actually closes earn the
        # grace. A raw word is decoded rather than trusted — an undecodable one records
        # nothing, so a genuine cutoff is still caught.
        closing: dict[int, int] = {}
        for zone, word in ((1, word1), (2, word2)):
            if word == UNUSED_VALVE_WORD:
                continue
            try:
                decoded = decode_word(word)
            except ValveHexError:  # pragma: no cover - already validated above
                continue
            closing[zone] = 0 if decoded.paused else decoded.outlet_mask
        self._cutoff.note_local_write(closing)
        try:
            await self.gcs.async_write_valves(word1, word2)
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem valve is offline. Check that it is powered on and connected "
                "to Wi-Fi, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

        return {"zone1_hex": word1, "zone2_hex": word2, "decoded": decoded}

    async def async_set_zone_outlet(self, zone: int, outlet: int, on: bool) -> None:
        """Open or close one outlet within a zone.

        ``outlet`` is 1-based **within that zone**, matching how the hardware and the API
        address it. Every other outlet, in both zones, is preserved.
        """
        if self.gcs_state is None:
            raise HomeAssistantError("No Anthem valve on this account")
        word = self.gcs_state.zone_word(zone)
        mask = word.outlet_mask if word else 0
        bit = 1 << (outlet - 1)
        mask = (mask | bit) if on else (mask & ~bit)
        await self.async_apply_valve(zone_masks={zone: mask})

    async def async_activate_preset(self, preset_id: int | str) -> None:
        """Start a stored GCS preset. **This runs water.**

        One call: the valve runs the preset itself, so no ``solowritesystem`` follow-up is
        needed. Verified live — the body is ``{preset, action}``.

        A preset only applies the zones it opens an outlet on; a zone left at mask ``0x00``
        keeps whatever setpoint it already had, so this cannot be used to set an idle zone's
        temperature.
        """
        if self.gcs is None:
            raise HomeAssistantError("No Anthem valve on this account")
        try:
            await self.gcs.async_activate_preset(preset_id, True)
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem valve is offline. Check that it is powered on and connected "
                "to Wi-Fi, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

    async def async_stop_shower(self) -> None:
        """Stop the water: mask byte ``0x00`` on both zones, **not** the ``0x40`` pause.

        This used to pause, which read nicely as "Paused" in the status sensor. It was
        changed on 2026-08-13 because **a pause is indistinguishable from the valve's own
        run-time cutoff** — the cutoff is internally ``{preset, action:"Off"}`` and writes
        exactly the same ``0x40``. With the restart-on-cutoff option enabled, Home Assistant
        turning the shower off and the valve timing out looked identical on the wire, leaving
        only `note_local_write()`'s 30 s grace between "stopped" and "helpfully restarted".

        ✅ **The strong guarantee is back, 2026-08-18: a stop issued from here can never be
        undone by Endless Shower.** The detector requires the ``0x40`` pause flag again, and
        this method writes ``0x00``, so its stops are outside the restart-eligible set
        entirely — by shape, not by timing.

        The requirement was briefly dropped on 2026-08-17, when a real cutoff arrived as
        ``0x00`` and was ignored. Five case studies established that as **two maximum
        durations set to different values** rather than a protocol gap: only the GCS valve
        cuts with ``0x40`` and only the Anthem Plus controller with ``0x00``, the valve fires
        marginally early and the controller marginally late, so with the two durations equal
        the pause always arrives first. See `anthem_plus/runtime_cutoff.py` and
        `docs/case_studies/`.

        `note_local_write()`'s 30 s grace still applies and is now belt-and-braces rather than
        the only protection.

        Still routed through `async_apply_valve` rather than `GcsDevice.async_turn_off()`,
        which would write a flat 38.0 °C to both zones — this preserves each zone's own
        setpoint while clearing its outlets.
        """
        await self.async_apply_valve(zone_masks={1: 0, 2: 0})

    async def async_set_warmup(self, mode: str) -> None:
        """Set the valve's warmup mode. **This does not run water now.**

        Warmup is a stored mode, not an action: an enabled mode means the valve warms up by
        itself at the start of a session. The setting persists — it survives a power cycle,
        and the valve re-announces it about 4 s after every boot.

        ``mode`` must be one of ``WARMUP_MODES_CURRENT`` — the three the current Konnect app
        offers. The two legacy delayed-start values are rejected here rather than passed
        through: the valve may still be *holding* one, and `select.py` shows it when it is,
        but nothing knows what their delay does and writing one would be guessing.

        ⚠️ **Refused while water is running.** The Konnect app checks whether any outlet on
        either valve is on and silently reverts its own control rather than calling the API;
        this mirrors that check, but says so instead of reverting. Whether the *device*
        enforces it is untested — the guard is client-side in the app, so a write during a
        shower might land, might be ignored, and there is no way to tell which from the
        response. Raising keeps us on the app's side of a question nobody has answered.
        """
        if self.gcs is None:
            raise HomeAssistantError("No Anthem valve on this account")
        if mode not in WARMUP_MODES_CURRENT:
            raise HomeAssistantError(
                f"{mode!r} is not a warmup mode this integration writes. Expected one of: "
                + ", ".join(WARMUP_MODES_CURRENT)
            )
        state = self.gcs_state
        if state is not None and state.is_running:
            raise HomeAssistantError(
                "Warmup cannot be changed while the shower is running. The Konnect app "
                "blocks this too. Turn the water off and try again."
            )
        # Recorded before the call, not after: the valve's echo can arrive while the POST
        # is still in flight, and a disable we caused must be recognisable by then.
        self._warmup_self_write_at = time.monotonic()
        self._warmup_self_write_mode = mode
        try:
            await self.gcs.async_set_warmup(mode)
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem valve is offline. Check that it is powered on and connected "
                "to Wi-Fi, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

        # Read the field back rather than trusting the write. A 200 here means the *cloud*
        # accepted the command; the valve can still ignore it, and does when warmup is
        # disabled on the fixture itself. `warmUpState.warmUp` is the device's own answer.
        #
        # ⚠️ **The first read is too early and will disagree.** Measured live 2026-08-20:
        # `gcs-state` still returned the OLD mode immediately after a successful POST and
        # only caught up by t+3 s, while the valve's own `GCS_WARM_STS` echo landed at
        # +3.42 s. So a single immediate read-back reports a false mismatch on every write.
        # Hence the retries: disagreement only means something after the device has had a
        # few seconds to answer.
        confirmed = None
        for delay in WARMUP_READBACK_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            confirmed = await self.async_read_warmup_mode()
            if confirmed == mode:
                self._remember_warmup_mode(mode)
                _LOGGER.info("Warmup mode set to %s and confirmed by the valve", mode)
                return
        if confirmed is None:
            _LOGGER.info(
                "Warmup mode %s sent to the Anthem valve; the read-back did not answer, so "
                "the stored mode is whatever the valve reports next over MQTT",
                mode,
            )
        else:
            # Past the settle window, so this is a real disagreement rather than lag. The
            # known cause is warmup being disabled on the fixture itself, where the cloud
            # accepts the command and the valve ignores it.
            _LOGGER.warning(
                "Warmup mode was set to %s but the valve still reports %s after %.0f s. The "
                "cloud accepted the command and the valve did not apply it — the usual cause "
                "is warmup being disabled on the fixture. Nothing has been retried.",
                mode,
                confirmed,
                sum(WARMUP_READBACK_DELAYS),
            )

    async def async_read_warmup_mode(self) -> str | None:
        """Read the warmup mode from the REST API and apply it, returning what it said.

        The source is `gcs-state`'s `warmUpState.warmUp` — the same field the Konnect app
        reads, and the same read that seeds this at setup and on every MQTT reconnect. It
        carries the mode axis; `warmUpState.state` beside it carries whether a warm-up is
        running, and `apply_rest_state` takes both.

        ⚠️ **REST reads here are partly cached** — `amplifierSettings.monoVolume` famously
        did not follow a live change (`docs/architecture.md`). So this is authoritative about
        what Kohler's cloud believes, which is not always what the valve did a second ago.
        The device's own push, `GCS_WARM_STS`, remains the final word and arrives by itself.

        Returns `None` if the read failed or carried no warmup field — never a guess, since
        "Off" and "we could not tell" are different answers and only one of them is safe to
        show on a control.
        """
        if self.gcs_device is None or self.gcs_state is None:
            return None
        try:
            payload = await self.client.async_get_gcs_state(self.gcs_device.device_id)
        except KohlerError as err:
            _LOGGER.debug("Could not read warmup mode: %s", err)
            return None
        self.gcs_state.apply_rest_state(payload)
        # Same notification path as an MQTT update, so the dropdown lands on the confirmed
        # value and drops its optimistic guess exactly as it would on a device push.
        self.async_set_updated_data(self._snapshot())
        return self.gcs_state.warmup_mode

    # ------------------------------------------------------------------ #
    # Warmup auto-restore
    # ------------------------------------------------------------------ #
    @property
    def warmup_auto_restore(self) -> bool:
        """Whether to put the warmup mode back after something else disables it.

        Read live from the entry options, like `restart_on_runtime_cutoff`, so the switch
        takes effect immediately. Off unless explicitly enabled.
        """
        return bool(self.entry.options.get(CONF_WARMUP_AUTO_RESTORE, False))

    @property
    def last_warmup_mode(self) -> str | None:
        """The last *enabled* warmup mode seen on the valve, or None if we have never seen one.

        Persisted in the entry options so a restore after a Home Assistant restart reinstates
        the mode the fixture actually had. `None` is a real answer and is treated as one: with
        no prior, auto-restore does nothing rather than picking a default, because "all
        outlets" and "selected outlets" are different fixtures' worth of water.
        """
        stored = self.entry.options.get(CONF_LAST_WARMUP_MODE)
        return stored if stored in WARMUP_MODES_CURRENT else None

    @callback
    def _remember_message(self, envelope: Envelope) -> None:
        """Keep a light record of every message, for the warmup journal's context windows.

        Deliberately small: a code, a sku, a timestamp, and — only for the valve's own status
        message — the four fields that tell a configuration write apart from an ordinary
        status. The raw capture beside this holds every payload in full; duplicating it here
        would make the journal unreadable for the one thing it is for.
        """
        record: dict[str, Any] = {
            # The same stamp shape the journal and the raw capture use, so the three sort
            # together on one clock.
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "at": time.monotonic(),
            "sku": envelope.sku,
            "code": envelope.code,
        }
        if envelope.code == MSG_GCS_SOLO_STATUS:
            attribute = envelope.attribute() or {}
            for key in (
                "configChangeIndent",
                "configWriteAllowedFlag",
                "currentSystemState",
                "warmUpStatus",
            ):
                if key in attribute:
                    record[key] = attribute[key]
        self._recent_messages.append(record)

    def _message_window(self, since: float, until: float | None = None) -> list[dict]:
        """Messages between two monotonic instants, oldest first, without the clock field."""
        return [
            {k: v for k, v in item.items() if k != "at"}
            for item in self._recent_messages
            if item["at"] >= since and (until is None or item["at"] <= until)
        ]

    @callback
    def _warmup_journal(self, event: str, **fields: Any) -> None:
        """Append to the warmup journal. Mirrors `_journal`, including the deferred open."""
        if self.warmup_log is None:
            return
        self.warmup_log.note(event, **fields)
        if self.warmup_log.wants_open:
            self.hass.async_add_executor_job(self.warmup_log.prepare)

    async def _async_journal_warmup_context(self, at: float) -> None:
        """Record what arrived *after* a disable.

        Separate from the disable record because the most distinctive marker seen so far —
        `SYSTEM_STS: SYSTEM_READY` — landed 7 to 9 s afterwards in the two clearest of the
        four known cases. A record written at the moment of the disable cannot contain it.
        """
        await asyncio.sleep(WARMUP_CONTEXT_AFTER_SECONDS)
        state = self.gcs_state
        self._warmup_journal(
            "context",
            after_window=self._message_window(at),
            window_seconds=WARMUP_CONTEXT_AFTER_SECONDS,
            mode_now=None if state is None else state.warmup_mode,
        )

    @callback
    def _remember_warmup_mode(self, mode: str) -> None:
        """Record an enabled mode as what auto-restore should reinstate.

        Called from three directions, because any one of them alone leaves a gap:

        * **The valve announcing a mode over MQTT.** Alone, it forgets a mode chosen while
          the stream was down.
        * **A write of ours confirming.** Alone, it forgets a mode set from the Konnect app
          or the touchscreen — and those are most of them.
        * **The REST seed at setup** (``_async_seed_state``). Alone, neither of the other two
          knows about a mode that was simply already in force when the integration started.
          Added 2026-08-21: its absence cost a seven-hour unrestored disable on 08-20, since
          a mode read but never announced left auto-restore with no target.

        Seeing an enabled mode also ends any fight in progress: the counter that stops an
        endless restore loop is reset here, because the mode staying enabled is exactly the
        outcome that counter exists to wait for.
        """
        if mode == WARMUP_DISABLED:
            return
        self._warmup_restores = 0
        self._warmup_restored_at = None
        if mode != self.entry.options.get(CONF_LAST_WARMUP_MODE):
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, CONF_LAST_WARMUP_MODE: mode},
            )

    def _warmup_write_status(self, after: str | None) -> tuple[float | None, bool]:
        """How long ago we last wrote a warmup mode, and whether ``after`` was that write.

        The pair every warmup observation needs, whichever channel it arrived on:
        ``write_age`` feeds ``should_restore_warmup``'s self-write grace, and ``ours`` is
        the journal's answer to "did we do this?" — true only when the observed mode matches
        the mode we wrote and the write is recent enough to be the cause.
        """
        write_age = (
            None
            if self._warmup_self_write_at is None
            else time.monotonic() - self._warmup_self_write_at
        )
        ours = (
            self._warmup_self_write_mode == after
            and write_age is not None
            and write_age <= WARMUP_SELF_WRITE_GRACE_SECONDS
        )
        return write_age, ours

    def _schedule_warmup_restore(self, taken_away: str | None) -> None:
        """Spawn one restore task, or record why not.

        Shared by both callers — the MQTT announcement path and the reseed discovery path —
        because two restores in flight would race `async_set_warmup` against itself over a
        single field, and the journal should say a second trigger arrived rather than let
        the tasks interleave silently.
        """
        if self._warmup_restore_task is not None and not self._warmup_restore_task.done():
            self._warmup_journal("restore_skipped", reason="a restore is already pending")
            return
        self._warmup_restore_task = self.hass.async_create_task(
            self._async_restore_warmup(taken_away)
        )

    @callback
    def _handle_warmup_mode_change(
        self, before: str | None, after: str | None, *, announced: bool = False
    ) -> None:
        """React to the valve announcing a new warmup mode.

        Two jobs: remember any enabled mode as the restore target, and notice a transition
        *into* disabled that this integration did not cause.

        ``announced`` says this envelope was a `GCS_WARM_STS` — the valve volunteering its
        mode — as opposed to any of the other messages that reach this method unchanged.
        It only matters when the mode did **not** move; a change can come from nowhere else,
        since `_apply_warmup` is the only envelope handler that writes `warmup_mode`.
        """
        record = journal_event(before, after, announced=announced)
        if record is None:
            return

        # Computed before the branch because **an announcement needs `ours` just as much as a
        # transition does** — see the note on the `announced` record below.
        write_age, ours = self._warmup_write_status(after)

        if record == "announced":
            # The valve restating a mode it is already in.
            #
            # ⚠️ **Most of these are our own dropdown writes, and the journal has to say so.**
            # Measured live 2026-08-21: `async_set_warmup` reads the mode back over REST at
            # `WARMUP_READBACK_DELAYS = (0.0, 2.0, 4.0)`, and the first of those is immediate,
            # so `apply_rest_state` has already moved `warmup_mode` by the time the valve's
            # own echo lands ~3.4 s later. `before == after`, and what would have been a
            # `mode` record with `ours: true` arrives here instead. Two dropdown changes that
            # evening produced exactly this, at +0.81 s and +0.33 s after their readbacks.
            #
            # Without `ours` the whole class is indistinguishable from the valve volunteering
            # its state — which is the one distinction §3e's open question turns on.
            #
            # Deliberately does not fall through to the disable path: a repeat of
            # `warmUpDisabled` is not a fresh disable, and `should_restore_warmup` would
            # refuse it anyway — but relying on that implicitly is how a restore loop starts.
            self._warmup_journal("announced", mode=after, ours=ours, source="mqtt")
            return

        # Every announcement is journalled, not only the disables. Establishing what a normal
        # week looks like is half of recognising the abnormal event.
        #
        # ⚠️ **That sentence was false from the day it was written until 2026-08-21.** Only
        # *changes* reached this line; a repeat returned above, and the mode a file opened on
        # was never recorded at all. Both are covered now — the `announced` record above and
        # the `baseline` record in `async_setup` — so it is true as stated. Check all three
        # before trusting it again.
        self._warmup_journal(
            "mode", before=before, after=after, ours=ours, source="mqtt"
        )

        if after != WARMUP_DISABLED:
            self._remember_warmup_mode(after)
            return

        restoring = should_restore_warmup(
            before,
            after,
            enabled=self.warmup_auto_restore,
            self_write_mode=self._warmup_self_write_mode,
            self_write_age=write_age,
            grace_seconds=WARMUP_SELF_WRITE_GRACE_SECONDS,
        )
        now = time.monotonic()
        state = self.gcs_state
        self._warmup_journal(
            "disabled",
            before=before,
            ours=ours,
            restoring=restoring,
            auto_restore=self.warmup_auto_restore,
            restores_to=restore_target(before, self.last_warmup_mode),
            water_running=None if state is None else state.is_running,
            before_window=self._message_window(now - WARMUP_CONTEXT_BEFORE_SECONDS, now),
            window_seconds=WARMUP_CONTEXT_BEFORE_SECONDS,
        )
        # The after-window is worth having whether or not we restore — an unrestored disable
        # is the cleaner observation of the two, since nothing of ours is in the way.
        self.hass.async_create_task(self._async_journal_warmup_context(now))

        if not restoring:
            return
        self._schedule_warmup_restore(before)

    async def _async_restore_warmup(self, taken_away: str | None = None) -> None:
        """Wait out the delay, re-check, and put the mode back.

        Re-checks rather than cancels: during the wait the mode may have been re-enabled by
        hand, the switch turned off, or the shower started. Every one of those means do
        nothing, and asking at the end is simpler than keeping a cancellation path correct
        for each.

        ``taken_away`` is the mode the disable moved *away* from, and it is the restore
        target. ``should_restore_warmup`` refuses unless ``before`` is a known enabled mode,
        so whenever a restore is scheduled that value is present and is the most current
        answer available — more current than ``last_warmup_mode``, which is a persisted
        memory that can be older or, before 2026-08-21, absent entirely.

        ⚠️ **It used to restore to ``last_warmup_mode`` alone, and that had a seven-hour
        failure on 2026-08-20.** The valve was disabled out of
        ``warmUpAllOutletsWithNoStartDelay``; the decision function said restore; the journal
        recorded ``"before": "warmUpAllOutletsWithNoStartDelay"`` and ``"restores_to": null``
        in the same entry — because no enabled mode had been *announced* during that
        integration session, only read over REST at setup. The mode being taken away was in
        hand the whole time and was thrown away. Seeding from REST (see
        ``_async_seed_state``) closes the same gap from the other side.
        """
        target = restore_target(taken_away, self.last_warmup_mode)
        if target is None:
            # Now unreachable for a genuine disable — kept because it is cheap, and because
            # a future caller that passes nothing should say so rather than write a default.
            _LOGGER.warning(WARMUP_AUTO_RESTORE_NO_TARGET)
            self._warmup_journal(
                "restore_skipped", reason="no enabled mode has ever been seen"
            )
            return

        if (
            self._warmup_restores >= WARMUP_AUTO_RESTORE_MAX_CONSECUTIVE
            and self._warmup_restored_at is not None
            and time.monotonic() - self._warmup_restored_at
            < WARMUP_AUTO_RESTORE_SETTLED_SECONDS
        ):
            self._warmup_journal(
                "restore_skipped",
                reason="gave up after %d restores that did not stick"
                % WARMUP_AUTO_RESTORE_MAX_CONSECUTIVE,
            )
            return

        self._warmup_journal(
            "restore_scheduled",
            target=target,
            delay_seconds=WARMUP_AUTO_RESTORE_DELAY_SECONDS,
        )
        await asyncio.sleep(WARMUP_AUTO_RESTORE_DELAY_SECONDS)

        if not self.warmup_auto_restore:
            self._warmup_journal("restore_skipped", reason="switched off during the wait")
            return
        state = self.gcs_state
        if state is None or state.warmup_mode != WARMUP_DISABLED:
            # Someone got there first. Nothing to do, and saying so beats a silent return
            # when the owner is watching the log to see whether this feature works.
            _LOGGER.info(
                "Warmup was re-enabled before auto-restore ran; leaving it alone"
            )
            self._warmup_journal(
                "restore_skipped",
                reason="re-enabled during the wait",
                mode_now=None if state is None else state.warmup_mode,
            )
            return

        self._warmup_restores += 1
        self._warmup_restored_at = time.monotonic()
        if self._warmup_restores > WARMUP_AUTO_RESTORE_MAX_CONSECUTIVE:
            _LOGGER.warning(
                WARMUP_AUTO_RESTORE_GIVING_UP, WARMUP_AUTO_RESTORE_MAX_CONSECUTIVE
            )
            self._warmup_journal(
                "restore_gave_up", attempts=WARMUP_AUTO_RESTORE_MAX_CONSECUTIVE
            )
            return

        _LOGGER.warning(
            "Warmup was disabled by something other than Home Assistant. Setting it back "
            "to %s (attempt %d).",
            target,
            self._warmup_restores,
        )
        self._warmup_journal("restore", target=target, attempt=self._warmup_restores)
        try:
            await self.async_set_warmup(target)
        except HomeAssistantError as err:
            # Not retried. The known refusal is water running, and a shower is exactly when
            # nobody wants this fighting the valve; the next disable will schedule another.
            _LOGGER.warning("Warmup auto-restore could not write: %s", err)
            self._warmup_journal("restore_failed", target=target, error=str(err))
            return
        self._warmup_journal(
            "restore_done",
            target=target,
            attempt=self._warmup_restores,
            mode_now=None if self.gcs_state is None else self.gcs_state.warmup_mode,
        )

    async def async_activate_favorite(self, favorite_id: Any, name: str) -> None:
        """Start a controller favourite. **This runs water.**

        The controller's only way to set water state: it has no direct temperature/outlet
        command, so a favourite is created holding that configuration and then activated.
        Activation is allowed even while something else is running.
        """
        if self.hub is None:
            raise HomeAssistantError("No Anthem Plus controller on this account")
        try:
            await self.hub.async_activate_favorite(favorite_id, name, True)
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem Plus controller is offline. Check that it is powered on and "
                "connected, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

    @property
    def hub_water_is_running(self) -> bool | None:
        """Whether the **controller** believes water is running. Never asks the valve.

        This is deliberately the controller's own, possibly wrong, view — and the entities
        on the Anthem Plus device are the one place that is the right answer. They are
        answering "what does this controller think it is doing", and a controller that has
        not been told about a session is not doing anything: its ``stopall`` and
        ``valvecontrol OFF`` have nothing to stop, and its own timers are not counting.

        **This replaced a valve-backed property on 2026-08-18, because that produced a false
        positive.** `resolve_outlet_source()` is right that the valve owns the *physical*
        water state, and the Anthem Valve entities read it. But feeding it to the
        controller's switches made them report a system the controller knew nothing about.
        Measured that day: a 86-minute GCS-driven shower — open at 07:52:01 local, the
        valve's 3600 s pause and our restore at 08:52, stopped by hand at 09:18 — during
        which the controller published **not one message of any kind**, `SHOWER_VALVE_STS`
        included. The capture holds five `GCS_SOLO_STS` messages and nothing else. Both
        controller switches nonetheless tracked the shower perfectly, which looked like
        health and was actually the valve wearing the controller's name.

        Read from the outlet arrays rather than ``HubState.is_running``'s zone ``status``
        so this agrees exactly with the ``ControllerOutletSensor`` binary sensors — the
        Shower switch is on if and only if one of those outlet rows is on. The two sources
        do not disagree in any capture; matching them is about the dashboard being
        self-consistent, not about correctness.

        ``None`` — "unknown", not "off" — until the controller has reported a zone at all,
        since an empty ``zones`` map pads to all-False and would otherwise read as a
        confident "no water".
        """
        state = self.hub_state
        if state is None or not state.zones:
            return None
        return any(state.outlets)

    async def async_set_hub_shower(self, on: bool) -> None:
        """Run or stop the controller's own default shower. **On runs water.**

        ``valvecontrol {valveOnOff}`` — the controller's one direct water command, and the
        only place in the system where a bare on/off exists. It works because the controller
        stores its own default configuration; the GCS valve has no equivalent, which is why
        the valve's shower switch has to name a preset instead.

        Off stops the water only, leaving music, steam, and lighting running. Use
        :meth:`async_stop_hub` to idle everything.
        """
        if self.hub is None:
            raise HomeAssistantError("No Anthem Plus controller on this account")
        try:
            await self.hub.async_set_shower(on)
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem Plus controller is offline. Check that it is powered on and "
                "connected, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

    async def async_stop_hub(self) -> None:
        """Stop everything the controller is running — water, steam, music, lighting.

        Uses ``stopall`` rather than deactivating the active favourite, because the
        favourite may already have been replaced by whatever is running now, and a stop
        should not depend on correctly identifying what to stop.
        """
        if self.hub is None:
            raise HomeAssistantError("No Anthem Plus controller on this account")
        try:
            await self.hub.async_stop_all()
        except DeviceOffline as err:
            raise HomeAssistantError(
                "The Anthem Plus controller is offline. Check that it is powered on and "
                "connected, then try again."
            ) from err
        except KohlerError as err:
            raise HomeAssistantError(f"Kohler command failed: {err}") from err

