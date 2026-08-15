"""Detect the valve closing a zone because it hit its own maximum run time.

The valve enforces a `maximumRunTime` — 900 s on the reference install, 3600 s before it was
reconfigured — and shuts the water off once it has been running that long. Nothing on the
wire says "I did this because of the timer": `currentSystemState` reads `normalOperation` in
every captured status message, and a timed-out close looks exactly like someone pressing
stop.

**The timer is per ZONE, not per outlet.** This is the thing that took two attempts to get
right, so it is worth stating precisely:

* The clock starts when a zone goes from *nothing flowing* to *something flowing*.
* It **does not reset when outlets change within the zone.** Opening a second head, closing
  the first, swapping between them — none of it touches the timer.
* At the limit the valve pauses that zone (`0x40`) and clears its mask.

An earlier version of this module timed each outlet from when *that outlet* opened. It fired
correctly only when a zone happened to run one outlet, unchanged, for the whole session, and
silently missed everything else — any mid-shower outlet change resets the per-outlet clock
while the valve's own clock keeps running. Replayed over the corpus it finds 8 of the 11 real
cutoffs; in the one logged session where the owner actually moved between shower heads, it
found 1 of 4.

# ---------------------------------------------------------------------------
# Every decision this module makes is written to the cutoff debug log — including
# the ones where it decides NOT to fire, which nothing else records. When this
# feature misbehaves, read `cutoff_*.jsonl` alongside `mqtt_raw_*.jsonl` in the
# same directory; see `cutoff_log.py`.
# ---------------------------------------------------------------------------

## Why duration alone is enough to discriminate

Across **156** completed zone-open periods in the capture corpus (2026-08-07 to 08-14,
spanning the reconfiguration from a 3600 s limit to 900 s):

| | |
|---|---|
| Zone **paused** within 10 s of a limit | **11** — 899.84, 899.93, 899.95, 899.96, 900.01, 900.07, 3598.68, 3599.68, 3599.74, 3599.85, 3599.85 |
| Every other pause (54) | 1.9 s to 1831 s, none closer than **334 s** to a limit |
| Zones ended by a **stop** (`0x00`) rather than a pause (91) | none closer than **123 s** to a limit |

Every cutoff lands within **1.32 s** of its limit; the nearest pause that was not a cutoff is
over five minutes away. The two groups do not come close to touching.

Note what the third row buys: requiring the pause flag removes 91 of the 156 periods from
consideration outright, including every stop issued from Home Assistant or the Anthem Plus
controller. Duration then only has to separate 11 cutoffs from 54 other pauses.

This module only *reports*. It never sends anything, holds no Home Assistant imports, and is
deliberately separable from whatever a caller chooses to do with the answer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)


class Journal(Protocol):
    """The bit of `cutoff_log.CutoffDebugLog` this module needs.

    Declared structurally so this module keeps no import of it — the detector stays
    dependency-free and unit-testable with a list-backed stub.
    """

    def note(self, event: str, **fields: Any) -> None:  # pragma: no cover - protocol
        ...


class _NullJournal:
    """Default journal: discards everything."""

    def note(self, event: str, **fields: Any) -> None:
        return

# How far from `maximumRunTime` a pause may land and still count as the timer firing.
#
# Every cutoff ever measured landed within **1.32 s** of the limit, and all but one within
# 0.35 s. The nearest pause that was *not* a cutoff was 334 s away. So anything from about
# 2 s to 300 s "works" on the evidence, and the number is a judgement about which way to fail.
#
# It fails asymmetrically, so this is deliberately tight rather than generous:
#
# * **Too tight** — a real cutoff is missed, the water stays off, somebody turns it back on.
# * **Too loose** — a deliberate stop is mistaken for a cutoff and the water comes back on by
#   itself, which is the outcome this whole feature exists to avoid causing accidentally.
#
# 10 s is ~7.5x the worst observed jitter and still 33x clear of the nearest real pause.
#
# The case that keeps it from being looser: **a GCS-only install has no Anthem Plus**, so the
# touchscreen is the primary control surface — and a touchscreen pause writes `0x40`, exactly
# like a cutoff, with no `note_local_write()` guard because Home Assistant did not send it.
# Somebody who knows their shower cuts out at 15 minutes and pauses it at 14:55 is a
# plausible user, not a contrived one, and they must not have the water restarted on them.
CUTOFF_TOLERANCE_SECONDS = 10.0

# A close is ignored if the integration itself **closed that zone** within this window.
# Without it, stopping the shower from Home Assistant at the limit would be read as the timer
# firing and immediately undone — the integration fighting its own user.
#
# Note "closed that zone", not "wrote to the valve". Both qualifiers were learned the hard
# way on 2026-08-14, from a live shower where the second of two cutoffs was swallowed:
#
#     22:23:11  zone 1 cut at 899.8s -> restored outlets 1, 5      (correct)
#     22:23:57  Home Assistant opens outlet 4 -> zone 2 mask 2->3
#     22:24:11  zone 2 cut at 899.9s -> IGNORED, "we wrote moments ago"   (wrong)
#
# The write at 22:23:57 *opened* an outlet. An opening write cannot cause a close, so it must
# not license ignoring one. Scoping by zone matters for the same reason — adjusting zone 2
# should never blind zone 1. See `note_local_write`.
LOCAL_WRITE_GRACE_SECONDS = 30.0

# ---------------------------------------------------------------------------
# Self-diagnosis: noticing a limit we do not know about
# ---------------------------------------------------------------------------
# The bug this module was rewritten for was invisible for a day because a cutoff that fails
# to fire produces no evidence anywhere. These constants power a check that would have caught
# it from the owner's own behaviour, on the first occurrence.
#
# The idea: a *timer* repeats to the same fraction of a second; a *person* does not. So when
# several declined pauses in one zone land on the same duration, that duration is a limit
# nobody told us about. This only ever reports — see `MissedCutoffWatcher`.

# How close two declined pauses must be to count as the same duration. Real cutoffs cluster
# far tighter than this (0.22 s spread across the six 900 s ones, 1.17 s across the five
# 3600 s ones), and the nearest unrelated pause above the floor below is **334 s** away, so
# there is no meaningful risk of accidental grouping.
LIMIT_CLUSTER_TOLERANCE_SECONDS = 2.0

# Durations shorter than this are never considered. **This is the constant that makes the
# check usable at all.** Preset activation and `action:"Off"` produce short pauses that
# cluster hard — the corpus has seven within 0.4 s of 10 s, five within 0.4 s of 11 s, and
# three near 42 s — and without a floor every one of those is a false alarm. Above 300 s the
# corpus has three non-cutoff pauses total and no cluster of any size. A run-time safety
# cutoff below five minutes is not a plausible product either.
MIN_PLAUSIBLE_LIMIT_SECONDS = 300.0

# How many matching durations before saying so. Two could be coincidence; three at the same
# fraction of a second is a clock.
SUSPECTED_LIMIT_MIN_SAMPLES = 3

# A declined pause followed by the shower coming back this fast is corroborating evidence:
# nobody pauses deliberately and resumes 11 seconds later. Measured over the corpus, 10 of 11
# real cutoffs were resumed within a minute against 9 of 54 other pauses — good supporting
# evidence, too weak to trigger on alone, which is why it only annotates a cluster.
QUICK_RESUME_SECONDS = 60.0

# Bound the bookkeeping. Nothing needs more history than this to find a cluster of three.
MAX_OBSERVATIONS_PER_ZONE = 50


@dataclass(frozen=True)
class ZoneReading:
    """What a zone was actually delivering, beyond which outlets were open.

    Captured so the log can answer "what was the shower like before the cut", which the mask
    alone cannot. **Recorded, not yet acted on** — see :attr:`ZoneCutoff.flow_percent`.
    """

    #: 0-100, decoded from the flow byte (byte 2 / 2).
    flow_percent: float
    #: Degrees Fahrenheit. Always °F in this log regardless of the account's display unit,
    #: so two captures from different accounts can be compared without unit archaeology.
    temperature_f: float


@dataclass(frozen=True)
class ZoneCutoff:
    """One zone that the valve just closed on its own timer."""

    zone: int
    #: Seconds the zone had been flowing. Within `CUTOFF_TOLERANCE_SECONDS` of `limit`.
    duration: float
    #: The `maximumRunTime` this matched against.
    limit: int
    #: The outlet mask that was flowing in the instant before the valve cleared it. This is
    #: the only surviving record of what the shower was doing — the cutoff message itself
    #: reports an empty mask.
    mask: int
    #: Flow and temperature in that same instant, or None if the caller did not supply them.
    #:
    #: **Captured for the log only; the restore does not use them yet.** Measured 2026-08-14:
    #: a preset-driven shower running at 82.5% flow was cut and restored at 100%, because the
    #: restore rebuilds its command through `async_apply_valve`, which deliberately does not
    #: inherit flow. Recording the value is step one — it makes the gap visible in
    #: `cutoff_*.jsonl` before any behaviour changes.
    reading: ZoneReading | None = None


@dataclass
class MissedCutoffWatcher:
    """Spots a run-time limit nobody announced, by noticing durations that repeat.

    **Reports only.** Nothing here can open a valve. Its output is evidence for a human — or,
    once trusted, an input the caller may *choose* to act on by merging
    :attr:`learned_limits` into what it feeds :meth:`ZoneCutoffDetector.update`.

    The staging is deliberate. A limit inferred from behaviour is a weaker claim than one the
    valve announced, and the consequence of being wrong is water turning on by itself. So the
    watcher first spends a while writing down what it *would* have done, and only starts
    doing it when somebody has read those records and agreed.

    ## Two limits worth knowing before trusting it

    **It does not model a configuration change.** Observations never expire, so if the limit
    is altered in the app, the old value keeps voting and can out-vote the new one. Replaying
    the reference install's whole history demonstrates exactly this: it spans the owner
    lowering the limit from 3600 s to 900 s, and zone 2 — four cutoffs in the old era, two in
    the new — "learns" 3600 while zone 1 learns 900. Neither zone's *actual* limit is 3600.

    **State is in memory and starts empty on every restart.** Which is what contains the
    problem above, since accumulating across a config change needs Home Assistant to run
    straight through one. `ZoneCutoffDetector.forget()` deliberately leaves it alone — a
    reconnect makes durations meaningless, not observations.

    The cost of that same fact: three cutoffs are needed **within one Home Assistant run**
    before anything is learned. On an install that restarts often, this will rarely have
    anything to say. That is acceptable for what it is for — noticing a limit the valve has
    never announced — but it is not a system that gets steadily better the longer it runs.
    """

    journal: Journal = field(default_factory=_NullJournal)
    # zone -> [(duration, corroborated_by_quick_resume)]
    _seen: dict[int, list[tuple[float, bool]]] = field(default_factory=dict)
    # zone -> (monotonic time of the declined close, its duration), pending a resume check
    _pending: dict[int, tuple[float, float]] = field(default_factory=dict)
    # (zone, rounded duration) already reported, so each finding is announced once
    _announced: set[tuple[int, int]] = field(default_factory=set)

    def note_declined(self, zone: int, duration: float, now: float) -> None:
        """Record a paused close that was not treated as a cutoff."""
        if duration < MIN_PLAUSIBLE_LIMIT_SECONDS:
            return
        observations = self._seen.setdefault(zone, [])
        observations.append((duration, False))
        del observations[:-MAX_OBSERVATIONS_PER_ZONE]
        self._pending[zone] = (now, duration)

    def note_flow_start(self, zone: int, now: float) -> None:
        """Note a zone starting again, to see whether it followed a decline closely."""
        pending = self._pending.pop(zone, None)
        if pending is None:
            return
        stopped_at, duration = pending
        if now - stopped_at > QUICK_RESUME_SECONDS:
            return
        observations = self._seen.get(zone, [])
        for index in range(len(observations) - 1, -1, -1):
            if observations[index][0] == duration:
                observations[index] = (duration, True)
                break

    def _cluster(self, zone: int) -> list[list[tuple[float, bool]]]:
        clusters: list[list[tuple[float, bool]]] = []
        for observation in sorted(self._seen.get(zone, []), key=lambda o: o[0]):
            for cluster in clusters:
                if abs(cluster[0][0] - observation[0]) <= LIMIT_CLUSTER_TOLERANCE_SECONDS:
                    cluster.append(observation)
                    break
            else:
                clusters.append([observation])
        return clusters

    @property
    def learned_limits(self) -> dict[int, tuple[int, ...]]:
        """Durations that have repeated often enough to look like a timer, per zone."""
        found: dict[int, tuple[int, ...]] = {}
        for zone in self._seen:
            values = sorted(
                round(sum(d for d, _ in c) / len(c))
                for c in self._cluster(zone)
                if len(c) >= SUSPECTED_LIMIT_MIN_SAMPLES
            )
            if values:
                found[zone] = tuple(values)
        return found

    def report(self, zone: int, known: tuple[int, ...]) -> None:
        """Announce any new finding for this zone. Called after each declined close."""
        for cluster in self._cluster(zone):
            if len(cluster) < SUSPECTED_LIMIT_MIN_SAMPLES:
                continue
            seconds = round(sum(d for d, _ in cluster) / len(cluster))
            if any(abs(seconds - limit) <= CUTOFF_TOLERANCE_SECONDS for limit in known):
                continue  # already a limit we act on
            key = (zone, seconds)
            if key in self._announced:
                continue
            self._announced.add(key)
            resumed = sum(1 for _, quick in cluster if quick)
            _LOGGER.warning(
                "Zone %s has now paused %d times after about %ss, which is not a "
                "maximumRunTime this valve has announced (known: %s). That looks like a "
                "run-time limit nobody told us about — %d of those %d were followed by the "
                "shower being turned straight back on. Nothing has been restarted on the "
                "strength of it; see the cutoff debug log",
                zone,
                len(cluster),
                seconds,
                ", ".join(f"{limit}s" for limit in known) or "none",
                resumed,
                len(cluster),
            )
            self.journal.note(
                "suspected_limit",
                zone=zone,
                seconds=seconds,
                samples=len(cluster),
                quick_resumes=resumed,
                durations=[round(d, 2) for d, _ in cluster],
                known_limits=list(known),
                acted_on=False,
            )


@dataclass
class ZoneCutoffDetector:
    """Tracks how long each zone has been flowing and reports timer-driven closes.

    Feed it every valve snapshot with :meth:`update`; it returns the zones that just hit
    their limit. Timing comes from when *this process* saw the zone start flowing, so a
    restart mid-shower loses the start time and that session cannot be judged — which is the
    right failure, since guessing would mean re-opening a valve on no evidence.
    """

    #: Where the decision trail goes. See `cutoff_log.py` for why this is worth having: a
    #: cutoff that *fails to fire* produces no log line anywhere else, and that is the
    #: failure mode this feature actually has.
    journal: Journal = field(default_factory=_NullJournal)
    #: Watches for limits the valve never announced. Reports; never acts on its own.
    watcher: MissedCutoffWatcher = field(default_factory=MissedCutoffWatcher)
    # zone -> monotonic time it was first seen flowing, or absent if not flowing
    _flowing_since: dict[int, float] = field(default_factory=dict)
    # zone -> the last mask seen while flowing, so a cutoff knows what to put back
    _last_mask: dict[int, int] = field(default_factory=dict)
    # zone -> the last flow/temperature seen while flowing. Same idea as `_last_mask`: the
    # cutoff message has already overwritten them by the time the close is visible.
    _last_reading: dict[int, ZoneReading] = field(default_factory=dict)
    # zone -> monotonic time we last CLOSED it ourselves, to suppress self-inflicted
    # detections. Only closes are recorded; see `note_local_write`.
    _local_close: dict[int, float] = field(default_factory=dict)

    def note_local_write(self, masks: dict[int, int] | None = None) -> None:
        """Record a command we just sent, so a close it causes is not ours to undo.

        `masks` is what was written, per zone. **Only zones written closed (mask 0) are
        recorded**, because only those can explain a close arriving moments later. A write
        that opens outlets cannot, and treating it as though it could is what swallowed a
        real cutoff on 2026-08-14 — the restore after one zone's cutoff, and then the owner
        opening another head, each blinded the detector to the *other* zone's timer.

        Omitting `masks` records every zone, which is the cautious reading: a caller that has
        not said what it wrote might have stopped the shower, and wrongly suppressing means
        the water stays off, while wrongly firing means it comes back on by itself.
        """
        now = time.monotonic()
        if masks is None:
            # Unknown write: assume the worst, which here means assume it was a stop.
            for zone in set(self._flowing_since) | set(self._local_close) | {1, 2}:
                self._local_close[zone] = now
            return
        for zone, mask in masks.items():
            if mask:
                # An opening write. Explicitly drop any earlier suppression for this zone —
                # whatever we closed before, this zone is open again now.
                self._local_close.pop(zone, None)
            else:
                self._local_close[zone] = now

    def flowing_for(self, zone: int) -> float | None:
        """Seconds this zone has been flowing, or None if it is not, or is not being timed.

        The same clock the cutoff decision uses, so anything displaying it is showing what
        the detector actually believes rather than a second, parallel measurement that could
        disagree. None after a reconnect until the zone next starts — see :meth:`forget`.
        """
        started = self._flowing_since.get(zone)
        return None if started is None else time.monotonic() - started

    def forget(self) -> None:
        """Drop all tracking — for a reconnect, where the gap makes durations meaningless."""
        if self._flowing_since:
            self.journal.note(
                "forget",
                zones=sorted(self._flowing_since),
                reason="reconnect — durations across the gap are meaningless",
            )
        self._flowing_since.clear()
        self._last_mask.clear()
        self._last_reading.clear()

    def update(
        self,
        masks: dict[int, int],
        paused: dict[int, bool],
        limits: dict[int, tuple[int, ...]],
        readings: dict[int, ZoneReading] | None = None,
    ) -> list[ZoneCutoff]:
        """Apply a valve snapshot. Returns the zones whose run-time limit just fired.

        `masks` maps zone number to its current outlet mask, `paused` to whether that zone
        carries the `0x40` pause flag, and `limits` to the distinct `maximumRunTime` values
        configured for the outlets in that zone (empty where the valve has not said).

        A zone counts as *flowing* when it has a non-empty mask and is not paused. A cutoff
        is a flowing zone that stops flowing **while paused**, having flowed for one of its
        limits.

        Requiring the pause is what stops a deliberate stop that happens to land on the limit
        from being undone. **A run-time cutoff always pauses (`0x40`), never stops
        (`0x00`)** — it is internally the same `{preset, action:"Off"}` the cloud API
        exposes, and that pauses by definition. Measured across every known cutoff, while
        every stop issued from Home Assistant or the Anthem Plus controller wrote `0x00`.
        """
        now = time.monotonic()
        fired: list[ZoneCutoff] = []
        readings = readings or {}

        def described(zone: int) -> dict[str, Any]:
            """Flow and temperature as journal fields, or nothing if unknown."""
            reading = self._last_reading.get(zone) or readings.get(zone)
            if reading is None:
                return {}
            return {
                "flow_percent": reading.flow_percent,
                "temperature_f": reading.temperature_f,
            }

        def suppressed(zone: int) -> bool:
            """Did *we* close this zone recently enough to explain its close?"""
            closed_at = self._local_close.get(zone)
            return closed_at is not None and (now - closed_at) < LOCAL_WRITE_GRACE_SECONDS

        for zone, mask in masks.items():
            is_paused = paused.get(zone, False)
            flowing = bool(mask) and not is_paused

            if flowing:
                reading = readings.get(zone)
                if zone not in self._flowing_since:
                    self._flowing_since[zone] = now
                    # Before anything else: a zone starting again moments after a close we
                    # declined is evidence that close was not wanted.
                    self.watcher.note_flow_start(zone, now)
                    if reading is not None:
                        self._last_reading[zone] = reading
                    self.journal.note(
                        "flow_start",
                        zone=zone,
                        mask=mask,
                        limits=list(limits.get(zone, ())),
                        **described(zone),
                    )
                else:
                    was_reading = self._last_reading.get(zone)
                    if reading is not None:
                        self._last_reading[zone] = reading
                    if self._last_mask.get(zone) != mask:
                        # Worth a line of its own: an outlet change mid-session is exactly
                        # what the old per-outlet detector reset its clock on, and the whole
                        # point of this one is that it does not.
                        self.journal.note(
                            "mask_change",
                            zone=zone,
                            mask=mask,
                            was=self._last_mask.get(zone),
                            flowing_for=now - self._flowing_since[zone],
                            **described(zone),
                        )
                    elif reading is not None and reading != was_reading:
                        # Flow or temperature moved without the outlets changing — the
                        # touchscreen adjusting a dial mid-shower looks exactly like this,
                        # and it is what decides whether a restore should replay the
                        # original settings or the latest ones.
                        self.journal.note(
                            "setting_change",
                            zone=zone,
                            mask=mask,
                            flowing_for=now - self._flowing_since[zone],
                            was_flow_percent=(
                                was_reading.flow_percent if was_reading else None
                            ),
                            was_temperature_f=(
                                was_reading.temperature_f if was_reading else None
                            ),
                            **described(zone),
                        )
                self._last_mask[zone] = mask
                continue

            started = self._flowing_since.pop(zone, None)
            was_running = self._last_mask.pop(zone, 0)
            # Popped last, so `described()` above still sees it while building the record.
            was_reading = self._last_reading.get(zone)
            if started is None:
                self._last_reading.pop(zone, None)
                continue

            duration = now - started
            candidates = limits.get(zone, ())
            record: dict[str, Any] = {
                "zone": zone,
                "duration": duration,
                "limits": list(candidates),
                "mask": was_running,
                "paused": is_paused,
                **described(zone),
            }
            self._last_reading.pop(zone, None)

            def stop(reason: str, **extra: Any) -> None:
                self.journal.note(
                    "flow_end", **record, verdict="ignored", reason=reason, **extra
                )
                if not is_paused:
                    # A 0x00 stop is somebody stopping the shower. Only pauses are
                    # candidates for a timer we have not been told about.
                    return
                self.watcher.note_declined(zone, duration, now)
                self.watcher.report(zone, candidates)
                for seconds in self.watcher.learned_limits.get(zone, ()):
                    if abs(duration - seconds) > CUTOFF_TOLERANCE_SECONDS:
                        continue
                    # The staging record: what would have happened had this suspected limit
                    # been promoted to a real one. Read these before promoting it.
                    self.journal.note(
                        "would_have_fired",
                        zone=zone,
                        duration=duration,
                        suspected_limit=seconds,
                        mask=was_running,
                        note="not acted on — this limit was inferred, not announced",
                    )

            if not candidates:
                # The valve has never announced a limit for this zone's outlets, so there is
                # nothing to compare against. Silence beats a guess when the consequence is
                # running water.
                stop("no maximumRunTime known for this zone's outlets")
                continue
            match = next(
                (
                    limit
                    for limit in candidates
                    if abs(duration - limit) <= CUTOFF_TOLERANCE_SECONDS
                ),
                None,
            )
            if match is None:
                stop(
                    "duration is not within %.0fs of any limit"
                    % CUTOFF_TOLERANCE_SECONDS,
                    off_by=min(abs(duration - limit) for limit in candidates),
                )
                continue
            if not is_paused:
                _LOGGER.debug(
                    "Zone %s stopped at its %ss limit but without the pause flag, so this "
                    "was a stop rather than the valve's timer — ignoring",
                    zone,
                    match,
                )
                stop("stopped (0x00) rather than paused (0x40) — not the valve's timer")
                continue
            if suppressed(zone):
                _LOGGER.debug(
                    "Zone %s closed at its %ss limit, but Home Assistant closed that zone "
                    "moments ago — treating it as our own stop",
                    zone,
                    match,
                )
                stop(
                    "Home Assistant closed this zone within the %.0fs grace window"
                    % LOCAL_WRITE_GRACE_SECONDS
                )
                continue
            self.journal.note("flow_end", **record, verdict="cutoff", matched=match)
            fired.append(
                ZoneCutoff(
                    zone=zone,
                    duration=duration,
                    limit=match,
                    mask=was_running,
                    reading=was_reading,
                )
            )

        return fired
