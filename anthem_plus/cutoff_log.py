"""Decision log for the run-time cutoff detector — why it fired, and why it didn't.

# =====================================================================
# CUTOFF DEBUG LOG — diagnostic, OFF BY DEFAULT, safe to delete wholesale
# =====================================================================
#
# Searching for this later? The markers are:
#
#   grep -rn "CUTOFF DEBUG LOG" custom_components/kohler_anthem_plus/
#
# That finds this module, the constants in `const.py`, the call sites in
# `anthem_plus/runtime_cutoff.py` and `coordinator.py`, and the roll button.
# Removing those blocks removes the feature completely.
#
# =====================================================================

The cutoff detector is the one piece of this integration that turns water back **on** by
itself, and its inputs are invisible after the fact: durations are measured against a
monotonic clock in memory, and the valve destroys the outlet mask in the same message that
reports the close. When it misbehaves, `home-assistant.log` shows only the outcome — a
WARNING if it fired, and *nothing at all* if it should have fired and didn't. Silence is the
failure mode that matters, and silence is exactly what a normal log cannot record.

So this writes the detector's whole decision trail: every zone that starts or stops flowing,
every close it evaluated, the duration and limits it compared, and the verdict with a reason.

## Reading it alongside the raw MQTT capture

Both logs live in the **same directory** and stamp `ts` in the **same format** — ISO-8601
UTC with a `Z` suffix, taken from the same clock. So the two interleave directly:

    cd /config/kohler_anthem_plus_raw
    jq -c '{ts, src:"mqtt", code:(.payload|fromjson|.data.code)}' mqtt_raw_*.jsonl \
      > /tmp/a.jsonl
    jq -c '{ts, src:"cutoff", event, zone, verdict, reason}' cutoff_*.jsonl > /tmp/b.jsonl
    sort -m -t'"' -k4 /tmp/a.jsonl /tmp/b.jsonl | less

The pairing to look for is a `GCS_SOLO_STS` in the raw log whose valve word carries `0x40`,
and the `flow_end` record written in the same instant. If the raw log shows the pause and
the cutoff log shows `verdict: "ignored"`, the `reason` and `duration` fields say precisely
why — which is the question that took a full capture corpus to answer the first time.

Switching it on works exactly like the raw capture, and independently of it:

* **From the UI, no restart** — Developer Tools → Actions → `logger.set_level`, YAML mode:

      action: logger.set_level
      data:
        custom_components.kohler_anthem_plus.anthem_plus.cutoff_log: debug

* **Permanently** — set `ENABLE_CUTOFF_DEBUG_LOG = True` in `const.py`.

Volume is low — a handful of lines per shower, versus one per MQTT message — so leaving it
on across days costs almost nothing. Files are one per Home Assistant run, pruned to the
newest `keep_files`.

Thread safety: the detector runs on the event loop, but `note()` is cheap and the lock makes
it safe from the paho thread too, matching `RawMqttLog`.
"""

from __future__ import annotations

import binascii
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# This module's own logger doubles as the runtime switch, read as a flag rather than used
# for output — see `RawMqttLog.enabled` for why `.level` and not `isEnabledFor()`.
_SWITCH_LOGGER = _LOGGER

#: None means no limit — every log file is kept forever. This is the default; the
#: directory is diagnostic output the owner wants to keep, not a rotating buffer.
DEFAULT_KEEP_FILES: int | None = None

