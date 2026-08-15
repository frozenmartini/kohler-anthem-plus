"""Raw MQTT capture — every payload paho hands us, before any decoding.

# =====================================================================
# RAW MQTT LOGGING — diagnostic, OFF BY DEFAULT, safe to delete wholesale
# =====================================================================
#
# Searching for this later? The markers are:
#
#   grep -rn "RAW MQTT LOG" custom_components/kohler_anthem_plus/
#
# That finds this module, the two constants in `const.py`, the call site in
# `mqtt.py:_on_message`, and the wiring in `coordinator.py`. Removing all four
# blocks removes the feature completely.
#
# =====================================================================

This exists because the decoded `Envelope` is lossy by design — it keeps `sku`, `deviceid`,
`code` and `attributes`, and drops everything else. When the question is "what did Kohler
*actually* send", a decoded stream cannot answer it, and the answer is unrecoverable after
the fact. This replaces the capture that used to live in the separate `mqtt_capture.py`
bridge, which stopped being reachable when the old `kohler` integration was removed.

**What is written is the payload exactly as it arrived** — the undecoded UTF-8 text, not a
re-serialised dict. A payload that is not valid JSON, or not valid UTF-8, is still captured;
those are precisely the ones worth having, and the normal decode path silently drops them.

Two ways to switch it on, both without touching this file:

* **From the Home Assistant UI, no restart** — Developer Tools → Actions →
  `logger.set_level`, in YAML mode. The whole `data:` block is a mapping of logger name to
  level; there is no `entity_id`, because a logger is not an entity.

      action: logger.set_level
      data:
        custom_components.kohler_anthem_plus.anthem_plus.raw_log: debug

  Setting it back to `info` stops the capture and closes the file on the next message. This
  is the one to reach for. Note `logger.set_level` is per-logger — the system-wide one is
  `logger.set_default_level`, which does **not** turn this on (see :attr:`RawMqttLog.enabled`).
  Neither survives a restart, which is the right default for a capture.

* **Permanently, across restarts** — set `ENABLE_RAW_MQTT_LOG = True` in `const.py`.

Nothing is created on disk until the first message actually arrives while enabled, so
leaving the feature installed but off costs one branch per message.

Thread safety: paho calls `write()` on its own network thread, never the event loop, so the
file I/O here is already off-loop. The lock guards against a `close()` from the loop racing
a write from that thread.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# The logger whose level acts as the runtime switch. It is this module's own logger, so
# `logger.set_level` on the module path toggles capture. Nothing is ever emitted through it
# at DEBUG — the level is read as a flag, not used for output — which keeps the capture out
# of `home-assistant.log` where it would be unreadable.
_SWITCH_LOGGER = _LOGGER

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
#: None means no limit — every capture file is kept forever. This is the default; the
#: directory is diagnostic output the owner wants to keep, not a rotating buffer.
DEFAULT_KEEP_FILES: int | None = None

_README = """\
Raw Kohler MQTT capture — written by the kohler_anthem_plus integration.

Each .jsonl file is one capture session, one JSON object per line:

    ts       ISO-8601 UTC, when paho handed us the message
    topic    the MQTT topic it arrived on
    payload  the payload text exactly as received (undecoded)
    payload_b64  present INSTEAD of `payload` when the bytes were not valid UTF-8
    qos, retain  from the paho message

This capture is OFF by default. Right now it is on because:

{why}

Files roll at {max_mb} MB. {keep_desc}
Delete it freely — it is pure diagnostic output.
"""

_WHY_FORCED = """\
    ENABLE_RAW_MQTT_LOG = True

in the integration's const.py, which pins capture on across restarts.

TO STOP IT: set that constant back to False and restart Home Assistant.
The `logger.set_level` action will NOT turn it off while the constant is
True — the constant wins on purpose, so a restart cannot silently end a
capture you meant to keep running."""

_WHY_LOGGER = """\
    custom_components.kohler_anthem_plus.anthem_plus.raw_log

is set to debug. To stop it, call the `logger.set_level` action with that
same logger name set to `info` — no restart needed. Note this does not
survive a restart; to keep capture on across restarts, set
ENABLE_RAW_MQTT_LOG = True in the integration's const.py instead."""


