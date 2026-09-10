"""Fan-out for the decision trails — one call site, any number of sinks.

The coordinator journals what the run-time cutoff detector and the warm-up watcher decide:
`journals.note("cutoff", "flow_end", zone=1, verdict="ignored", ...)`. Where that record
goes is not the caller's business. In a release it goes to exactly one place, the user's
Report Log (`report_log.py`), which ignores it unless an episode is on. On the author's
machine a second sink is added at setup — the always-on development capture that lives
outside the repository — and the call sites do not know or care.

Sinks are duck-typed rather than subclassed: a sink needs `note(journal, event, **fields)`
and `close()`, and may offer `wants_open` / `prepare()` when its writer cannot open a file
where it is called from. `note()` runs on the event loop (the detector runs there), so a
sink that wants to open or roll a file must not do it inline — it raises `wants_open` and
this fan-out hands its `prepare` to the executor scheduler it was built with. That replaces
the two-line check every call site used to carry.

No Home Assistant imports, like the rest of this package: the scheduler is a plain callable
the coordinator supplies (`hass.async_add_executor_job`), so this is testable offline.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

CUTOFF = "cutoff"
WARMUP = "warmup"


class JournalSink(Protocol):
    """What a sink must offer. `wants_open` and `prepare()` are optional extras."""

    def note(self, journal: str, event: str, **fields: Any) -> None: ...

    def close(self) -> None: ...


class Journals:
    """Every registered sink, addressed as one."""

    def __init__(self, schedule_prepare: Callable[[Callable[[], None]], Any]) -> None:
        """`schedule_prepare` runs a blocking callable off the event loop — an executor."""
        self._sinks: list[JournalSink] = []
        self._schedule_prepare = schedule_prepare

    @property
    def sinks(self) -> tuple[JournalSink, ...]:
        return tuple(self._sinks)

    def add(self, sink: JournalSink) -> None:
        """Register a sink. Order is preserved; a sink registered twice writes twice."""
        self._sinks.append(sink)

    def note(self, journal: str, event: str, **fields: Any) -> None:
        """Write one record to every sink, and get any sink its executor open if it asks."""
        for sink in self._sinks:
            sink.note(journal, event, **fields)
            if getattr(sink, "wants_open", False):
                self._schedule_prepare(sink.prepare)  # type: ignore[attr-defined]

    def close(self) -> None:
        """Release every sink's file. Blocking — call from an executor."""
        for sink in self._sinks:
            sink.close()
