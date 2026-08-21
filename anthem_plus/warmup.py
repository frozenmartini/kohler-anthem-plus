"""Warmup auto-restore: the decision, kept out of Home Assistant so it can be tested.

The valve's warmup mode does not stay where it is put. Four times between 2026-08-13 and
08-18 it reverted to ``warmUpDisabled`` on its own, inside bursts of configuration re-sync
traffic, with no command on the MQTT channel and nothing from Home Assistant. Reboots are
ruled out: the mode survives those. See ``docs/gcs/api.md`` §3e.

This module holds the judgements that have to be right, as pure functions: *is this disable
one we should undo?* (``should_restore_warmup``), *what do we put back?* (``restore_target``),
and *what does this observation deserve in the journal?* (``journal_event``). The scheduling,
the waiting and the writing live in the coordinator, where they need Home Assistant; the
judgement lives here, where a test can reach it.

All three are here for the same reason: each one was a bug where the coordinator's behaviour
and its own description of that behaviour had drifted apart, and a comment cannot be run.
"""

from __future__ import annotations

from .const import WARMUP_DISABLED

__all__ = ["journal_event", "restore_target", "should_restore_warmup"]


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


def restore_target(taken_away: str | None, remembered: str | None) -> str | None:
    """Which mode a restore should reinstate, given the two things we might know.

    ``taken_away`` is ``before`` from the announcement that disabled warmup — the mode the
    valve was demonstrably in one message ago. ``remembered`` is the persisted
    ``last_warmup_mode``.

    **``taken_away`` wins**, because it is the more current of the two and cannot be stale:
    it comes from the same announcement being acted on, while ``remembered`` survives across
    restarts and may describe a mode that has since been changed.

    This exists as its own function because the bug it prevents was precisely the two
    disagreeing. On 2026-08-20 the coordinator asked ``should_restore_warmup`` — which
    refuses unless ``before`` is a known enabled mode, so it had *proved* one existed — and
    then looked the target up in ``remembered``, which was ``None`` because that session had
    only ever read the mode over REST, never seen it announced. The journal recorded
    ``"before": "warmUpAllOutletsWithNoStartDelay"`` beside ``"restores_to": null`` and the
    valve stayed disabled for seven hours.

    So the invariant worth testing, and the one ``test_warmup_restore_target.py`` asserts, is
    that **whenever ``should_restore_warmup`` returns True, this returns a mode.**
    """
    for mode in (taken_away, remembered):
        if mode and mode != WARMUP_DISABLED:
            return mode
    return None


def journal_event(before: str | None, after: str | None, *, announced: bool) -> str | None:
    """Which journal record one warmup observation deserves, or ``None`` for silence.

    ``before`` / ``after`` are the modes either side of applying one MQTT message.
    ``announced`` says that message was a ``GCS_WARM_STS`` — the valve volunteering its mode.
    The flag only changes the answer when the mode did **not** move, because a move can come
    from nowhere else: ``_apply_warmup`` is the only envelope handler that writes
    ``warmup_mode``.

    * ``"mode"`` — the mode moved. Always recorded.
    * ``"announced"`` — the valve restated a mode it was already in.
    * ``None`` — an ordinary message that happens not to touch warmup. The overwhelming
      majority: the coordinator calls this for **every** valve message, and 3057 of the 3143
      in the raw corpus are not warmup announcements at all.

    ⚠️ **The bug this exists to prevent, 2026-08-21.** The coordinator returned early
    whenever ``after == before``, so a repeat announcement was discarded along with the
    uninteresting messages — while the comment beside the ``mode`` record claimed "every
    announcement is journalled, not only the disables". It was not true, and the repeats are
    not a rare edge case: **28 of the 43 announcements in the raw corpus restate the value
    before them.** They are the valve volunteering a timestamp, which is the only kind of
    evidence this journal can gather about a device whose real control channel is an RJ wired
    link that cannot be sniffed.

    Kept as a pure function for the same reason as ``restore_target``: the defect was the
    journal's behaviour disagreeing with the journal's own description of it, so the
    judgement is somewhere a test can reach without Home Assistant. **The invariant is
    stated here rather than only in a test**, because the test scripts in
    ``kohler-work/tests/`` are scratch and expected to be discarded — so this docstring is
    the durable record of it:

        an announcement is never silently dropped; only a message that carries no warmup
        mode, or one that moved nothing, produces no record.
    """
    if after is None:
        return None
    if after == before:
        return "announced" if announced else None
    return "mode"