class RawMqttLog:
    """Append raw MQTT payloads to rolling JSONL files, when switched on.

    `forced` comes from `ENABLE_RAW_MQTT_LOG` and pins the capture on. Independently, the
    module logger sitting at DEBUG turns it on at runtime — checked per message so it can be
    flipped from the UI mid-session, in both directions.
    """

    def __init__(
        self,
        directory: str,
        *,
        forced: bool = False,
        max_bytes: int = DEFAULT_MAX_BYTES,
        keep_files: int | None = DEFAULT_KEEP_FILES,
    ) -> None:
        self._directory = directory
        self._forced = forced
        self._max_bytes = max_bytes
        self._keep_files = keep_files
        self._lock = threading.Lock()
        self._handle: Any = None
        self._written = 0
        self._path: str | None = None
        # Logged once each way, so flipping the switch is visible in the HA log without the
        # capture itself ever going there.
        self._announced = False

    @property
    def enabled(self) -> bool:
        """True when capture is switched on, by either mechanism.

        Deliberately reads `.level` — the level set on *this exact logger* — and not
        `isEnabledFor()`, which reads the effective level and therefore inherits from
        ancestors. With `isEnabledFor`, debugging the integration as a whole
        (`custom_components.kohler_anthem_plus: debug`) or setting `logger: default: debug`
        would silently start writing capture files nobody asked for. A diagnostic that
        touches the disk should require being named.

        `.level` is `NOTSET` (0) until something sets it explicitly, so the default is off.
        """
        return self._forced or _SWITCH_LOGGER.level == logging.DEBUG

    @property
    def path(self) -> str | None:
        """The file currently being written, or None when not capturing."""
        return self._path

    def prepare(self) -> None:
        """Create the directory and open an empty capture file now, if switched on.

        Without this nothing appears on disk until the first message arrives — and this
        stream can be silent for hours (11.9 h is the record), so somebody who has just
        switched capture on has no way to tell whether it worked. An empty file that exists
        is a far better answer than a missing directory.

        Blocking file I/O: call it from an executor, not the event loop.
        """
        if not self.enabled:
            return
        with self._lock:
            if self._handle is None:
                try:
                    self._open_locked()
                except OSError as err:
                    _LOGGER.warning("Raw MQTT capture could not open a file: %s", err)

    def write(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        """Record one message. Cheap no-op when switched off."""
        if not self.enabled:
            # Handles the on->off transition: releases the file the moment capture stops,
            # rather than holding it open until unload.
            if self._handle is not None:
                self.close()
            return

        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "topic": topic,
            "qos": qos,
            "retain": retain,
        }
        # Exactly what arrived. Decoding is the consumer's problem, deliberately: a payload
        # that fails to parse is the most interesting kind, and re-serialising a parsed dict
        # would quietly normalise away key order, duplicates, and numeric formatting.
        try:
            record["payload"] = payload.decode("utf-8")
        except UnicodeDecodeError:
            record["payload_b64"] = base64.b64encode(payload).decode("ascii")

        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return

        with self._lock:
            try:
                self._write_line_locked(line)
            except OSError as err:
                # A diagnostic must never take the stream down with it.
                _LOGGER.warning("Raw MQTT capture write failed, disabling: %s", err)
                self._close_locked()
                self._forced = False

    def _write_line_locked(self, line: str) -> None:
        if self._handle is None or self._written >= self._max_bytes:
            self._open_locked()
        assert self._handle is not None
        encoded = line + "\n"
        self._handle.write(encoded)
        self._handle.flush()
        # Flushed per line on purpose: a capture is usually read while the thing being
        # debugged is still running, and buffered lines would not be there yet.
        self._written += len(encoded.encode("utf-8"))

    def _open_locked(self) -> None:
        self._close_locked()
        os.makedirs(self._directory, exist_ok=True)
        self._write_readme()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        suffix = binascii.hexlify(os.urandom(4)).decode("ascii")
        self._path = os.path.join(
            self._directory, f"mqtt_raw_{stamp}Z_{os.getpid()}_{suffix}.jsonl"
        )
        self._handle = open(self._path, "a", encoding="utf-8")
        self._written = 0
        self._prune()
        if not self._announced:
            self._announced = True
            _LOGGER.info("Raw MQTT capture is ON, writing to %s", self._path)

    def _write_readme(self) -> None:
        """Leave a note saying what these files are and how to stop them.

        Rewritten on every file open rather than written once, because *which* switch is
        active decides how to turn capture off — and the wrong instruction is worse than
        none. `logger.set_level` cannot stop a capture pinned by the constant.
        """
        try:
            with open(
                os.path.join(self._directory, "README.txt"), "w", encoding="utf-8"
            ) as fh:
                fh.write(
                    _README.format(
                        why=_WHY_FORCED if self._forced else _WHY_LOGGER,
                        max_mb=self._max_bytes // (1024 * 1024),
                        keep_desc=(
                            "No limit on the number of files — every one is kept."
                            if self._keep_files is None
                            else f"Only the newest {self._keep_files} are kept."
                        ),
                    )
                )
        except OSError:  # pragma: no cover - the capture still works without it
            pass

    def _prune(self) -> None:
        """Keep the newest `keep_files` captures so the directory stays bounded.

        A no-op when `keep_files` is None — unlimited is the default, and the owner wants
        this directory to hold everything.
        """
        if self._keep_files is None:
            return
        try:
            captures = sorted(
                (
                    os.path.join(self._directory, name)
                    for name in os.listdir(self._directory)
                    if name.startswith("mqtt_raw_") and name.endswith(".jsonl")
                ),
                key=os.path.getmtime,
            )
        except OSError:  # pragma: no cover
            return
        for stale in captures[: max(0, len(captures) - self._keep_files)]:
            try:
                os.remove(stale)
            except OSError:  # pragma: no cover
                pass

    def roll(self) -> str | None:
        """Start a new capture file immediately. Returns its path, or None if capture is off.

        For separating one experiment from the next without restarting Home Assistant. A
        capture that spans several runs has to be split by timestamp afterwards, and reading
        back which message belonged to which attempt is exactly the kind of bookkeeping that
        goes wrong when the runs are minutes apart.

        Blocking file I/O — call it from an executor, not the event loop.
        """
        if not self.enabled:
            return None
        with self._lock:
            self._close_locked()
            try:
                self._open_locked()
            except OSError as err:
                _LOGGER.warning("Could not start a new capture file: %s", err)
                return None
            return self._path

    def close(self) -> None:
        """Close the current capture file, if one is open."""
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:  # pragma: no cover
                pass
            if self._announced:
                _LOGGER.info("Raw MQTT capture is OFF (%s)", self._path)
                self._announced = False
        self._handle = None
        self._path = None
        self._written = 0
