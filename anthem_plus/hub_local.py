"""Liveness probe for the Anthem Plus controller's local HTTP server.

# =====================================================================
# HUB LOCAL PROBE — diagnostic, OFF unless a host is configured
# =====================================================================
#
#   grep -rn "HUB LOCAL PROBE" custom_components/kohler_anthem_plus/
#
# =====================================================================

**This measures reachability, not health.** It exists to answer one question the cloud
stream cannot: *when the valve reboots, does the controller go down with it?* Everything
else about the controller already arrives over MQTT, and better.

The endpoint is `get_hub_running_state`, chosen for one reason only — it is on the local
API's **pre-auth allow-list**, so no PIN, no JWT, and no token expiry to manage. Its payload
describes the *shower*, not the controller, and is deliberately **discarded**: the cloud
already reports shower state, and a second source would only invite disagreement. What
matters is whether the HTTP server answered at all.

So the states are:

* **reachable** — the request completed, whatever it said.
* **unreachable** — timeout, connection refused, DNS failure, or a non-200 status.

A controller that is rebooting cannot serve HTTP, so an outage here is a strong signal that
the controller restarted, and its *duration* is roughly how long it was down.

Polling is fast on purpose (see `HUB_LOCAL_POLL_SECONDS`). This is a local HTTP GET on the
LAN, and the controller's own web UI fires this same endpoint before every POST it makes, so
the call pattern is one the device already expects. It is still the only polling loop in an
otherwise push-only integration, and it is off unless a host is configured.

Nothing here writes. The local API cannot actuate the valve on firmware 2.88 in any case —
see `docs/hub/local_api.md` — but this module restricts itself to a single GET regardless.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

import aiohttp

_LOGGER = logging.getLogger(__name__)

#: The pre-auth endpoint used purely as a ping. Its body is ignored.
PROBE_PATH = "/web/api/v1/device/get_hub_running_state"

#: How long a single probe may take before it counts as unreachable. Deliberately shorter
#: than the poll interval would suggest is safe: a controller that is up answers this in
#: milliseconds on a LAN, so anything approaching a second is already abnormal.
PROBE_TIMEOUT_SECONDS = 2.0

#: Consecutive failures before "unreachable" is declared. One dropped packet on Wi-Fi is not
#: an outage; three in a row at 1 Hz is three seconds of silence from a device that normally
#: answers instantly.
FAILURES_BEFORE_DOWN = 3


@dataclass
class HubOutage:
    """One period during which the controller stopped answering."""

    started: float
    ended: float | None = None

    @property
    def seconds(self) -> float | None:
        return None if self.ended is None else self.ended - self.started


@dataclass
class HubLocalProbe:
    """Polls the controller's local HTTP server and records when it stops answering.

    Reachability only — see the module docstring for why the response body is discarded.
    """

    session: aiohttp.ClientSession
    host: str
    interval: float = 1.0
    #: Called with no arguments whenever the up/down state changes, so entities refresh
    #: promptly rather than on the next coordinator push.
    on_change: object = None

    #: Called with the completed `HubOutage` each time one ends, so the consumer can persist
    #: it. Kept separate from `on_change` because that fires on both edges, and only a
    #: *completed* outage is worth writing to storage.
    on_outage_complete: object = None

    #: Outages that ended before this process started, restored by the consumer from
    #: persistent storage. This class does no I/O of its own — it has no Home Assistant
    #: imports and must stay that way — so the count is handed to it rather than loaded.
    baseline_outages: int = 0
    baseline_last_ended: float | None = None
    baseline_last_seconds: float | None = None

    reachable: bool | None = None
    consecutive_failures: int = 0
    last_ok: float | None = None
    last_failure: float | None = None
    #: Every completed outage *this process has seen*, plus the current one while it runs.
    #: Deliberately not seeded from the baseline: durations and timestamps of old outages
    #: belong in the log, and keeping them here would make `outages[-1]` lie about what is
    #: in progress.
    outages: list[HubOutage] = field(default_factory=list)
    _task: asyncio.Task | None = None
    _stop: bool = False

    # ------------------------------------------------------------------ #
    @property
    def outage_count(self) -> int:
        """Outages that have *ended*, including ones from before this process started.

        An in-progress outage is not counted until it ends, so the figure never moves
        backwards when one is running.
        """
        return self.baseline_outages + sum(1 for o in self.outages if o.ended is not None)

    @property
    def current_outage_seconds(self) -> float | None:
        """How long the controller has been unreachable, or None if it is answering."""
        if not self.outages or self.outages[-1].ended is not None:
            return None
        return time.time() - self.outages[-1].started

    @property
    def last_outage_seconds(self) -> float | None:
        """Duration of the most recent *completed* outage, restart included."""
        for outage in reversed(self.outages):
            if outage.ended is not None:
                return outage.seconds
        return self.baseline_last_seconds

    @property
    def last_outage_ended(self) -> float | None:
        """Unix time the most recent completed outage ended, or None if none has."""
        for outage in reversed(self.outages):
            if outage.ended is not None:
                return outage.ended
        return self.baseline_last_ended

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Begin polling. Safe to call once; a second call is ignored."""
        if self._task is not None:
            return
        self._stop = False
        self._task = asyncio.create_task(self._run())
        _LOGGER.info(
            "Anthem Plus local probe started against %s every %.1fs — reachability only, "
            "to correlate controller outages with valve reboots",
            self.host,
            self.interval,
        )

    async def stop(self) -> None:
        self._stop = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        url = f"http://{self.host}{PROBE_PATH}"
        while not self._stop:
            await self._probe_once(url)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                return

    async def _probe_once(self, url: str) -> None:
        ok = False
        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT_SECONDS),
                headers={"random_uuid": str(uuid.uuid4())},
            ) as response:
                # The body is deliberately not read or parsed. A status line is proof the
                # server is alive, and the payload describes the shower rather than the
                # controller — see the module docstring.
                ok = response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            ok = False
        except asyncio.CancelledError:
            raise
        self._record(ok)

    def _record(self, ok: bool) -> None:
        now = time.time()
        was = self.reachable
        if ok:
            self.consecutive_failures = 0
            self.last_ok = now
            if was is not True:
                # Close any outage in progress before flipping state.
                if self.outages and self.outages[-1].ended is None:
                    completed = self.outages[-1]
                    completed.ended = now
                    _LOGGER.warning(
                        "Anthem Plus controller is answering again after %.0fs "
                        "unreachable — that outage looks like a controller restart. "
                        "That is #%d recorded",
                        completed.seconds or 0.0,
                        self.outage_count,
                    )
                    self._notify_outage_complete(completed)
                elif was is False:
                    _LOGGER.warning("Anthem Plus controller is answering again")
                self.reachable = True
                self._notify()
            return

        self.consecutive_failures += 1
        self.last_failure = now
        if self.reachable is not False and self.consecutive_failures >= FAILURES_BEFORE_DOWN:
            self.reachable = False
            # Date the outage from the first failure, not from when we declared it, so the
            # duration is the device's downtime rather than ours.
            self.outages.append(
                HubOutage(started=now - (self.consecutive_failures - 1) * self.interval)
            )
            _LOGGER.warning(
                "Anthem Plus controller stopped answering on %s after %d consecutive "
                "failed probes. If the valve also rebooted around now, they went down "
                "together",
                self.host,
                self.consecutive_failures,
            )
            self._notify()

    def _notify(self) -> None:
        callback = self.on_change
        if callable(callback):
            try:
                callback()
            except Exception:  # pragma: no cover - a diagnostic must not break the probe
                _LOGGER.debug("Local probe listener raised", exc_info=True)

    def _notify_outage_complete(self, outage: HubOutage) -> None:
        callback = self.on_outage_complete
        if callable(callback):
            try:
                callback(outage)
            except Exception:  # pragma: no cover - a diagnostic must not break the probe
                _LOGGER.debug("Local probe outage listener raised", exc_info=True)
