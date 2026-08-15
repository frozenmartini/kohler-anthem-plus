"""Service actions for Kohler Anthem Plus.

Currently one: ``send_valve_hex``, the escape hatch for anything the entities cannot
express. The entities cover ordinary use; this covers the rest, by letting a raw command
word go straight to ``solowritesystem`` — the same endpoint every other control path uses.

**Only registered when the account has an Anthem valve.** ``solowritesystem`` is a GCS
endpoint — an Anthem Plus controller on its own has no valve to write to, and control there
goes through favourites instead. So on a HUB-only account this service does not appear at
all, rather than appearing and failing.

There is deliberately **no device field**. The service targets the valve because it can only
target the valve, and asking which one on a single-valve integration is friction for nothing.

**This service can run water.** It is validated before sending and its effect is logged, but
it is deliberately unrestricted otherwise: the point is to reach states the UI does not model.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_set_service_schema

from .const import DOMAIN, SERVICE_SEND_VALVE_HEX
from .coordinator import KohlerAnthemPlusCoordinator

_LOGGER = logging.getLogger(__name__)

ATTR_ZONE1_HEX = "zone1_hex"
ATTR_ZONE2_HEX = "zone2_hex"

# Either length the system itself shows: 8 for a command word, 16 for what the Zone Hex
# sensor displays — its second half is sensor feedback, which `_command_half` discards. Both
# are accepted so a value can be pasted straight out of that sensor without being edited.
# Any other length is a typo, and `async_send_valve_hex` re-checks it there too: this layer
# only exists so the UI can reject one without a round trip.
_HEX_WORD = vol.All(cv.string, cv.matches_regex(r"^(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{16})$"))

SEND_VALVE_HEX_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ZONE1_HEX): _HEX_WORD,
        # `vol.Maybe` because the UI submits "" for a touched-then-cleared optional text
        # field, which would otherwise fail the regex instead of meaning "closed".
        vol.Optional(ATTR_ZONE2_HEX): vol.Any("", None, _HEX_WORD),
    }
)


# The form as the UI renders it. `services.yaml` carries the same thing statically, as the
# fallback if the runtime override below cannot be applied; keep the two in step.
_FIELD_ZONE1 = {
    "name": "Zone 1 Hex",
    "required": True,
    "description": (
        'The 8-character code from the "Zone 1 Hex" sensor on the Anthem Valve '
        "device. Set the outlet switches and temperature the way you want them "
        "first, then copy the code."
    ),
    "example": "0184C801",
    "selector": {"text": None},
}
_FIELD_ZONE2 = {
    "name": "Zone 2 Hex",
    "required": False,
    "description": (
        'The 8-character code from the "Zone 2 Hex" sensor on the Anthem Valve '
        "device. Set the outlet switches and temperature the way you want them "
        "first, then copy the code."
    ),
    "example": "1184C801",
    "selector": {"text": None},
}
_SERVICE_DESCRIPTION = (
    "Send a command code straight to the Anthem valve, for anything the normal "
    "controls cannot do. Set the shower up how you want it with the outlet switches "
    "and temperature controls, then copy the code from the Zone Hex diagnostic "
    "sensor and paste it below. WARNING: this can start water."
)


def _async_describe_service(hass: HomeAssistant, two_zones: bool) -> None:
    """Publish the form, showing the Zone 2 field only on a two-zone system.

    `services.yaml` is static and cannot vary per installation, so a single-zone owner would
    otherwise be shown a Zone 2 box for a zone they do not have — with a sensor named in its
    description that does not exist on their device. `async_set_service_schema` overrides
    that description at runtime, which is the supported way to vary it.

    Best-effort: if this cannot be applied the static `services.yaml` still stands, so the
    action keeps working with one redundant field rather than not working at all.
    """
    fields: dict[str, Any] = {"zone1_hex": _FIELD_ZONE1}
    if two_zones:
        fields["zone2_hex"] = _FIELD_ZONE2
    try:
        async_set_service_schema(
            hass,
            DOMAIN,
            SERVICE_SEND_VALVE_HEX,
            {
                "name": "Send valve hex",
                "description": _SERVICE_DESCRIPTION,
                "fields": fields,
            },
        )
    except Exception:  # noqa: BLE001 - a cosmetic override must not break setup
        _LOGGER.debug("Could not override the service description", exc_info=True)


def _resolve_coordinator(hass: HomeAssistant) -> KohlerAnthemPlusCoordinator:
    """Find the loaded entry that owns a valve.

    No device field to disambiguate with, so this picks the one entry that *can* answer.
    Several valve-owning entries is a configuration nobody has, but it is better to say so
    than to write a command word to whichever one happened to load first.
    """
    entries: dict[str, KohlerAnthemPlusCoordinator] = hass.data.get(DOMAIN, {})
    with_valve = [c for c in entries.values() if c.gcs_device is not None]
    if not with_valve:
        raise HomeAssistantError(
            "No Anthem valve on this account — solowritesystem is a valve endpoint, and an "
            "Anthem Plus controller is driven through favourites instead"
        )
    if len(with_valve) > 1:
        raise HomeAssistantError(
            "More than one Anthem valve is set up; this action cannot tell them apart"
        )
    return with_valve[0]


async def _async_send_valve_hex(call: ServiceCall) -> ServiceResponse:
    """Handle `kohler_anthem_plus.send_valve_hex`."""
    coordinator = _resolve_coordinator(call.hass)
    result: dict[str, Any] = await coordinator.async_send_valve_hex(
        call.data[ATTR_ZONE1_HEX], call.data.get(ATTR_ZONE2_HEX) or None
    )
    return result


def async_register_services(
    hass: HomeAssistant, coordinator: KohlerAnthemPlusCoordinator
) -> None:
    """Register the integration's services, once, if this entry has a valve.

    Idempotent: `async_setup_entry` runs per entry and on every reload, and re-registering
    would otherwise stack handlers. A HUB-only entry registers nothing, so the action does
    not appear in the UI on an account that could never use it.
    """
    if coordinator.gcs_device is None:
        return
    if hass.services.has_service(DOMAIN, SERVICE_SEND_VALVE_HEX):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_VALVE_HEX,
        _async_send_valve_hex,
        schema=SEND_VALVE_HEX_SCHEMA,
        # Returns the decoded reading of both words, so a caller can confirm the word meant
        # what they thought without going to the log.
        supports_response=SupportsResponse.OPTIONAL,
    )
    # After registering, not before: the description attaches to a service that exists.
    # Whether the Zone 2 field is shown follows the topology detected at setup.
    _async_describe_service(hass, coordinator.model.uses_valve2)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the services when the last entry unloads.

    Tolerates never having been registered — a HUB-only account gets here having skipped
    registration entirely.
    """
    if hass.services.has_service(DOMAIN, SERVICE_SEND_VALVE_HEX):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_VALVE_HEX)
