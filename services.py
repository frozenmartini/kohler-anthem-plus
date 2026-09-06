"""Service actions for Kohler Anthem Plus.

Two, both writing the valve through ``solowritesystem`` — the same endpoint every other
control path uses:

* ``custom_shower`` — the form. Tick outlets, pick a temperature, optionally a flow, and it
  goes to the valve as **one** complete command. Added 2026-09-06 after GitHub issue #1 showed
  what every automation built in the UI turns into — an outlet action, then a temperature
  action — and that the valve cannot take two commands back to back: the second is built from
  a report that predates the first, and closes what the first opened. The words sent here come
  from the form and from nothing else; see `anthem_plus.valve_hex.encode_shower`.
* ``send_valve_hex`` — the escape hatch, a raw command word for anything neither the entities
  nor the form can express.

**Only registered when the account has an Anthem valve.** ``solowritesystem`` is a GCS
endpoint — an Anthem Plus controller on its own has no valve to write to, and control there
goes through favourites instead. So on a HUB-only account neither service appears at all,
rather than appearing and failing.

There is deliberately **no device field**. The services target the valve because they can
only target the valve, and asking which one on a single-valve integration is friction for
nothing.

**These services can run water.** Input is validated before sending and the effect is logged,
but they are deliberately unrestricted otherwise: the point is to reach states the UI does
not model.
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
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_set_service_schema

from .anthem_plus.models import ValveModel
from .anthem_plus.valve_hex import (
    FLOW_BYTE_MAX,
    FLOW_BYTE_MIN,
    FLOW_PER_PERCENT,
    ValveHexError,
    encode_shower,
    unit_to_celsius,
)
from .const import (
    DEFAULT_FLOW_PERCENT,
    DOMAIN,
    SERVICE_CUSTOM_SHOWER,
    SERVICE_SEND_VALVE_HEX,
    UI_TEMPERATURE_MAX_F,
    UI_TEMPERATURE_MIN_F,
)
from .coordinator import KohlerAnthemPlusCoordinator

_LOGGER = logging.getLogger(__name__)

ATTR_ZONE1_HEX = "zone1_hex"
ATTR_ZONE2_HEX = "zone2_hex"

ATTR_ZONE1_TEMPERATURE = "zone1_temperature"
ATTR_ZONE2_TEMPERATURE = "zone2_temperature"
ATTR_FLOW = "flow"
ATTR_KEEP_ON = "keep_on_after_warmup"
# Flat data keys, zone by zone. The form groups them into one section per zone for display
# only; the call data is flat. Zone 2's temperature is optional and follows zone 1's.
_ZONE_TEMPERATURE_FIELDS = {1: ATTR_ZONE1_TEMPERATURE, 2: ATTR_ZONE2_TEMPERATURE}
_ZONE_OUTLET_FIELDS: dict[int, tuple[str, ...]] = {
    1: ("zone1_outlet_1", "zone1_outlet_2", "zone1_outlet_3"),
    2: ("zone2_outlet_1", "zone2_outlet_2", "zone2_outlet_3"),
}
_ZONE_SECTIONS = {1: "zone_1", 2: "zone_2"}
# The flow byte's own range, as a percentage — 0x10 (16) to 0xC8 (200) is 8 % to 100 %.
_FLOW_MIN_PERCENT = FLOW_BYTE_MIN // FLOW_PER_PERCENT
_FLOW_MAX_PERCENT = FLOW_BYTE_MAX // FLOW_PER_PERCENT

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

# Temperatures are range-checked in the handler, not here: the bounds depend on the account's
# unit, which the schema does not know. The booleans default to off so a YAML call may leave
# them out; the form marks them required for a display reason explained at `_FIELD_OUTLETS`.
CUSTOM_SHOWER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ZONE1_TEMPERATURE): vol.Coerce(float),
        vol.Optional(ATTR_ZONE2_TEMPERATURE): vol.Any(None, vol.Coerce(float)),
        vol.Optional(ATTR_FLOW): vol.All(
            vol.Coerce(float), vol.Range(min=_FLOW_MIN_PERCENT, max=_FLOW_MAX_PERCENT)
        ),
        vol.Optional(ATTR_KEEP_ON, default=False): cv.boolean,
        **{
            vol.Optional(key, default=False): cv.boolean
            for keys in _ZONE_OUTLET_FIELDS.values()
            for key in keys
        },
    }
)


# The forms as the UI renders them. `services.yaml` carries the same thing statically, as the
# fallback if the runtime override below cannot be applied; keep the two in step —
# `tests/test_service_form.py` checks that they are.
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

_CUSTOM_SHOWER_DESCRIPTION = (
    "Start the shower with the outlets and temperature you choose, sent to the valve as "
    "one command. This is the reliable way to open an outlet and set its temperature from "
    "a single automation step. Outlets you leave off are closed, and leaving every outlet "
    "off stops the shower. On a valve with warm-up enabled the valve warms up first and "
    "then pauses for two minutes, just as it always does; turn on \"Keep shower on after "
    "warm-up\" (beta) to have it carry on with your outlets and temperature the moment "
    "that pause begins. WARNING: this can start water."
)
# The static form shows Fahrenheit and the K-28212's outlets; the runtime override swaps in
# the account's unit and range and drops the zones and outlets the valve does not have.
_FIELD_ZONE1_TEMPERATURE = {
    "name": "Zone 1 temperature",
    "required": True,
    "description": "Target temperature for zone 1, in the unit your account uses.",
    "example": 104,
    "selector": {
        "number": {
            "min": 80,
            "max": 113,
            "step": 1,
            "unit_of_measurement": "°F",
            "mode": "slider",
        }
    },
}
_FIELD_ZONE2_TEMPERATURE = {
    "name": "Zone 2 temperature",
    "required": False,
    "description": "Target temperature for zone 2. Leave it unset to use the zone 1 temperature.",
    "example": 104,
    "selector": {
        "number": {
            "min": 80,
            "max": 113,
            "step": 1,
            "unit_of_measurement": "°F",
            "mode": "slider",
        }
    },
}
# `required: True` on every boolean is a display decision, not validation. The automation
# editor puts an "include this field" checkbox in front of each optional field, which next to
# a toggle is two switches for one thing (owner, 2026-09-06, after the first live test). A
# required boolean is shown as the toggle alone and pre-filled off — frontend
# `ha-service-control`: `showOptionalToggle` is false for a required field, and a required
# boolean with no default is set to `false` when the action is chosen. The schema above still
# defaults them, so a YAML call may leave them out.
_FIELD_OUTLETS = {
    "zone1_outlet_1": {
        "name": "Zone 1 outlet 1",
        "required": True,
        "selector": {"boolean": None},
    },
    "zone1_outlet_2": {
        "name": "Zone 1 outlet 2",
        "required": True,
        "selector": {"boolean": None},
    },
    "zone1_outlet_3": {
        "name": "Zone 1 outlet 3",
        "required": True,
        "selector": {"boolean": None},
    },
    "zone2_outlet_1": {
        "name": "Zone 2 outlet 1",
        "required": True,
        "selector": {"boolean": None},
    },
    "zone2_outlet_2": {
        "name": "Zone 2 outlet 2",
        "required": True,
        "selector": {"boolean": None},
    },
    "zone2_outlet_3": {
        "name": "Zone 2 outlet 3",
        "required": True,
        "selector": {"boolean": None},
    },
}
# "(beta)" in the name and "Beta" in the description are deliberate and mirrored in the docs
# and release notes (owner, 2026-09-06): the resume has run on one valve, so the form says so.
_FIELD_KEEP_ON = {
    "name": "Keep shower on after warm-up (beta)",
    "required": True,
    "description": (
        "Beta, tested on one valve so far. Only matters when the valve's warm-up is "
        "enabled. After warming up, the valve pauses for two minutes, just as it always "
        "does. With this on, the shower carries on with your outlets and temperature the "
        "moment that pause begins. Off, the valve's two-minute pause runs as usual."
    ),
    "selector": {"boolean": None},
}
_FIELD_FLOW = {
    "name": "Flow",
    "required": False,
    "description": (
        "Percentage of full flow, from 8 to 100. Leave it unset for full flow. The flow "
        "set here holds only until someone presses the flow button on the touchscreen, "
        "which takes over from then on."
    ),
    "example": 100,
    "selector": {
        "number": {
            "min": 8,
            "max": 100,
            "step": 1,
            "unit_of_measurement": "%",
            "mode": "box",
        }
    },
}
_SECTION_NAMES = {
    "zone_1": "Zone 1",
    "zone_2": "Zone 2",
    "advanced_fields": "Advanced",
}


def _temperature_bounds(unit: str) -> tuple[float, float, str]:
    """The slider's range in the account's unit, as the number entity computes it.

    Same maths as `ZoneTemperatureNumber`: the bounds are stated in Fahrenheit
    (`UI_TEMPERATURE_MIN_F` / `UI_TEMPERATURE_MAX_F`) and rounded for a Celsius account.
    """
    if unit.lower().startswith("f"):
        return float(UI_TEMPERATURE_MIN_F), float(UI_TEMPERATURE_MAX_F), "°F"
    return (
        float(round(unit_to_celsius(UI_TEMPERATURE_MIN_F, "Fahrenheit"))),
        float(round(unit_to_celsius(UI_TEMPERATURE_MAX_F, "Fahrenheit"))),
        "°C",
    )


def _async_describe_service(hass: HomeAssistant, two_zones: bool) -> None:
    """Publish the `send_valve_hex` form, showing the Zone 2 field only on a two-zone system.

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


