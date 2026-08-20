"""Warmup auto-restore: the decision, kept out of Home Assistant so it can be tested.

The valve's warmup mode does not stay where it is put. Four times between 2026-08-13 and
08-18 it reverted to ``warmUpDisabled`` on its own, inside bursts of configuration re-sync
traffic, with no command on the MQTT channel and nothing from Home Assistant. Reboots are
ruled out: the mode survives those. See ``docs/gcs/api.md`` §3e.

This module holds the one question that has to be right — *is this disable one we should undo?*
— as a pure function. The scheduling, the waiting and the writing live in the coordinator,
where they need Home Assistant; the judgement lives here, where a test can reach it.
"""

from __future__ import annotations

from .const import WARMUP_DISABLED

__all__ = ["should_restore_warmup"]


def should_restore_warmup(
    before: str | None,
    after: str | None,
    *,
    enabled: bool,
    self_write_mode: str | None,
    self_write_age: float | None,
    grace_seconds: float,
) -> bool:
    """Whether a warmup mode change is a disable this integration should undo.

    ``before`` / ``after`` are the modes either side of one MQTT announcement. ``enabled`` is
    the auto-restore switch. ``self_write_mode`` and ``self_write_age`` describe the most
    recent warmup write *we* made — the mode written, and how many seconds ago.

    True only for a genuine, externally-caused transition into disabled:

    * **Only a mode we watched being taken away.** ``before`` must be a known enabled mode.
      A repeat announcement is not a transition — the valve restates its mode about 4 s after
      every boot, and it rebooted 25 times in a week here, so treating each restatement as a
      fresh event would fire a restore per reboot. Neither is the *first* mode we ever see:
      arriving to find warmup already off is not something being disabled, and turning it on
      would be this integration enabling a feature nobody asked it to.
    * **A disable we caused is not a fault.** Choosing `Off` on the dropdown writes
      ``warmUpDisabled``, and the valve echoes it back ~3.4 s later. Without this check that
      echo would be read as the device misbehaving and `Off` could never be selected.
      Scoped to the *mode* written, not merely to having written recently: our own switch to
      an enabled mode says nothing about a disable that follows it.
    * **Anything that is not a disable** is somebody setting a mode, which is not our business.
    """
    if not enabled:
        return False
    if after != WARMUP_DISABLED:
        return False
    if before is None or before == WARMUP_DISABLED:
        return False
    if (
        self_write_mode == WARMUP_DISABLED
        and self_write_age is not None
        and self_write_age <= grace_seconds
    ):
        return False
    return True
