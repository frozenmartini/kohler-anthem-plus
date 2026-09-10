"""Repairs — the fix flow behind the one fixable issue this integration raises.

`old_capture_folder`: every install before 0.4.1 wrote the author's always-on development
capture to `<config>/kohler_anthem_plus_raw/`, unasked and never pruned. Nothing ships that
writes it now. `__init__.py` raises the card when the folder is found (and not on the
author's install, where `_dev/` still writes it); this flow deletes it on confirmation.

The rules are all about not deleting what is not ours:

- A file counts as ours only if its name is exactly what that capture produced —
  `mqtt_raw_|cutoff_|warmup_<UTC stamp>_<n>_<8 hex>.jsonl` (ASCII digits) or one of its
  three READMEs. A `mqtt_raw_notes.jsonl` someone made by hand is not ours. Neither is a
  symlink, whatever its name, nor a subdirectory.
- A symlinked root is never traversed: someone pointed the folder elsewhere on purpose.
- Nothing foreign is ever deleted. The folder is first *renamed* aside (one atomic step,
  to a fixed sibling name), inspected again under that name, and only then emptied —
  file by file, each unlink guarded by the same name check, so even something that
  appears after the inspection is left alone and makes the final `rmdir` fail instead.
  Anything foreign puts the folder back untouched. What
  is *not* promised is that our own files survive a failure part-way: they are the
  leftover being deleted, and losing half of them loses nothing anyone wanted.
- Every outcome the user is shown is true. A failure that leaves the folder where it was
  says so; a failure that leaves it under the aside name says *that*, with the name. A
  folder that cannot be read is reported as present-and-foreign, not as absent, so the
  card is not cleared over a leftover that is still there — and a folder stranded under
  the aside name by an interrupted run counts as present too, and the card says where.

**Transitional — remove later.** This module, `_async_offer_old_capture_cleanup` in
`__init__.py`, `ISSUE_OLD_CAPTURE_FOLDER` / `OLD_CAPTURE_DIR` in `const.py` and the
`issues.old_capture_folder` strings exist only to clean up after 0.1.0–0.4.0. HACS lets a
user jump straight from any old release to the latest, so no number of releases proves
every install has passed through this code; the sunset is a judgement, not a guarantee.
Pencilled in for 2027-03 or v0.9.0, whichever first: after that an install jumping from
0.4.0 or earlier keeps its folder and deletes it by hand — inert files, nothing breaks.
Same category as the `_REMOVED_UNIQUE_ID_SUFFIXES` purge; delete the lot in one commit.

All filesystem work runs in an executor. Shape verified against
https://developers.home-assistant.io/docs/core/platform/repairs/ on 2026-09-10 (the flow)
and `homeassistant/components/hassio/strings.json` (the `issues.<key>.fix_flow.step/abort`
layout).
"""

from __future__ import annotations

import logging
import os
import re

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_OLD_CAPTURE_FOLDER, OLD_CAPTURE_DIR

_LOGGER = logging.getLogger(__name__)

# Exactly the names the retired capture wrote: `cutoff_20260910T223325Z_72_6f4e0990.jsonl`.
# `[0-9]`, not `\d`: Python's `\d` also matches non-ASCII digits, and this decides deletion.
# `fullmatch`, not `$`: `$` also matches before a trailing newline, which a filename may carry.
_OWN_FILE = re.compile(r"(?:mqtt_raw|cutoff|warmup)_[0-9]{8}T[0-9]{6}Z_[0-9]+_[0-9a-f]{8}\.jsonl")
_OWN_READMES = frozenset({"README.txt", "README-cutoff.txt", "README-warmup.txt"})
ASIDE_SUFFIX = ".deleting"

# `delete_old_capture_folder` outcomes; the failures double as abort reasons in strings.json.
GONE = "gone"
NOT_OURS = "not_ours"
FAILED = "failed"  # folder untouched, where it was
STRANDED = "stranded"  # folder (or what is left of it) sits under the aside name


def _is_ours(name: str) -> bool:
    return name in _OWN_READMES or _OWN_FILE.fullmatch(name) is not None