def _async_describe_custom_shower(
    hass: HomeAssistant, model: ValveModel, temperature_unit: str
) -> None:
    """Publish the `custom_shower` form for this installation.

    Three things the static `services.yaml` cannot know: the account's temperature unit and
    therefore the slider's range, which zones the valve has, and how many outlets each zone
    has (`ValveModel.outlets_in_zone`). Same best-effort rule as `_async_describe_service`.
    """
    low, high, symbol = _temperature_bounds(temperature_unit)

    def temperature_field(static: dict[str, Any]) -> dict[str, Any]:
        return {
            **static,
            "selector": {
                "number": {
                    **static["selector"]["number"],
                    "min": int(low),
                    "max": int(high),
                    "unit_of_measurement": symbol,
                }
            },
        }

    statics = {1: _FIELD_ZONE1_TEMPERATURE, 2: _FIELD_ZONE2_TEMPERATURE}
    fields: dict[str, Any] = {}
    for zone in model.zones:
        keys = _ZONE_OUTLET_FIELDS[zone][: model.outlets_in_zone(zone)]
        section = _ZONE_SECTIONS[zone]
        fields[section] = {
            "name": _SECTION_NAMES[section],
            "collapsed": False,
            "fields": {
                _ZONE_TEMPERATURE_FIELDS[zone]: temperature_field(statics[zone]),
                **{key: _FIELD_OUTLETS[key] for key in keys},
            },
        }
    fields[ATTR_KEEP_ON] = _FIELD_KEEP_ON
    fields["advanced_fields"] = {
        "name": _SECTION_NAMES["advanced_fields"],
        "collapsed": True,
        "fields": {ATTR_FLOW: _FIELD_FLOW},
    }
    try:
        async_set_service_schema(
            hass,
            DOMAIN,
            SERVICE_CUSTOM_SHOWER,
            {
                "name": "Custom shower",
                "description": _CUSTOM_SHOWER_DESCRIPTION,
                "fields": fields,
            },
        )
    except Exception:  # noqa: BLE001 - a cosmetic override must not break setup
        _LOGGER.debug("Could not override the custom_shower description", exc_info=True)


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


