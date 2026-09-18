"""Event-driven reachability with bounded recovery reads, never silence verdicts."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .anthem_plus import AuthError, AuthUnavailable, DeviceOffline, KohlerError
from .anthem_plus.connectivity import RecoveryBackoff, error_label, local_hostname
from .anthem_plus.const import MSG_HUB_SHOWER_VALVE
from .const import CLOUD_CHECK_COOLDOWN_SECONDS, CLOUD_CHECK_PAIR_WINDOW_SECONDS, CLOUD_CHECK_QUIET_SECONDS

_LOGGER = logging.getLogger(__name__)
CONNECTED = "connected"


def _utc_iso(stamp: float | None) -> str | None:
    return None if stamp is None else datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


class CloudConnectionWatch:
    """One device's cloud verdict; HUBs also have local and valve-link evidence."""

    def __init__(self, coordinator: Any, device: Any, *, controller: bool = False) -> None:
        self._coordinator = coordinator
        self._device = device
        self._hass = coordinator.hass
        self._is_controller = controller
        self._state_endpoint = "hub-state" if controller else "gcs-state"
        self._device_label = "controller" if controller else "valve"
        self._connected: bool | None = None
        self._local: bool | None = None
        self._reported: str | None = None
        self._checked_at: float | None = None
        self._trigger: str | None = None
        self._last_error: str | None = None
        self._stale = True
        self._last_device_at: float | None = None
        self._last_check_at: float | None = None
        self._generation = 0
        self.state_ready = False
        self.warmup_ready = False
        self.favorite_ready = False
        self.needs_reseed = True
        self._outage_reported = False
        self.hostname: str | None = None
        self.links: dict[int, bool | None] = {1: None}
        self.links_stale = True
        self.link_error: str | None = None
        self.links_checked: float | None = None
        self._backoff = RecoveryBackoff()
        self._next_check: float | None = None
        self._pending_check: str | None = None
        self._pair_cancel = self._quiet_cancel = self._retry_cancel = None
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._auth_blocked = False

    @property
    def cloud_connected(self) -> bool | None:
        return self._connected

    @property
    def connected(self) -> bool | None:
        if self._is_controller and self._local is True:
            return True
        return self._connected

    @property
    def operational(self) -> bool:
        stream = self._coordinator.stream
        return bool(
            not self._stopped and not self._auth_blocked
            and stream and stream.connected and self._connected is True
            and not self._stale and self.state_ready
            and getattr(self._coordinator.client, "cloud_available", True)
        )

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            "cloud_connection": self._reported,
            "answer_source": "local" if self._is_controller and self._local is True else self._trigger,
            "last_checked": _utc_iso(self._checked_at),
            "stale": self._stale and self._local is not True,
            "last_error": self._last_error,
            "next_check": _utc_iso(self._next_check),
        }

    def journal(self, event: str, **fields: Any) -> None:
        fn = getattr(self._coordinator, "connectivity_event", None)
        if fn:
            fn(event, device_id=self._device.device_id, device_kind=self._device_label, **fields)

    def _notify(self) -> None:
        if not self._stopped:
            self._coordinator.async_refresh_entities()

    def async_start(self) -> None:
        self._stopped = False
        self._arm_quiet_timer()
        if self._connected is False or self._last_error or self.needs_reseed:
            self._schedule_retry()

    def async_stop(self) -> None:
        self._stopped = True
        self._next_check = self._pending_check = None
        for name in ("_pair_cancel", "_quiet_cancel", "_retry_cancel"):
            cancel = getattr(self, name)
            if cancel:
                cancel()
            setattr(self, name, None)
        if self._task and not self._task.done():
            self._task.cancel()

    def _invalidate(self, reason: str) -> None:
        self.state_ready = False
        self.warmup_ready = False
        self.favorite_ready = False
        self.needs_reseed = True
        fn = getattr(self._device, "connectivity_lost", None)
        if fn:
            fn(reason)

    def transport_lost(self, reason: str) -> None:
        self._generation += 1
        self._stale = True
        self._local = None
        self.links_stale = True
        self._last_error = reason
        self._invalidate(reason)
        self._schedule_retry()
        self._notify()

    def auth_required(self) -> None:
        self._auth_blocked = True
        self.transport_lost("reauthentication required")
        if self._retry_cancel:
            self._retry_cancel()
            self._retry_cancel = None
        self._next_check = None

    def note_offline(self, reason: str = "device reported offline") -> None:
        first = self._connected is not False
        self._generation += 1
        self._connected = False
        self._reported = "Disconnected"
        self._stale = False
        self._last_error = None
        self._local = None
        self._checked_at = time.time()
        self._trigger = reason
        self._invalidate(reason)
        if first:
            _LOGGER.warning("Kohler %s %s is unreachable through the cloud", self._device_label, self._device.device_id)
            self.journal("device_disconnected", reason=reason)
            self._outage_reported = True
        self._schedule_retry()
        self._notify()

    def _note_device_message(self) -> None:
        returning = self._connected is not True or self._stale or self.needs_reseed
        self._generation += 1
        self._last_device_at = time.monotonic()
        self._connected = True
        self._reported = "Connected"
        self._local = None
        self._stale = False
        self._last_error = None
        self._trigger = "mqtt"
        self._checked_at = time.time()
        self._arm_quiet_timer()
        if returning:
            self.journal("device_returned", source="mqtt")
            recovery = getattr(self._coordinator.client, "request_recovery", None)
            if recovery:
                recovery()
            self._request_check("MQTT recovery", force=True)
        self._notify()

    def note_gcs_message(self) -> None:
        self._note_device_message()
        if self._pair_cancel:
            self._pair_cancel()
            self._pair_cancel = None

    def note_hub_message(self) -> None:
        self._note_device_message()

    def note_hub_envelope(self, envelope: Any) -> None:
        if self._is_controller or envelope.code != MSG_HUB_SHOWER_VALVE:
            return
        if not any(isinstance(a, dict) and a.get("status") == "ON" for a in envelope.attributes):
            return
        if self._last_device_at is not None and time.monotonic() - self._last_device_at <= CLOUD_CHECK_PAIR_WINDOW_SECONDS:
            return
        if self._pair_cancel is None:
            self._pair_cancel = async_call_later(self._hass, CLOUD_CHECK_PAIR_WINDOW_SECONDS, self._pair_window_elapsed)

    @callback
    def _pair_window_elapsed(self, _now: Any) -> None:
        self._pair_cancel = None
        self._request_check("controller reported a zone ON, valve silent")

    def _arm_quiet_timer(self) -> None:
        if self._stopped:
            return
        if self._quiet_cancel:
            self._quiet_cancel()
        self._quiet_cancel = async_call_later(self._hass, CLOUD_CHECK_QUIET_SECONDS, self._quiet_elapsed)

    @callback
    def _quiet_elapsed(self, _now: Any) -> None:
        self._quiet_cancel = None
        if self._retry_cancel is None:
            self._request_check(f"three hours without a {self._device_label} message")
        self._arm_quiet_timer()

    def _schedule_retry(self) -> None:
        if self._stopped or self._auth_blocked or self._retry_cancel:
            return
        delay = self._backoff.fail(minimum=getattr(self._coordinator.client, "cloud_retry_delay", 0))
        if not self._backoff.long_reported and time.monotonic() - self._backoff.since >= 86400:
            self._backoff.long_reported = True
            _LOGGER.info("Kohler %s remains unavailable; checking hourly", self._device.device_id)
            self.journal("long_outage", retry_in=delay)
        self.journal("retry_scheduled", retry_in=delay)
        self._next_check = time.time() + delay
        self._retry_cancel = async_call_later(self._hass, delay, self._retry_elapsed)

    @callback
    def _retry_elapsed(self, _now: Any) -> None:
        self._retry_cancel = None
        self._next_check = None
        self._request_check("recovery check", force=True)

    def _request_check(self, trigger: str, *, force: bool = False) -> None:
        if self._stopped or self._auth_blocked:
            return
        if self._task and not self._task.done():
            if force and trigger in ("MQTT recovery", "cloud service returned"):
                self._pending_check = trigger
            return
        now = time.monotonic()
        if not force and self._last_check_at is not None and now - self._last_check_at < CLOUD_CHECK_COOLDOWN_SECONDS:
            return
        self._last_check_at = now
        self._task = self._hass.async_create_task(self._async_check(trigger))
        self._task.add_done_callback(self._check_done)

    def _check_done(self, task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            _LOGGER.error("Kohler connectivity check failed unexpectedly: %s", error_label(task.exception()))
        trigger, self._pending_check = self._pending_check, None
        if trigger and self.needs_reseed:
            self._request_check(trigger, force=True)

    async def async_check_now(self, trigger: str = "manual refresh") -> None:
        self._request_check(trigger, force=True)
        if self._task:
            await self._task

    async def _async_local_probe(self) -> None:
        generation = self._generation
        controllers = self._coordinator.controllers
        hostname = self.hostname or ("kohler-myshower.local" if len(controllers) == 1 else None)
        if not hostname or sum(1 for c in controllers if getattr(getattr(c, "cloud_watch", None), "hostname", None) == hostname) > 1:
            self._local = None
            self.journal("local_probe_skipped", reason="no unambiguous local hostname")
            return
        try:
            session = getattr(self._coordinator.client, "_session", None)
            if session is None or getattr(session, "closed", False):
                self._local = None
                self.journal("local_probe_skipped", reason="HTTP session unavailable")
                return
            async with session.get(
                f"http://{hostname}/web/api/v1/device/get_hub_version_info",
                timeout=aiohttp.ClientTimeout(total=3), allow_redirects=False,
                headers={"Content-Type": "application/json", "random_uuid": str(uuid.uuid4())},
            ) as response:
                if response.status != 200:
                    raise ValueError("local status")
                payload = await response.json()
                reachable = isinstance(payload, dict) and isinstance(payload.get("version"), str) and bool(payload["version"].strip())
        except (aiohttp.ClientError, TimeoutError, ValueError, RuntimeError):
            reachable = False
        if generation != self._generation or self._stopped:
            return
        self._local = reachable
        if reachable:
            self._checked_at = time.time()
        self.journal("local_probe_result", reachable=self._local)

    async def _async_check(self, trigger: str) -> None:
        generation = self._generation
        self.journal("check_started", reason=trigger)
        try:
            getter = self._coordinator.client.async_get_hub_state if self._is_controller else self._coordinator.client.async_get_gcs_state
            payload = await getter(self._device.device_id)
            if generation != self._generation or self._stopped:
                self.journal("check_superseded", reason="newer device evidence")
                return
            self.note_rest_payload(payload, trigger, notify=False)
            if self._connected is True and self.needs_reseed:
                apply = getattr(self._coordinator, "async_reconcile_device", None)
                if apply:
                    await apply(self._device, payload, generation)
            if self._is_controller:
                if self._connected is True:
                    await self.async_read_links()
                else:
                    self.links_stale = True
        except DeviceOffline:
            if generation == self._generation and not self._stopped:
                self.note_offline()
        except AuthError as err:
            if not isinstance(err, AuthUnavailable):
                self.auth_required()
                handler = getattr(self._coordinator, "_handle_auth_error", None)
                if handler:
                    handler(err)
            else:
                self._read_failed(err)
        except (KohlerError, TimeoutError, aiohttp.ClientError) as err:
            self._read_failed(err)
        finally:
            if not self._stopped and not self._auth_blocked:
                if self._is_controller and (self._connected is not True or self._stale):
                    await self._async_local_probe()
                unresolved = self._connected is not True or self._stale or self.needs_reseed
                unresolved |= self._is_controller and (self.links_stale or any(v is False for v in self.links.values()))
                if unresolved:
                    self._schedule_retry()
                else:
                    self._recovered()
                self._notify()

    def _read_failed(self, err: BaseException) -> None:
        self._last_error = error_label(err)
        self._stale = True
        self._invalidate(self._last_error)
        self.journal("check_failed", error=self._last_error)

    def _recovered(self) -> None:
        if self._retry_cancel:
            self._retry_cancel()
            self._retry_cancel = None
        if self._backoff.since is not None:
            if self._outage_reported:
                self.journal("recovered")
                # WARNING to match the "is unreachable" onset; see the note in `coordinator.py`.
                _LOGGER.warning("Kohler %s connectivity recovered", self._device.device_id)
            else:
                # `async_start` primes the backoff on every fresh watcher, because
                # `needs_reseed` is true before the first seed, so the first successful
                # check always lands here. Nothing was announced as lost, so announcing a
                # recovery would tell every user their cloud came back at each Core restart.
                _LOGGER.debug("Kohler %s connectivity settled; no outage had been announced", self._device.device_id)
        self._outage_reported = False
        self._backoff.reset()
        self._next_check = None

    def note_rest_payload(self, payload: Any, trigger: str, *, notify: bool = True) -> None:
        reported = payload.get("connectionState") if isinstance(payload, dict) else None
        if not isinstance(reported, str) or not reported.strip():
            self._last_error = f"{self._state_endpoint} carried no connectionState field"
            self._stale = True
            self._schedule_retry()
        elif reported.lower() != CONNECTED:
            self.note_offline(trigger)
            self._reported = reported
        else:
            self._connected = True
            self._reported = reported
            self._checked_at = time.time()
            self._trigger = "cloud"
            self._local = None
            self._stale = False
            self._last_error = None
        if notify:
            self._notify()

    async def async_read_links(self) -> None:
        generation = self._generation
        try:
            payload = await self._coordinator.client.async_get_hub_configuration(self._device.device_id)
            if generation == self._generation and not self._stopped:
                self.note_configuration(payload)
        except (KohlerError, AuthUnavailable) as err:
            self.links_stale = True
            self.link_error = error_label(err)
            self.journal("link_check_failed", error=self.link_error)

    def note_configuration(self, payload: Any) -> None:
        config = payload.get("configuration") if isinstance(payload, dict) else None
        if not isinstance(config, dict):
            self.links_stale = True
            self.link_error = "missing HUB configuration"
            return
        about = config.get("about")
        hub = about.get("hub") if isinstance(about, dict) else None
        hostname = local_hostname(hub.get("hubname")) if isinstance(hub, dict) else None
        if hostname:
            self.hostname = hostname
        parts = config.get("parts")
        if not isinstance(parts, dict):
            self.links_stale = True
            self.link_error = "missing valve-link status"
            return
        before = dict(self.links)
        incomplete = False
        for port, alias in ((1, "valveOne"), (2, "valveTwo")):
            value = parts.get(f"valve{port}") or parts.get(alias)
            if port == 2 and port not in self.links and str(value).lower() != CONNECTED:
                continue
            if isinstance(value, str) and value:
                self.links[port] = value.lower() == CONNECTED
            else:
                incomplete = True
        self.links_stale = incomplete or self._connected is not True or any(v is None for v in self.links.values())
        self.link_error = "incomplete or stale valve-link status" if self.links_stale else None
        self.links_checked = time.time()
        if before != self.links:
            self.journal("valve_link_changed", links=dict(self.links))
            hook = getattr(self._coordinator, "remember_controller_ports", None)
            if hook:
                hook(self._device)
        if any(v is False for v in self.links.values()):
            self._schedule_retry()
