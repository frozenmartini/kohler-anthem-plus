"""Kohler Anthem Plus protocol library.

Pure Python with no Home Assistant imports, so it can be tested off-box and lifted into its
own package later without changes. Everything that knows about Kohler's wire formats lives
here; everything that knows about Home Assistant lives in the parent integration.

Covers both products:

* **Anthem** (SKU ``GCS``) — the digital valve body with built-in Wi-Fi, addressed
  directly. Every start specifies the full valve state as a hex command word.
* **Anthem Plus** (SKU ``HUB``) — the Linux system controller that drives the valves and
  integrates music, lighting, and steam. Control is organised around favourites.

Written against the protocol documentation in ``docs/``, which is capture-derived. The
``kohler-anthem`` library reads three of these behaviours differently; it was decompiled from
the same APK but not checked against captures, so where the two disagree see
``docs/gcs/valve_hex.md``.
"""

from __future__ import annotations

from .auth import (
    AuthError,
    AuthUnavailable,
    InvalidCredentials,
    KohlerAuth,
    SignInBlocked,
    TokenSet,
    decode_tenant_id,
)
from .client import (
    Customer,
    Device,
    DeviceOffline,
    DeviceRunning,
    KohlerClient,
    KohlerError,
)
from .const import (
    MSG_GCS_SOLO_STATUS,
    MSG_GCS_WARMUP_STATUS,
    WARMUP_DISABLED,
    WARMUP_MODES,
    WARMUP_MODES_CURRENT,
    WARMUP_MODES_LEGACY,
)
from .gcs import GcsDevice
from .hub import HubCapabilities, HubDevice, zone_number, zone_outlet_flags
from .mqtt import AnthemMqttStream, Envelope
from .cutoff_log import CutoffDebugLog, WARMUP_README
from .raw_log import RawMqttLog
from .runtime_cutoff import ZoneCutoff, ZoneCutoffDetector, ZoneReading
from .state import GcsPreset, GcsState, HubState, HubZone
from .warmup import journal_event, restore_target, should_restore_warmup
from .topology import (
    describe as describe_topology,
    topology_from_hub_configuration,
    topology_from_valve_settings,
)
from .models import (
    DEFAULT_VALVE_MODEL,
    VALVE_MODELS,
    OutletStateSource,
    ValveModel,
    get_valve_model,
    model_for_topology,
    resolve_outlet_source,
)
from .valve_hex import (
    OUTLET_COUNT,
    OUTLETS_PER_VALVE,
    ValveHexError,
    ValveWord,
    celsius_to_unit,
    decode_valve_state,
    decode_word,
    encode_pair,
    encode_word,
    outlet_mask,
    pause_pair,
    preset_opens_anything,
    preset_to_pair,
    preset_valve_to_command,
    preset_word_to_command,
    stop_pair,
    unit_to_celsius,
)

__all__ = [
    "AuthError",
    "MSG_GCS_SOLO_STATUS",
    "MSG_GCS_WARMUP_STATUS",
    "WARMUP_DISABLED",
    "WARMUP_MODES",
    "WARMUP_MODES_CURRENT",
    "WARMUP_MODES_LEGACY",
    "journal_event",
    "restore_target",
    "should_restore_warmup",
    "AuthUnavailable",
    "Customer",
    "Device",
    "DeviceOffline",
    "DeviceRunning",
    "AnthemMqttStream",
    "DEFAULT_VALVE_MODEL",
    "Envelope",
    "GcsPreset",
    "GcsState",
    "HubState",
    "HubZone",
    "GcsDevice",
    "HubCapabilities",
    "HubDevice",
    "zone_number",
    "zone_outlet_flags",
    "OutletStateSource",
    "VALVE_MODELS",
    "ValveModel",
    "describe_topology",
    "get_valve_model",
    "model_for_topology",
    "topology_from_hub_configuration",
    "topology_from_valve_settings",
    "resolve_outlet_source",
    "InvalidCredentials",
    "KohlerAuth",
    "KohlerClient",
    "KohlerError",
    "CutoffDebugLog",
    "WARMUP_README",
    "RawMqttLog",
    "ZoneCutoff",
    "ZoneCutoffDetector",
    "ZoneReading",
    "SignInBlocked",
    "TokenSet",
    "decode_tenant_id",
    "OUTLETS_PER_VALVE",
    "OUTLET_COUNT",
    "ValveHexError",
    "ValveWord",
    "celsius_to_unit",
    "decode_valve_state",
    "decode_word",
    "encode_pair",
    "encode_word",
    "outlet_mask",
    "pause_pair",
    "preset_opens_anything",
    "preset_to_pair",
    "preset_valve_to_command",
    "preset_word_to_command",
    "stop_pair",
    "unit_to_celsius",
]
