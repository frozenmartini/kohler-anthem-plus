"""The Report Log — the one capture a user turns on to document a bug.

# =====================================================================
# REPORT LOG — off by default, one file per switch-on, survives restarts
# =====================================================================

A switch on the device page ("Report Log") that someone flips on to document a bug — or a
healthy run on hardware this integration has never been verified against — and off when
done, producing **one file per episode** they can attach to a GitHub issue.

Two kinds of record land in that file, on one clock, in the order they happened:

* **Raw MQTT** — every payload paho hands us, before any decoding. The decoded `Envelope`
  is lossy by design (it keeps `sku`, `deviceid`, `code` and `attributes` and drops the
  rest), and a payload that fails to parse is dropped entirely by the normal path. Those
  are precisely the ones worth having, so the record is the payload text exactly as it
  arrived — not a re-serialised dict. A raw record is recognisable by its `topic` key.
* **Decision trails** — the run-time cutoff detector's and the warm-up watcher's own
  records: every zone that started or stopped flowing, every close evaluated with the
  duration and limits it was compared against, the verdict and its reason; every warm-up
  mode change, who wrote it, and what auto-restore did about it. `home-assistant.log`
  shows only outcomes — a WARNING if a restore fired and *nothing at all* if one should
  have and didn't — so the trail is the only record of the silence that matters. A trail
  record is recognisable by its `journal` key (`cutoff` or `warmup`; the two vocabularies
  share event names) and its `event`.

Until 0.4.1 the trails went to the author's own always-on development capture instead, so
a user's report carried the wire traffic but none of the reasoning about it. Folded in on
2026-09-10 (session 27), the owner's decision: one capture, one attachment.

The episode is the unit, not the Home Assistant run:

* **Switch on → a new file**, named for the moment it was enabled.
* **Home Assistant restarting does not split the episode** — the coordinator persists the
  episode name in the config entry options and re-attaches to the *same* file in append
  mode after the restart. A capture of "it breaks when I restart HA" must not lose the
  interesting part to the restart itself.
* **Switch off → the episode ends.** The next switch-on starts a fresh file.

Size is bounded per file, not per episode: a file that reaches ``max_bytes`` rolls to a
continuation part (``<episode>_p2.jsonl``, ``_p3``, …) sharing the episode stem, so one
runaway episode cannot eat the disk in a single unmanageable file and a restart's re-attach
lands on the latest part.

⚠️ **The directory lives inside the integration folder** (``custom_components/
kohler_anthem_plus/reports/``) — the owner's choice, so reports sit with the integration
they describe. Two consequences, both accepted: a HACS update or reinstall **replaces the
integration folder and deletes any reports still in it** (move files out before updating if
they matter), and on the development install the directory is gitignored.

Threads: paho calls `write()` on its network thread; the coordinator calls `note()` on the
event loop; `start`/`resume`/`stop`/`prepare` run in an executor. The lock covers all file
state. `write()` may open or roll the file (it is off the loop); `note()` never does — see
:attr:`ReportLog.wants_open`.

The two formatters here, `format_record` and `format_event`, are also what the author's
out-of-tree development capture is built on (the gitignored ``_dev/`` package, present on
one machine and never in a release), so its files stay byte-compatible with these.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 8 * 1024 * 1024

_PART_RE = re.compile(r"_p(\d+)\.jsonl$")

_README = """\
Kohler Anthem Plus — report captures
====================================

Each report_*.jsonl file here is one capture episode, recorded because the
"Report Log" switch on the device page was on. One file per switch-on; a Home
Assistant restart continues the same file; a file that reaches {max_mb} MB
continues in _p2, _p3, ... parts.

One JSON object per line, in the order things happened, every line stamped

    ts           ISO-8601 UTC, the same clock for every record

Two kinds of line share the file. Tell them apart by which key they carry:

  A raw MQTT message — has `topic`:

    topic        the MQTT topic
    payload      the payload text exactly as received (undecoded)
    payload_b64  present INSTEAD of payload when the bytes were not UTF-8
    qos, retain  from the MQTT message

  A decision record — has `journal` and `event`:

    journal      "cutoff" or "warmup" — which watcher wrote it
    event        what happened (the two journals reuse some event names,
                 which is why `journal` is there)
    valve        present only on an account with several valves: which one

    jq -c 'select(.topic)'   report_*.jsonl     # the wire traffic only
    jq -c 'select(.journal)' report_*.jsonl     # the reasoning only