async def _async_custom_shower(call: ServiceCall) -> ServiceResponse:
    """Handle `kohler_anthem_plus.custom_shower`.

    Builds both words from the form and hands them to the coordinator as one write. Each
    temperature is checked against the same bounds the temperature sliders offer, in the
    account's unit, so a YAML caller cannot send the valve full cold by typing 0. Zone 2's
    temperature follows zone 1's when it is not given.
    """
    coordinator = _resolve_coordinator(call.hass)
    unit = coordinator.temperature_unit
    low, high, symbol = _temperature_bounds(unit)
    zone1 = float(call.data[ATTR_ZONE1_TEMPERATURE])
    zone2_raw = call.data.get(ATTR_ZONE2_TEMPERATURE)
    zone2 = zone1 if zone2_raw is None else float(zone2_raw)
    for zone, temperature in ((1, zone1), (2, zone2)):
        if not low <= temperature <= high:
            raise ServiceValidationError(
                f"Zone {zone} temperature must be between {low:g} and {high:g} {symbol}; "
                f"got {temperature:g}"
            )
    zone_flags = {
        zone: [bool(call.data.get(key, False)) for key in keys]
        for zone, keys in _ZONE_OUTLET_FIELDS.items()
    }
    flow = call.data.get(ATTR_FLOW)
    try:
        word1, word2 = encode_shower(
            coordinator.model,
            {1: unit_to_celsius(zone1, unit), 2: unit_to_celsius(zone2, unit)},
            DEFAULT_FLOW_PERCENT if flow is None else float(flow),
            zone_flags,
        )
    except ValveHexError as err:
        raise ServiceValidationError(str(err)) from err
    keep_on = bool(call.data.get(ATTR_KEEP_ON, False))
    result: dict[str, Any] = await coordinator.async_custom_shower(
        word1, word2, keep_on_after_warmup=keep_on
    )
    return {**result, ATTR_KEEP_ON: keep_on}


def async_register_services(
    hass: HomeAssistant, coordinator: KohlerAnthemPlusCoordinator
) -> None:
    """Register the integration's services, once, if this entry has a valve.

    Idempotent: `async_setup_entry` runs per entry and on every reload, and re-registering
    would otherwise stack handlers. A HUB-only entry registers nothing, so the actions do
    not appear in the UI on an account that could never use them.
    """
    if coordinator.gcs_device is None:
        return
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_VALVE_HEX):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_VALVE_HEX,
            _async_send_valve_hex,
            schema=SEND_VALVE_HEX_SCHEMA,
            # Returns the decoded reading of both words, so a caller can confirm the word
            # meant what they thought without going to the log.
            supports_response=SupportsResponse.OPTIONAL,
        )
        # After registering, not before: the description attaches to a service that exists.
        # Whether the Zone 2 field is shown follows the topology detected at setup.
        _async_describe_service(hass, coordinator.model.uses_valve2)
    if not hass.services.has_service(DOMAIN, SERVICE_CUSTOM_SHOWER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CUSTOM_SHOWER,
            _async_custom_shower,
            schema=CUSTOM_SHOWER_SCHEMA,
            # Same response as `send_valve_hex`, so the form doubles as a way to learn the
            # command word for the escape hatch.
            supports_response=SupportsResponse.OPTIONAL,
        )
        _async_describe_custom_shower(
            hass, coordinator.model, coordinator.temperature_unit
        )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the services when the last entry unloads.

    Tolerates never having been registered — a HUB-only account gets here having skipped
    registration entirely.
    """
    for service in (SERVICE_SEND_VALVE_HEX, SERVICE_CUSTOM_SHOWER):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