_README = """\
Run-time cutoff decision log — written by the kohler_anthem_plus integration.

Each .jsonl file is one Home Assistant run, one JSON object per line. Every
record has:

    ts       ISO-8601 UTC — the SAME clock and format as mqtt_raw_*.jsonl in
             this directory, so the two files interleave by sorting on it
    event    flow_start | flow_end | restore | arm

`flow_end` is the interesting one. It carries the detector's full reasoning:

    zone       the valve zone that stopped flowing
    duration   seconds it had been flowing, monotonic
    limits     the maximumRunTime values it was compared against
    mask       the outlet mask that was flowing just before it stopped
    paused     whether the zone carried the 0x40 pause flag
    verdict    "cutoff" or "ignored"
    reason     why, when ignored

`flow_start`, `mask_change`, `setting_change` and `flow_end` also carry what the
shower was actually delivering at that moment:

    flow_percent     0-100, from the valve word
    temperature_f    degrees FAHRENHEIT always, whatever the account displays,
                     so captures from different accounts stay comparable

`setting_change` fires when flow or temperature moved while the outlets did not —
which is what the touchscreen adjusting a dial mid-shower looks like.

On a `restore`, compare `was_flow_percent` against `writing_flow_percent`.
`flow_preserved: false` means at least one cut zone had no captured reading, so it
came back at `DEFAULT_FLOW_PERCENT` instead of its own prior value — the fallback,
not the normal case. `true` means every cut zone's flow was replayed exactly as it
was running before the cut.

To correlate with the raw MQTT capture, look for the GCS_SOLO_STS message
whose valve word has 0x40 in byte 3 at the same `ts` as a flow_end record.

This log is OFF by default. Right now it is on because:

{why}

{keep_desc} Delete them freely — pure diagnostics.
"""

_WHY_FORCED = """\
    ENABLE_CUTOFF_DEBUG_LOG = True

in the integration's const.py, which pins it on across restarts.

TO STOP IT: set that constant back to False and restart Home Assistant.
`logger.set_level` will NOT turn it off while the constant is True."""

_WHY_LOGGER = """\
    custom_components.kohler_anthem_plus.anthem_plus.cutoff_log

is set to debug. To stop it, call `logger.set_level` with that same logger
name set to `info` — no restart needed. This does not survive a restart; set
ENABLE_CUTOFF_DEBUG_LOG = True in const.py to keep it on."""


WARMUP_README = """\
Kohler Anthem Plus — warmup journal
==================================

These `warmup_*.jsonl` files exist to answer one open question: **what keeps setting the
Anthem valve's warmup mode back to `warmUpDisabled`?**

It happened four times between 2026-08-13 and 2026-08-18. Ruled out already: valve reboots
(the mode survives them, and the valve merely restates it ~4 s after every boot), Home
Assistant (this integration made no such write), and a cloud command (no `GCS_RECIEVED_STS`
landed within 447 s of any of them). What every one of them *did* sit inside was a burst of
configuration re-sync traffic. The leading suspect is the Anthem Plus controller writing over
the RJ wired link, which cannot be sniffed — so the only evidence available is what happens
either side on the channels that can be seen. That is what these records hold.

{keep_desc}

Records
-------
  baseline          the first line of every file: the mode in force when the journal opened,
                    read over REST at setup, plus whether auto-restore is armed and what it
                    would restore to. The valve never volunteers its mode on connect — over
                    all 74 raw captures the first `GCS_WARM_STS` in a file lands between
                    137 s and 7 h in — so without this line a file has no idea what it
                    started from, and cannot say how long the mode had been in force.
  mode              the mode moved. `before` -> `after`, `ours` (did we write it), and
                    `source`: `mqtt` if the valve announced it, `rest` if a reseed found it
                    already changed. A `rest` one means the move happened while the stream
                    was down; it carries `restored: false`, because auto-restore does not
                    act on these.
  announced         the valve restated a mode it was already in. Carries `mode` and `ours`.
                    No decision attached — 28 of the 43 announcements in the raw corpus are
                    these. ⚠️ **Check `ours` before reading one as the valve volunteering.**
                    Setting the mode from the dropdown lands here rather than on a `mode`
                    record: the write reads itself back over REST immediately, so our state
                    has already moved by the time the valve's echo arrives ~3.4 s later.
  disabled          the mode went to `warmUpDisabled`. Carries `ours` (did we write it),
                    `restoring` (is auto-restore acting), and `before_window`: every MQTT
                    message seen in the {before}s leading up to it.
  context           written {after}s later, holding `after_window` — the messages that
                    followed. `SYSTEM_STS: SYSTEM_READY` appearing here is the signature seen
                    7-9 s after two of the four known disables. The window deliberately
                    closes before auto-restore could act, so this record never contains our
                    own write.
  restore*          what auto-restore did: scheduled, skipped, done, or failed.

Reading them
------------
Every record has an ISO-8601 UTC `ts`, the same clock as the raw capture beside it, so the two
interleave:

    jq -c '{{ts, src:"warmup", event, mode, before, after, ours}}' warmup_*.jsonl > /tmp/a.jsonl
    jq -c '{{ts, src:"raw", topic}}' mqtt_raw_*.jsonl > /tmp/b.jsonl
    sort -m /tmp/a.jsonl /tmp/b.jsonl

What to look for
----------------
Compare the `before_window` and `after_window` of several `disabled` records and find what
they share and a quiet hour does not. Candidates worth ranking:

  * `SYSTEM_STS` / `STATUS_SNAPSHOT` — the controller announcing it has come up.
  * `configChangeIndent` stepping on `GCS_SOLO_STS` — configuration writes landing.
  * A burst of `READ_GCS_OUTLET_CONFIG_CFG` / `GCS_PRESET_STS` — a full config re-read.
  * `SHOWER_EXP_SNAPSHOT` and friends — the Konnect app or a touchscreen asking for state.

⚠️ Absence of a message means "nothing was pushed", never "nothing happened" — MQTT here is
the Konnect app's UI channel, not device-to-device traffic. See docs/case_studies/intro.md.

Auto-restore and this journal
-----------------------------
A single disable is recorded identically whether the Warmup Auto-Restore switch is on or off:
both windows close before a restore could fire.

Where it matters is a *repeat*. A restore is itself a write — a POST, then the valve's echo
about 3.4 s later — and if the culprit disables the mode again soon afterwards, that traffic
lands inside the new event's `before_window`. It is identifiable (the `restore` records carry
timestamps, and the `mode` record that follows one is flagged `ours: true`), but it is our
noise in the middle of the evidence, and a restore might itself provoke whatever is doing
this. **For the cleanest series of observations, leave auto-restore off.** For a shower that
warms up reliably while the question stays open, turn it on and subtract our own records
during analysis.


Turning it off
--------------
Set ENABLE_WARMUP_DEBUG_LOG = False in const.py and restart Home Assistant Core.
"""


