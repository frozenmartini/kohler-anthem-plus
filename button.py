"""Buttons for the Kohler Anthem Plus integration.

One so far: start a new raw MQTT capture file. That exists because the natural way to get a
fresh capture — restart Home Assistant — costs a full reload, drops the MQTT connection, and
**clears the run-time cutoff tracking** (`ZoneCutoffDetector.forget()` on reconnect). None
of which anyone wants in the middle of a sequence of shower experiments.

Pressing this rolls the file instead: the current one is closed and a new one opened, so each
experiment lands in its own file rather than being separated by timestamp afterwards.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import KohlerAnthemPlusCoordinator
from .entity import KohlerControllerEntity, KohlerValveEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the capture button on whichever device this account has."""
    coordinator: KohlerAnthemPlusCoordinator = hass.data[DOMAIN][entry.entry_id]

    # The capture covers the whole account rather than one device, so it only needs to live
    # somewhere findable. The valve is the primary device where one exists; a controller-only
    # account gets it on the controller instead.
    if coordinator.gcs_device is not None:
        async_add_entities([ValveNewCaptureButton(coordinator)])
    elif coordinator.hub_device is not None:
        async_add_entities([ControllerNewCaptureButton(coordinator)])


class _NewCaptureMixin:
    """Roll the diagnostic capture files. Shared so both device variants behave identically.

    Rolls the raw MQTT capture **and** the cutoff debug log together. They are read as a
    pair, joined on `ts`, so splitting one per experiment while the other keeps accumulating
    would put the burden of matching them back on whoever reads them later.
    """

    _attr_name = "Start new MQTT capture"
    _attr_icon = "mdi:file-restore-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        raw_log = self.coordinator.raw_log
        cutoff_log = self.coordinator.cutoff_log
        if raw_log is None and cutoff_log is None:
            _LOGGER.warning("No diagnostic capture is set up; nothing to roll")
            return

        def _roll() -> tuple[str | None, str | None]:
            # Opens files and creates a directory — off the event loop.
            return (
                raw_log.roll() if raw_log else None,
                cutoff_log.roll() if cutoff_log else None,
            )

        raw_path, cutoff_path = await self.hass.async_add_executor_job(_roll)
        if raw_path is None and cutoff_path is None:
            _LOGGER.warning(
                "Both diagnostic captures are OFF, so there is nothing to roll. Turn them "
                "on with ENABLE_RAW_MQTT_LOG / ENABLE_CUTOFF_DEBUG_LOG in const.py, or the "
                "logger.set_level action on "
                "custom_components.kohler_anthem_plus.anthem_plus.raw_log / .cutoff_log"
            )
            return
        _LOGGER.warning(
            "Started new capture files — raw MQTT: %s; cutoff debug: %s",
            raw_path or "(off)",
            cutoff_path or "(off)",
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        raw_log = self.coordinator.raw_log
        cutoff_log = self.coordinator.cutoff_log
        return {
            "capture_enabled": bool(raw_log and raw_log.enabled),
            "current_file": (raw_log.path if raw_log else None),
            "cutoff_log_enabled": bool(cutoff_log and cutoff_log.enabled),
            "cutoff_log_file": (cutoff_log.path if cutoff_log else None),
        }


class ValveNewCaptureButton(_NewCaptureMixin, KohlerValveEntity, ButtonEntity):
    """Capture button on the Anthem Valve device."""

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_new_mqtt_capture"

    @property
    def available(self) -> bool:
        """A diagnostic action, usable whenever the entry is loaded."""
        return self.coordinator.last_update_success


class ControllerNewCaptureButton(_NewCaptureMixin, KohlerControllerEntity, ButtonEntity):
    """Capture button on a controller-only account. See :class:`ValveNewCaptureButton`."""

    def __init__(self, coordinator: KohlerAnthemPlusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_new_mqtt_capture"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
