"""Repairs — the fix flow behind the one fixable issue this integration raises.

`old_capture_folder`: every install before 0.4.1 wrote the author's always-on development
capture to `<config>/kohler_anthem_plus_raw/`, unasked and never pruned. Nothing ships that
writes it now. `__init__.py` raises the card when the folder is found (and not on the
author's install, where `_dev/` still writes it); this flow deletes it on confirmation.

The rules are all about not deleting what is not ours:

- A file counts as ours only if its name is exactly what that capture produced —
  `mqtt_raw_|cutoff_|warmup_<UTC stamp>_<n>_<8 hex>.jsonl` or one of its three READMEs. A
  `mqtt_raw_notes.jsonl` someone made by hand is not ours. Neither is a symlink, whatever
  its name, nor a subdirectory.
- A symlinked root is never traversed: someone pointed the folder elsewhere on purpose.
- Deletion is all-or-nothing. The folder is first *renamed* aside (atomic), inspected again
  under its new name where nothing else can add to it, and only then emptied. Anything
  foreign puts it back untouched, and so does a failure part-way — the abort text the user
  sees is then true rather than hopeful.
- A folder that cannot be read is reported as present-and-foreign, not as absent, so the
  card is not cleared over a leftover that is still there.

**Transitional — remove later.** This module, `_async_offer_old_capture_cleanup` in
`__init__.py`, `ISSUE_OLD_CAPTURE_FOLDER` / `OLD_CAPTURE_DIR` in `const.py` and the
`issues.old_capture_folder` strings exist only to clean up after 0.1.0–0.4.0. Once every
install can be assumed to have passed through 0.4.1 — HACS offers the five latest releases,
so after five more releases nobody upgrades *from* 0.4.0 or earlier without going through
one that ran this — delete the lot in one commit. Same category as the
`_REMOVED_UNIQUE_ID_SUFFIXES` purge. Sunset pencilled in for 2027-03 or v0.9.0, whichever
first; a user who skipped that window deletes the folder by hand, nothing breaks.

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
_OWN_FILE = re.compile(r"^(?:mqtt_raw|cutoff|warmup)_\d{8}T\d{6}Z_\d+_[0-9a-f]{8}\.jsonl$")
_OWN_READMES = frozenset({"README.txt", "README-cutoff.txt", "README-warmup.txt"})

# `delete_old_capture_folder` outcomes; the two failures double as abort reasons in strings.json.
GONE = "gone"
NOT_OURS = "not_ours"
FAILED = "failed"


def _is_ours(name: str) -> bool:
    return name in _OWN_READMES or _OWN_FILE.match(name) is not None


def inspect_old_capture_folder(path: str) -> tuple[int, int, bool] | None:
    """(files of ours, their bytes, anything else present) — or None when there is no folder.

    None means *absent*, nothing else: a folder that cannot be listed, a regular file under
    that name, or a symlink all come back as present with `foreign=True`, so the caller
    neither clears the card nor deletes anything. Blocking: executor only.
    """
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


def _put_back(quarantine: str, path: str) -> None:
    try:
        os.rename(quarantine, path)
    except OSError as err:
        _LOGGER.warning("Could not move %s back to %s: %s", quarantine, path, err)


def delete_old_capture_folder(path: str) -> str:
    """Remove the folder if it holds only our files. Returns GONE, NOT_OURS or FAILED.

    The folder is renamed aside first — one atomic step, after which nothing else knows
    where it is — then inspected again and emptied. Anything foreign, or any error while
    emptying, puts it back under its original name, so NOT_OURS and FAILED both mean the
    folder is where it was. Blocking: executor only.
    """
    if os.path.islink(path):
        return NOT_OURS
    quarantine = path + ".deleting"
    try:
        os.rename(path, quarantine)
    except FileNotFoundError:
        return GONE
    except OSError as err:
        _LOGGER.warning("Could not set %s aside for deletion: %s", path, err)
        return FAILED
    found = inspect_old_capture_folder(quarantine)
    if found is None:
        return GONE
    if found[2]:
        _put_back(quarantine, path)
        return NOT_OURS
    try:
        for name in os.listdir(quarantine):
            os.remove(os.path.join(quarantine, name))
        os.rmdir(quarantine)
    except OSError as err:
        _LOGGER.warning("Deleting %s failed part-way: %s", path, err)
        _put_back(quarantine, path)
        return FAILED
    return GONE


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
                    reason=outcome, description_placeholders={"path": shown}
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