class CutoffDebugLog:
    """Append cutoff-detector decisions to a JSONL file, when switched on."""

    def __init__(
        self,
        directory: str,
        *,
        forced: bool = False,
        keep_files: int | None = DEFAULT_KEEP_FILES,
        prefix: str = "cutoff",
        readme: str | None = None,
        readme_fields: dict[str, Any] | None = None,
        label: str = "Cutoff debug log",
    ) -> None:
        """`prefix` names the files and scopes pruning; `readme` is the note left beside them.

        Parameterised 2026-08-20 so the warmup journal can reuse this writer rather than
        copy it. Pruning matches on the prefix, so two journals in one directory never
        delete each other's files.
        """
        self._directory = directory
        self._forced = forced
        self._keep_files = keep_files
        self._prefix = prefix
        self._readme = readme
        self._readme_fields = readme_fields or {}
        self._label = label
        self._lock = threading.Lock()
        self._handle: Any = None
        self._path: str | None = None
        self._announced = False
        # Set when a record arrives with no file open. See `wants_open`.
        self._wants_open = False

    @property
    def enabled(self) -> bool:
        """True when the log is switched on, by either mechanism."""
        return self._forced or _SWITCH_LOGGER.level == logging.DEBUG

    @property
    def path(self) -> str | None:
        """The file currently being written, or None when not logging."""
        return self._path

    @property
    def wants_open(self) -> bool:
        """True when a record arrived with no file open, so :meth:`prepare` should be called.

        Unlike `RawMqttLog`, this log is written from the **event loop** — the detector runs
        there. Opening a file and creating a directory are blocking calls that must not
        happen on it, so `note()` never opens one; it raises this flag instead and the caller
        schedules `prepare()` in an executor. The cost is that the first record after
        switching capture on mid-session is dropped, which matters far less than the flag it
        replaces.
        """
        return self._wants_open

    def prepare(self) -> None:
        """Open an empty file now, if switched on, so it is visibly working.

        Blocking file I/O: call it from an executor, not the event loop.
        """
        if not self.enabled:
            return
        with self._lock:
            self._wants_open = False
            if self._handle is None:
                try:
                    self._open_locked()
                except OSError as err:
                    _LOGGER.warning("%s could not open a file: %s", self._label, err)

    def note(self, event: str, **fields: Any) -> None:
        """Record one decision or transition. Cheap no-op when switched off."""
        if not self.enabled:
            if self._handle is not None:
                self.close()
            return

        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event": event,
        }
        # Rounded on the way in: these are seconds measured off a monotonic clock, and
        # sixteen significant figures of float noise makes the log harder to read for no
        # gain. Two decimals still resolves the 0.2 s jitter the tolerance is sized against.
        for key, value in fields.items():
            record[key] = round(value, 2) if isinstance(value, float) else value

        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return

        with self._lock:
            if self._handle is None:
                # No file yet, and opening one here would block the event loop. Ask for a
                # prepare() instead; this record is lost and the next one lands.
                self._wants_open = True
                return
            try:
                self._handle.write(line + "\n")
                self._handle.flush()
            except OSError as err:
                # A diagnostic must never take the integration down with it.
                _LOGGER.warning("%s write failed, disabling: %s", self._label, err)
                self._close_locked()
                self._forced = False

    def _open_locked(self) -> None:
        self._close_locked()
        os.makedirs(self._directory, exist_ok=True)
        self._write_readme()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        suffix = binascii.hexlify(os.urandom(4)).decode("ascii")
        self._path = os.path.join(
            self._directory, f"{self._prefix}_{stamp}Z_{os.getpid()}_{suffix}.jsonl"
        )
        self._handle = open(self._path, "a", encoding="utf-8")
        self._prune()
        if not self._announced:
            self._announced = True
            _LOGGER.info("%s is ON, writing to %s", self._label, self._path)

    def _write_readme(self) -> None:
        """Leave a note saying what these files are and how to stop them."""
        try:
            with open(
                os.path.join(self._directory, f"README-{self._prefix}.txt"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    (self._readme or _README).format(
                        **self._readme_fields,
                        why=_WHY_FORCED if self._forced else _WHY_LOGGER,
                        keep_desc=(
                            "No limit on the number of files — every one is kept."
                            if self._keep_files is None
                            else f"Only the newest {self._keep_files} are kept."
                        ),
                    )
                )
        except OSError:  # pragma: no cover - the log still works without it
            pass

    def _prune(self) -> None:
        """Keep the newest `keep_files` logs so the directory stays bounded.

        A no-op when `keep_files` is None — unlimited is the default, and the owner wants
        this directory to hold everything.
        """
        if self._keep_files is None:
            return
        try:
            logs = sorted(
                (
                    os.path.join(self._directory, name)
                    for name in os.listdir(self._directory)
                    if name.startswith(f"{self._prefix}_") and name.endswith(".jsonl")
                ),
                key=os.path.getmtime,
            )
        except OSError:  # pragma: no cover
            return
        for stale in logs[: max(0, len(logs) - self._keep_files)]:
            try:
                os.remove(stale)
            except OSError:  # pragma: no cover
                pass

    def roll(self) -> str | None:
        """Start a new file immediately. Returns its path, or None if the log is off.

        Rolled together with the raw capture so a pair of files always covers the same
        experiment — matching them up afterwards by timestamp is the bookkeeping this
        avoids.

        Blocking file I/O — call it from an executor, not the event loop.
        """
        if not self.enabled:
            return None
        with self._lock:
            self._close_locked()
            try:
                self._open_locked()
            except OSError as err:
                _LOGGER.warning("Could not start a new cutoff debug log: %s", err)
                return None
            return self._path

    def close(self) -> None:
        """Close the current file, if one is open."""
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:  # pragma: no cover
                pass
            if self._announced:
                _LOGGER.info("%s is OFF (%s)", self._label, self._path)
                self._announced = False
        self._handle = None
        self._path = None
