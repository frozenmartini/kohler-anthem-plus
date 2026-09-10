"""Repairs — the fix flow behind the one fixable issue this integration raises.

`old_capture_folder`: every install before 0.4.1 wrote the author's always-on development
capture to `<config>/kohler_anthem_plus_raw/`, unasked and never pruned. Nothing ships that
writes it now. `__init__.py` raises the card when the folder is found (and not on the
author's install, where `_dev/` still writes it); this flow deletes it on confirmation.

Two rules, both about not deleting what is not ours: the folder is removed only if every
entry in it is one of the files that capture wrote (`mqtt_raw_*.jsonl`, `cutoff_*.jsonl`,
`warmup_*.jsonl`, the three READMEs), and the check is repeated at the moment of deletion,
not trusted from setup. Anything else in there means nothing is deleted and the flow says
so. All filesystem work runs in an executor.

Shape verified against https://developers.home-assistant.io/docs/core/platform/repairs/
on 2026-09-10 (the flow) and `homeassistant/components/hassio/strings.json` (the
`issues.<key>.fix_flow.step/abort` layout).
"""

from __future__ import annotations

import os

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_OLD_CAPTURE_FOLDER, OLD_CAPTURE_DIR

_OWN_PREFIXES = ("mqtt_raw_", "cutoff_", "warmup_")
_OWN_READMES = frozenset({"README.txt", "README-cutoff.txt", "README-warmup.txt"})


def _is_ours(name: str) -> bool:
    return name in _OWN_READMES or (
        name.endswith(".jsonl") and name.startswith(_OWN_PREFIXES)
    )


def inspect_old_capture_folder(path: str) -> tuple[int, int, bool] | None:
    """(files of ours, their bytes, anything else present) — or None when there is no folder.

    Blocking: executor only.
    """
    try:
        names = os.listdir(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return None
    count = size = 0
    foreign = False
    for name in names:
        full = os.path.join(path, name)
        if os.path.isdir(full) or not _is_ours(name):
            foreign = True
            continue
        count += 1
        try:
            size += os.path.getsize(full)
        except OSError:
            pass
    return count, size, foreign


def delete_old_capture_folder(path: str) -> bool:
    """Remove our files and then the folder. True when the folder is gone.

    Deletes file by file against the same pattern the inspection used, then `rmdir` — which
    refuses if anything else is still inside, so a file that appeared between the check and
    the delete is never taken with it. Blocking: executor only.
    """
    found = inspect_old_capture_folder(path)
    if found is None:
        return True
    if found[2]:
        return False
    for name in os.listdir(path):
        if _is_ours(name):
            os.remove(os.path.join(path, name))
    try:
        os.rmdir(path)
    except OSError:
        return False
    return True


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
            gone = await self.hass.async_add_executor_job(delete_old_capture_folder, path)
            if not gone:
                return self.async_abort(
                    reason="not_ours", description_placeholders={"path": shown}
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