The cutoff journal (journal: "cutoff") is the run-time cutoff detector — the
part of the integration that can turn water back ON by itself (Endless Shower):

    arm             the detector armed at startup: `enabled` (the Endless
                    Shower switch), the run-time limits it knows per outlet
    flow_start      a zone started flowing: `zone`, `mask`, `limits`
    mask_change     outlets changed while flowing: `mask`, `was`, `flowing_for`
    setting_change  flow or temperature moved while the outlets did not —
                    the touchscreen adjusting a dial mid-shower
    flow_end        a zone stopped: `duration` (seconds), `limits` it was
                    compared against, `mask`, `paused` (the 0x40 pause flag),
                    `verdict` "cutoff" or "ignored", and `reason` when ignored
    restore         Endless Shower acted (or was `skipped` because the switch
                    is off): zones, masks, and whether the previous flow was
                    replayed (`flow_preserved`) or fell back to the default
    restore_done / restore_failed / anchor / forget
                    the outcome, and the bookkeeping around a restore

    flow_start, mask_change, setting_change and flow_end also carry what the
    shower was delivering: `flow_percent` (0-100) and `temperature_f` —
    ALWAYS Fahrenheit, whatever the account displays, so captures compare.

The warmup journal (journal: "warmup") watches the valve's warm-up mode, which
the Anthem Plus hub's own web UI resets to `warmUpDisabled` on every sign-in:

    baseline        the first record after startup: the mode in force, whether
                    Warmup Auto-Restore is armed, and what it would restore to
    mode            the mode moved: `before` -> `after`, `ours` (did Home
                    Assistant write it), `source` mqtt or rest
    announced       the valve restated a mode it was already in
    disabled        the mode went to warmUpDisabled, with `before_window`: the
                    MQTT traffic in the seconds leading up to it
    context         written shortly after a disable, holding `after_window`
    restore_scheduled / restore / restore_done / restore_failed / restore_skipped
                    what Auto-Restore did, and why when it did nothing

Attach these files to a GitHub issue to document a bug — or a healthy run on
hardware the integration has never been verified against.

⚠️ Before sharing, know that these files contain your device identifiers and
show when your shower was used. Review anything you'd rather not publish.

⚠️ This folder is inside the integration itself, so updating or reinstalling
the integration DELETES it. Move files you want to keep somewhere else first.

Turning the switch off ends the capture; the files stay until you delete them
(or an update does).
"""


def _now_iso() -> str:
    """The one timestamp format every record in a capture carries."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def format_record(
    topic: str, payload: bytes, *, qos: int = 0, retain: bool = False
) -> str | None:
    """One raw-MQTT line: ts/topic/qos/retain plus the payload exactly as it arrived.

    Decoding is the consumer's problem, deliberately: a payload that fails to parse is the
    most interesting kind, and re-serialising a parsed dict would quietly normalise away
    key order, duplicates, and numeric formatting. None when the record cannot be
    serialised.
    """
    record: dict[str, Any] = {
        "ts": _now_iso(),
        "topic": topic,
        "qos": qos,
        "retain": retain,
    }
    try:
        record["payload"] = payload.decode("utf-8")
    except UnicodeDecodeError:
        record["payload_b64"] = base64.b64encode(payload).decode("ascii")
    try:
        return json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def format_event(journal: str | None, event: str, fields: dict[str, Any]) -> str | None:
    """One decision-trail line: ts, [journal], event, then the fields in call order.

    `journal` names the trail (`cutoff` or `warmup`) when several share a file, as they do
    in the Report Log — the two vocabularies reuse event names (`restore`, `restore_done`,
    `restore_failed`, `restore_skipped`), so a line without it is ambiguous. `None` omits the
    key: a file that holds one trail only (the development capture's per-trail files) has
    no need of it, and this keeps those files byte-identical to what they were.

    Floats are rounded on the way in: these are seconds measured off a monotonic clock, and
    sixteen significant figures of float noise makes the log harder to read for no gain.
    Two decimals still resolves the 0.2 s jitter the cutoff tolerance is sized against.
    None when the record cannot be serialised.
    """
    record: dict[str, Any] = {"ts": _now_iso()}
    if journal is not None:
        record["journal"] = journal
    record["event"] = event
    for key, value in fields.items():
        record[key] = round(value, 2) if isinstance(value, float) else value
    try:
        return json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


