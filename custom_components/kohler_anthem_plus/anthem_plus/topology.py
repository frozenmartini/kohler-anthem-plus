"""Detect how many outlets sit on each valve, without asking the user.

Two sources, both verified live, in preference order:

1. **The valve itself** — ``gcs-state/gcsadvancestate/{deviceId}`` returns a
   ``valveSettings[]`` array with ``noOfOutlets`` per valve. Authoritative, and needs no
   controller. Only available when the account has a GCS device.
2. **The controller** — ``hub-configuration/{deviceId}`` reports ``configuredoutlets`` per
   zone. The only option on a HUB-only account, which by definition has no valve id to
   query.

Either yields the split directly, so nothing has to be inferred from a flat outlet count or
from gaps in outlet ids. (Outlet ids turn out to be dense ``0..N-1`` with the zone boundary
at N/2, but that arithmetic is never needed: both sources group outlets by valve already.)

Detection can still fail — an unreachable device, an unexpected payload — so callers must
keep a manual fallback.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# valveSettings entries are named "Valve1", "Valve2", … in order.
_VALVE_PREFIX = "valve"


def _as_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def topology_from_valve_settings(setting: dict) -> tuple[int, int] | None:
    """Read ``(outlets_valve1, outlets_valve2)`` from a valve settings block.

    ``setting`` is the ``setting`` object of a ``gcsadvancestate`` response. Its
    ``valveSettings`` array carries all eight valve slots; unpopulated ones report
    ``noOfOutlets`` of 0.

    The sibling ``outlets`` total is deliberately ignored — it was ``null`` on the tested
    system while the per-valve counts were correct.
    """
    entries = (setting or {}).get("valveSettings")
    if not isinstance(entries, list):
        return None

    counts: dict[int, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("valve") or "").strip().lower()
        if not name.startswith(_VALVE_PREFIX):
            continue
        index = _as_int(name[len(_VALVE_PREFIX) :])
        if index in (1, 2):
            counts[index] = _as_int(entry.get("noOfOutlets"))

    first, second = counts.get(1, 0), counts.get(2, 0)
    if first <= 0:
        return None
    return first, second


def topology_from_hub_configuration(configuration: dict) -> tuple[int, int] | None:
    """Read ``(zone1, zone2)`` outlet counts from a ``hub-configuration`` response.

    Used for HUB-only accounts, which have no valve to query directly.

    Reads ``configuredoutlets``, **not** ``parts.valve1``/``valve2``. Those count physical
    valve units, while the GCS API counts zones — so a single 6-outlet unit reports
    ``parts.valve2: NotConnected`` while genuinely having a populated zone 2.
    """
    config = configuration or {}
    first = _as_int((config.get("zoneone") or {}).get("configuredoutlets"))
    second = _as_int((config.get("zonetwo") or {}).get("configuredoutlets"))
    if first <= 0:
        return None
    return first, second


def describe(topology: tuple[int, int]) -> str:
    """A short human summary, e.g. ``"2 zones, 3 + 3 outlets"``."""
    first, second = topology
    if not second:
        return f"1 zone, {first} outlet{'s' if first != 1 else ''}"
    return f"2 zones, {first} + {second} outlets"