def _inspect_dir(path: str) -> tuple[int, int, bool] | None:
    if os.path.islink(path):
        return 0, 0, True
    try:
        names = os.listdir(path)
    except FileNotFoundError:
        return None
    except OSError as err:
        _LOGGER.warning("Cannot read %s: %s", path, err)
        return 0, 0, True
    count = size = 0
    foreign = False
    for name in names:
        full = os.path.join(path, name)
        if os.path.islink(full) or os.path.isdir(full) or not _is_ours(name):
            foreign = True
            continue
        count += 1
        try:
            size += os.path.getsize(full)
        except OSError:
            pass
    return count, size, foreign


def inspect_old_capture_folder(path: str) -> tuple[int, int, bool] | None:
    """(files of ours, their bytes, anything else present) — or None when there is no folder.

    None means *absent*, nothing else: a folder that cannot be listed, a regular file under
    that name, or a symlink all come back as present with `foreign=True`, so the caller
    neither clears the card nor deletes anything. A folder left under the aside name by an
    interrupted delete is reported in place of the missing original. Blocking: executor only.
    """
    found = _inspect_dir(path)
    if found is None:
        found = _inspect_dir(path + ASIDE_SUFFIX)
    return found


def _put_back(aside: str, path: str) -> bool:
    try:
        os.rename(aside, path)
    except OSError as err:
        _LOGGER.warning("Could not move %s back to %s: %s", aside, path, err)
        return False
    return True


def _remove_ours(aside: str) -> bool:
    """Remove our files from a folder already inspected, then the folder. False on any error.

    Each unlink is guarded by name, so something foreign that appears after the inspection
    is never removed; it makes the final `rmdir` fail instead, and the caller reports that.
    """
    try:
        for name in os.listdir(aside):
            full = os.path.join(aside, name)
            if _is_ours(name) and not os.path.islink(full) and not os.path.isdir(full):
                os.remove(full)
        os.rmdir(aside)
    except OSError as err:
        _LOGGER.warning("Deleting %s failed part-way: %s", aside, err)
        return False
    return True


def delete_old_capture_folder(path: str) -> str:
    """Remove the folder if it holds only our files. GONE, NOT_OURS, FAILED or STRANDED.

    Renamed aside first — one atomic step — then inspected again and emptied by name. Anything foreign puts it back (NOT_OURS). A
    failure before anything was removed leaves it where it was (FAILED); a failure after
    the rename that cannot be undone leaves it under the aside name (STRANDED), and the
    abort text names that. Blocking: executor only.
    """
    aside = path + ASIDE_SUFFIX
    if os.path.lexists(aside):
        # Left by an interrupted run. Ours → clear it first; anything else → hands off.
        # Before the symlink check so a stale aside is cleared even if the original path
        # has since become a link.
        stale = _inspect_dir(aside)
        if stale is not None and (stale[2] or not _remove_ours(aside)):
            return STRANDED
    if os.path.islink(path):
        return NOT_OURS
    try:
        os.rename(path, aside)
    except FileNotFoundError:
        return GONE
    except OSError as err:
        _LOGGER.warning("Could not set %s aside for deletion: %s", path, err)
        return FAILED
    found = _inspect_dir(aside)
    if found is None:
        return GONE
    if found[2]:
        return NOT_OURS if _put_back(aside, path) else STRANDED
    if _remove_ours(aside):
        return GONE
    return FAILED if _put_back(aside, path) else STRANDED


class OldCaptureFolderFlow(RepairsFlow):
    """Confirm, then delete `<config>/kohler_anthem_plus_raw/` if it holds only our files."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        path = self.hass.config.path(OLD_CAPTURE_DIR)
        shown = f"/config/{OLD_CAPTURE_DIR}"
        if user_input is not None:
            outcome = await self.hass.async_add_executor_job(delete_old_capture_folder, path)
            if outcome != GONE:
                # The folder is still where it was; the card stays so they can retry or
                # Ignore it once they have looked.
                return self.async_abort(
                    reason=outcome,
                    description_placeholders={"path": shown, "aside": shown + ASIDE_SUFFIX},
                )
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_OLD_CAPTURE_FOLDER)
            return self.async_create_entry(title="", data={})

        found = await self.hass.async_add_executor_job(inspect_old_capture_folder, path)
        count, size = (found[0], found[1]) if found else (0, 0)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "path": shown,
                "aside": shown + ASIDE_SUFFIX,
                "count": str(count),
                "size_mb": f"{size / (1024 * 1024):.1f}",
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Hand Home Assistant the flow for a fixable issue of ours."""
    if issue_id == ISSUE_OLD_CAPTURE_FOLDER:
        return OldCaptureFolderFlow()
    return ConfirmRepairFlow()