class ReportLog:
    """One capture file per switch-on episode, append-through-restart.

    The coordinator owns the episode lifecycle: `start()` returns the episode name for it
    to persist, `resume(name)` re-attaches after a restart, `stop()` ends the episode, and
    `close()` merely releases the file handle at unload without ending the episode (the
    options key, not this object, is what says an episode is in force).

    Two writers feed it: the MQTT stream's `write()` for raw messages, off the event loop,
    and the coordinator's `note()` for decision records, on it. Both are no-ops while no
    episode is active, so registering this object as a sink costs one branch per record.
    """

    def __init__(self, directory: str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._directory = directory
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._handle = None
        self._written = 0
        self._path: str | None = None
        self._stem: str | None = None
        # Set by `note()` when it finds no open file. See `wants_open`.
        self._wants_open = False

    @property
    def active(self) -> bool:
        """Whether an episode is being written by this object right now."""
        return self._stem is not None

    @property
    def path(self) -> str | None:
        """The file currently being written, or None."""
        return self._path

    @property
    def wants_open(self) -> bool:
        """True when the loop-side writer needs an executor to open or roll the file.

        `note()` runs on the event loop, where opening a file, creating a directory or
        rolling to the next part are blocking calls that must not happen. So `note()` never
        does them: with no file open it raises this flag and drops that one record; with a
        file that has passed the size cap it writes anyway (a few bytes over is harmless,
        a lost record is not) and the flag asks for the roll. The journal fan-out schedules
        `prepare()` in an executor whenever this reads true; the paho thread's next
        `write()` would do the same open or roll on its own.
        """
        return self._stem is not None and (
            self._handle is None or self._written >= self._max_bytes
        )

    def start(self) -> str:
        """Begin a new episode. Returns the episode name for the caller to persist.

        Opens the file immediately rather than waiting for the first message — this stream
        has been silent for 11.9 hours, and someone who just flipped the switch deserves a
        file they can see. Blocking I/O: call from an executor.
        """
        stem = "report_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with self._lock:
            self._close_locked()
            # Off and on again inside one second would land on the episode just closed and
            # merge two switch-ons into one attachment; take the next free name instead.
            # The name is *reserved* by creating the file exclusively, not by looking, so
            # two starts in the same second — the valve's switch and the controller's, or
            # two config entries sharing this directory — cannot both claim it. (`resume`
            # reopens an existing file on purpose; only `start` guards.)
            os.makedirs(self._directory, exist_ok=True)
            base, nth = stem, 1
            while True:
                try:
                    os.close(os.open(os.path.join(self._directory, f"{stem}.jsonl"),
                                     os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
                    break
                except FileExistsError:
                    nth += 1
                    stem = f"{base}-{nth}"
                except OSError:
                    break  # the append open below reports the real problem
            self._stem = stem
            try:
                self._open_locked()
            except OSError as err:
                _LOGGER.warning("Report log could not open a file: %s", err)
        _LOGGER.info("Report log ON — new episode %s", stem)
        return stem

    def resume(self, stem: str) -> None:
        """Re-attach to a persisted episode after a restart, appending to its last part.

        Blocking I/O: call from an executor. A vanished file (user deleted it mid-episode)
        is simply recreated by the append open — the episode name is the identity.
        """
        with self._lock:
            self._close_locked()
            self._stem = stem
            try:
                self._open_locked()
            except OSError as err:
                _LOGGER.warning("Report log could not reopen %s: %s", stem, err)
        _LOGGER.info("Report log resumed episode %s after restart", stem)

    def stop(self) -> None:
        """End the episode. The next `start()` gets a fresh file."""
        with self._lock:
            path = self._path
            self._close_locked()
            self._stem = None
        _LOGGER.info("Report log OFF (%s)", path)

    def close(self) -> None:
        """Release the file handle without ending the episode — for unload.

        The episode's persistence is the config entry's business; after a reload the
        coordinator calls `resume()` with the persisted name and writing continues in the
        same file. Idempotent on purpose: at shutdown this is reached twice, once through
        the MQTT stream's raw sinks and once through the journal sinks.
        """
        with self._lock:
            self._close_locked()

    def prepare(self) -> None:
        """Open, or roll, the file the loop-side writer asked for. Executor only.

        No-op when no episode is active or nothing was asked for; otherwise the same open
        the paho thread would have done, just off the loop.
        """
        with self._lock:
            self._wants_open = False
            if self._stem is None:
                return
            if self._handle is None or self._written >= self._max_bytes:
                try:
                    self._open_locked()
                except OSError as err:
                    _LOGGER.warning("Report log could not open a file: %s", err)

    def write(
        self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False
    ) -> None:
        """Record one raw message. Cheap no-op when no episode is active. Paho thread."""
        if self._stem is None:
            return
        line = format_record(topic, payload, qos=qos, retain=retain)
        if line is None:  # pragma: no cover - defensive
            return
        with self._lock:
            if self._stem is None:
                return
            try:
                self._write_line_locked(line)
            except OSError as err:
                # A diagnostic must never take the stream down. Drop the handle but keep
                # the episode: the disk may come back, and the persisted name means a
                # restart re-attaches either way.
                _LOGGER.warning("Report log write failed: %s", err)
                self._close_locked()

    def note(self, journal: str, event: str, **fields: Any) -> None:
        """Record one decision. Cheap no-op when no episode is active. Event loop.

        Never opens or rolls the file — see `wants_open` for what happens instead.
        """
        if self._stem is None:
            return
        line = format_event(journal, event, fields)
        if line is None:  # pragma: no cover - defensive
            return
        with self._lock:
            if self._stem is None:
                return
            if self._handle is None:
                # No file, and opening one here would block the event loop. Ask for a
                # prepare() instead; this record is lost and the next one lands.
                self._wants_open = True
                return
            try:
                encoded = line + "\n"
                self._handle.write(encoded)
                self._handle.flush()
                self._written += len(encoded.encode("utf-8"))
            except OSError as err:
                _LOGGER.warning("Report log write failed: %s", err)
                self._close_locked()

    # ------------------------------------------------------------------ #
    # Locked internals
    # ------------------------------------------------------------------ #
    def _write_line_locked(self, line: str) -> None:
        if self._handle is None or self._written >= self._max_bytes:
            self._open_locked()
        assert self._handle is not None
        encoded = line + "\n"
        self._handle.write(encoded)
        self._handle.flush()
        # Per line, on purpose: reports are read while the problem is still happening, and
        # buffered lines would not be there yet.
        self._written += len(encoded.encode("utf-8"))

    def _part_path(self, part: int) -> str:
        name = f"{self._stem}.jsonl" if part == 1 else f"{self._stem}_p{part}.jsonl"
        return os.path.join(self._directory, name)

    def _latest_part(self) -> int:
        """The highest existing part number for this episode, or 1 if none exist yet."""
        assert self._stem is not None
        latest = 1
        try:
            for name in os.listdir(self._directory):
                if not name.startswith(self._stem):
                    continue
                if name == f"{self._stem}.jsonl":
                    latest = max(latest, 1)
                else:
                    match = _PART_RE.search(name)
                    if match and name == f"{self._stem}_p{match.group(1)}.jsonl":
                        latest = max(latest, int(match.group(1)))
        except OSError:
            pass
        return latest

    def _open_locked(self) -> None:
        """Open the episode's current part for append, rolling to the next when full.

        Append mode is the whole trick: a restart's `resume()` lands here, finds the
        latest part, and continues it — the file does not restart with Home Assistant.
        """
        self._close_locked(quiet=True)
        os.makedirs(self._directory, exist_ok=True)
        self._write_readme()
        part = self._latest_part()
        path = self._part_path(part)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size >= self._max_bytes:
            part += 1
            path = self._part_path(part)
            size = 0
        self._path = path
        self._handle = open(path, "a", encoding="utf-8")
        self._written = size
        self._wants_open = False

    def _write_readme(self) -> None:
        try:
            with open(
                os.path.join(self._directory, "README.txt"), "w", encoding="utf-8"
            ) as fh:
                fh.write(_README.format(max_mb=self._max_bytes // (1024 * 1024)))
        except OSError:  # pragma: no cover - the capture still works without it
            pass

    def _close_locked(self, *, quiet: bool = False) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:  # pragma: no cover
                pass
        self._handle = None
        if not quiet:
            self._path = None
        self._written = 0
