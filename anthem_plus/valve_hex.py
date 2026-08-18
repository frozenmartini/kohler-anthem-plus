"""Encode and decode the Anthem GCS 4-byte valve command word.

Single source of truth for the valve word. This replaces three implementations that
previously had to agree by hand: a Jinja encoder in ``scripts.yaml``, a decoder in the
standalone ``mqtt_capture.py``, and a subtly wrong ``ValveMode`` reading in the
``kohler-anthem`` library.

Layout, identical for reads and writes::

     0 1 | 2 3 | 4 5 | 6 7
      01 | 84  | C8  | 07
      ^     ^     ^     ^
      |     |     |     └─ outlet mask
      |     |     └─────── flow
      |     └───────────── temperature
      └─────────────────── prefix

Only the first 8 of the field's 16 hex characters carry the command; the trailing 8 were
``00000001`` in every captured message.

Every constant here is validated against 315 ``GCS_SOLO_STS`` messages correlated with the
HUB's ``SHOWER_VALVE_STS``. See ``docs/gcs/valve_hex.md`` for the evidence, and its
"Superseded readings" section for two decompile-derived formulas that this contradicts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import ValveModel

# Sent for a valve the model does not populate. The firmware ignores it: prefix 0x00
# addresses no valve. It must still be present in the payload.
UNUSED_VALVE_WORD = "00000000"

# Byte 0 layout (resolved from the app decompile, `p315jj/h.java`, and verified against 363
# captured messages). READ and WRITE differ:
#
#     status:  [valve index : 4][atFlow : 1][atTemp : 1][temperature high : 2]
#     write:   [valve index : 4][   0       0        ][temperature high : 2]
#
# `atFlow` (0x08) and `atTemp` (0x04) are read-only status the device asserts; the client
# always writes them as zero, which is why they never appear in a command word. They land in
# `ValveStatusModel.atFlow` / `.atTemp` in the app.
#
# `atTemp` is what made 0x05 look mysterious: it means "this valve has reached its
# temperature setpoint", which is sticky, uncorrelated with outlets, and appears about half
# the time. It was never set during warmup in the captures — correct, since the valve is
# still climbing to temperature then.
#
# `atFlow` was never observed set on the test system — but that system has flow control
# DISABLED at the fixture (a workaround for it being broken on HUB firmware 2.88), so the
# flat zero probably reflects the setting rather than the firmware. The measured-flow byte
# is also zero there, which fits. Unconfirmed: needs a system with flow control enabled.
VALVE_INDEX_SHIFT = 4
VALVE1_INDEX = 0
VALVE2_INDEX = 1
AT_FLOW_BIT = 0x08
AT_TEMP_BIT = 0x04
# Kept as the values actually written for a temperature at or above 25.6 °C.
VALVE1_PREFIX = 0x01
VALVE2_PREFIX = 0x11

# Temperature is a 16-BIT value spanning bytes 0 and 1: tenths of a degree Celsius, with
# the high byte in bit 0 of byte 0 and the low byte in byte 1.
#
#     °C = ((byte0 & 0x01) << 8 | byte1) / 10
#
# This supersedes the earlier reading of "25.6 + byte1/10", which was the same arithmetic
# in disguise — 256/10 is 25.6, so that formula silently assumed the high bit was always
# set. It agrees on all 357 captured words where the bit IS set, and is wrong where it is
# not: the words 0000C800 and 1000C800 are 0.0 °C, which the old formula reported as
# 25.6 °C.
#
# It also explains the mysterious "base": there is no base. 25.6 °C is simply the smallest
# temperature whose high byte is 1.
TEMPERATURE_TENTHS_PER_DEGREE = 10
# TWO bits of byte 0, not one: temperature is 10-bit, so up to 102.3 C is representable.
# Bit 0x02 was never set across 363 captures (no temperature reached 51.2 C), which is why a
# one-bit reading agreed with every sample while still being the narrower model.
TEMPERATURE_HIGH_BITS = 0x03
TEMPERATURE_HIGH_BIT = 0x01  # legacy alias
# The Konnect app never sends above 48.8 °C (488 tenths), so writes clamp there rather than
# at the 51.1 °C the encoding could carry.
TEMPERATURE_MAX_TENTHS = 488
# Retained for callers that still reason in the old terms; both are derived, not magic.
TEMPERATURE_BASE_C = 25.6
TEMPERATURE_STEP_C = 0.1

# ---------------------------------------------------------------------------
# ⚠️ Fahrenheit is a LOOKUP TABLE, not arithmetic — Konnect 3.0.1, `p315jj/h.java:1971`
# ---------------------------------------------------------------------------
# `h.z()` maps a displayed whole °F to tenths of a °C directly, and it is **not**
# `round((f - 32) * 50 / 9)`. Above 86 °F it sits exactly one tenth *below* that formula at
# sixteen entries — 87, 89, 91, 93, 96, 98, 100, 102, 105, 107, 109, 111, 114, 116, 118, 120 —
# precisely the set where naive rounding would round up.
#
# **That low bias is the mechanism, not a rounding artefact.** It is what makes the app's
# round trip idempotent: with `h.j(c) = round(c * 1.8 + 32)` for display, `z(j(t)) == t` holds
# for all 64 entries. Naive arithmetic breaks it on 12 of the 34 values this integration's
# slider can produce, every one by +1 tenth:
#
#     102 °F -> ours 0x185 (389), Kohler 0x184 (388)
#     100 °F -> ours 0x17A (378), Kohler 0x179 (377)
#      98 °F -> ours 0x16F (367), Kohler 0x16E (366)
#
# Measured consequence, 2026-08-17: the owner reported the temperature coming back "one more"
# after the shower restarted itself, and 0x185 (389) appears 11 times in this system's capture
# corpus — a value **no Kohler client can emit**. `z()` cannot produce it, and the Celsius path
# writes whole degrees (380/390/400). Those messages were this integration's own writes.
#
# The valve accepts off-ladder values perfectly well — nothing here is a protocol requirement.
# What it costs is that a setpoint written from Home Assistant no longer sits where the
# touchscreen would put it, so the next panel adjustment starts from a value one tenth off.
#
# Outside 59–122 °F the app returns 0, which for a device that opens water valves would mean
# "full cold". `unit_to_celsius` falls back to the arithmetic rather than doing that.
FAHRENHEIT_TO_TENTHS_C = {
    59: 150, 60: 156, 61: 161, 62: 167, 63: 172, 64: 178, 65: 183, 66: 189,
    67: 194, 68: 200, 69: 206, 70: 211, 71: 217, 72: 222, 73: 228, 74: 233,
    75: 239, 76: 244, 77: 250, 78: 256, 79: 261, 80: 267, 81: 272, 82: 278,
    83: 283, 84: 289, 85: 294, 86: 300, 87: 305, 88: 311, 89: 316, 90: 322,
    91: 327, 92: 333, 93: 338, 94: 344, 95: 350, 96: 355, 97: 361, 98: 366,
    99: 372, 100: 377, 101: 383, 102: 388, 103: 394, 104: 400, 105: 405,
    106: 411, 107: 416, 108: 422, 109: 427, 110: 433, 111: 438, 112: 444,
    113: 450, 114: 455, 115: 461, 116: 466, 117: 472, 118: 477, 119: 483,
    120: 488, 121: 494, 122: 500,
}
# The byte accepts up to 0xFF, but the Konnect app never sends above 0xE8 (48.8 °C /
# 119.8 °F). Whether the firmware enforces that cap or only the app does is untested, so
# writes clamp to the app's limit rather than the byte's.
TEMPERATURE_BYTE_MAX = 0xE8

# Byte 2 — flow. The SAME byte is expressed on three different scales depending on where
# you read it, which is a standing source of 2x and 4x errors:
#
#   byte            0x00-0xC8   the wire format, here and in MQTT
#   flowSetpoint    0-50        the GCS device's own native unit (gcs-state), byte / 4
#   percent         0-100       HUB favourite `flowrate` and HA entities, byte / 2
#
# Verified live: with the shower idle, gcs-state reports flowSetpoint "50" on both valves,
# and 50 * 4 = 0xC8 = the maximum flow byte. The outlet configuration's documented
# "flow 16-200" range is in BYTE units (0x10-0xC8), not either of the other two.
#
# The HUB has no independent flow of its own — its favourite `flowrate` is just read and
# written through to the GCS valve, so the valve is always the real source.
FLOW_PER_PERCENT = 2
FLOW_PER_SETPOINT = 4

# The flow byte is the valve's own flow rate, and its scale **does not start at zero**.
# Every outlet reports `minimumFlowRate: 16` / `maximumFlowRate: 200` in
# `READ_GCS_OUTLET_CONFIG_CFG`, and across every capture the byte has never once fallen
# outside 16-200 (31 distinct values). So the usable percent range is 8-100, not 0-100.
#
# **The valve honours a directly written flow byte.** Verified against hardware: 74 and 100
# commanded with one, two, and three outlets open in a zone, every echo matching exactly, and
# the other zone untouched.
#
# That needs saying because touchscreen-driven captures look nothing like this — the byte
# moves on its own when outlets change, and the same outlet set tops out at 200 in one
# session and 69 in another. That is the **touchscreen** computing linked-zone scaling and
# its own ceiling before it sends; the valve just obeys whoever wrote last. The Konnect app
# is a third actor and has removed flow control entirely. Writing directly, none of the
# touchscreen's behaviour applies to us.
#
# Consequence for a client: encode against [16, 200] and expect it to stick — but keep
# treating the echo as truth, since the touchscreen can overwrite at any time.
#
# The byte is continuous over that range, which is why it is frequently **not** a multiple
# of 4: values like 17, 19, and 165 are ordinary. `flowSetpoint` (byte/4, the 0-50 figure
# `gcs-state` reports) is a derived display value, not the underlying quantity, so treating
# it as an integer scale invents a precision the device does not use.
FLOW_BYTE_MIN = 0x10
FLOW_SETPOINT_MAX = 50
FLOW_BYTE_MAX = 0xC8

# Byte 3 = [0x80][pause 0x40][0 0 0][outlet3 0x04][outlet2 0x02][outlet1 0x01]
#
# Bit 0x80 differs by direction, like byte 0: on READ it is `errorFlag`, paired with the
# error code in byte 7; on WRITE it is `skipWarmUp` (start without triggering warmup).
# Corroborated by gcs-state, which reports errorFlag "0" / errorCode "1" while captures show
# byte3 & 0x80 clear and byte7 = 0x01. Never observed set, so the write meaning is untested.
#
# The outlet mask is ONLY the low three bits. 0x40 is an INDEPENDENT pause bit that
# round-trips the device's pauseFlag (write: `Pi/r.java` getPauseFlag(); read: decodes into
# ValveStatusModel.pauseFlag) — it is not a mask value, and it coexists with outlet bits:
#
#     00  idle, nothing assigned          01/02/04  running to outlet 1/2/3
#     40  paused, nothing assigned        41/42/44  paused, outlet 1/2/3 still assigned
#
# So a paused valve retains which outlet it will resume to. Treating 0x40 as a whole-mask
# sentinel makes 0x41 unrepresentable and misreads a paused-with-assignment valve as running.
# The library's "0x40 = preset-mode" and "0x01 = SHOWER mode" were both misreads of this byte.
OUTLET_MASK_BITS = 0x07
VALVE_PAUSE_FLAG = 0x40
VALVE_SKIP_WARMUP_FLAG = 0x80   # write meaning of bit 0x80
VALVE_ERROR_FLAG = 0x80         # read meaning of the same bit
VALVE_STOP_MASK = 0x00
OUTLETS_PER_VALVE = 3
OUTLET_COUNT = OUTLETS_PER_VALVE * 2

VALVE_WORD = re.compile(r"^[0-9A-Fa-f]{8}$")

# A preset's hexString is 3 bytes — [byte0][temp low][flow] — and byte0 carries BOTH the
# temperature high bit and the outlet flags, at DIFFERENT bit positions from a command word:
#
#     preset  byte0:  0x04 outlet1   0x08 outlet2   0x10 outlet3   0x01 temp high bit
#     command byte3:  0x01 outlet1   0x02 outlet2   0x04 outlet3
#
# There is no valve-index nibble in a preset: the valve is identified by field position.
# Confirmed on all four valve entries of two live presets:
#
#     018448  byte0 0x01 -> no outlets, 38.8 C      (Default shower Valve1)
#     05849C  byte0 0x05 -> outlet1,    38.8 C      (Default shower Valve2)
#     1190C8  byte0 0x11 -> outlet3,    40.0 C      (Test favourite Valve1)
#     0589C8  byte0 0x05 -> outlet1,    39.3 C      (Test favourite Valve2)
#
# An earlier revision concluded presets carried no outlet mask at all. That was wrong: it
# tested the command word's bit positions (0x01/0x02/0x04) against preset bytes.
PRESET_OUTLET_BITS = (0x04, 0x08, 0x10)
PRESET_WORD = re.compile(r"^[0-9A-Fa-f]{6}$")
PRESET_HEX_UNUSED = frozenset({"", "000000"})


def decode_preset_word(value: str) -> ValveWord:
    """Decode a 3-byte preset hexString into the same shape as a command word."""
    word = str(value or "").strip().upper()
    if not PRESET_WORD.fullmatch(word):
        raise ValveHexError(f"Not a 6-character preset valve word: {value!r}")
    byte0 = int(word[0:2], 16)
    tenths = ((byte0 & TEMPERATURE_HIGH_BITS) << 8) | int(word[2:4], 16)
    mask = 0
    for index, bit in enumerate(PRESET_OUTLET_BITS):
        if byte0 & bit:
            mask |= 1 << index
    return ValveWord(
        prefix=byte0,
        temperature_celsius=round(tenths / TEMPERATURE_TENTHS_PER_DEGREE, 1),
        flow_percent=round(int(word[4:6], 16) / FLOW_PER_PERCENT, 1),
        outlet_mask=mask,
        paused=False,
    )


def encode_preset_word(
    temperature_celsius: float, flow_percent: float, outlet_mask: int
) -> str:
    """Build a 3-byte preset hexString for one valve.

    Used by ``writepreset`` and ``createpreset``, which take this format — NOT the 4-byte
    command word. Sending a command word where a preset word is expected is accepted by the
    backend and then silently ignored.
    """
    if outlet_mask & ~OUTLET_MASK_BITS:
        raise ValveHexError(f"Outlet mask 0x{outlet_mask:02X} sets unknown bits")
    tenths = min(
        max(round(temperature_celsius * TEMPERATURE_TENTHS_PER_DEGREE), 0),
        TEMPERATURE_MAX_TENTHS,
    )
    byte0 = (tenths >> 8) & TEMPERATURE_HIGH_BITS
    for index, bit in enumerate(PRESET_OUTLET_BITS):
        if outlet_mask >> index & 1:
            byte0 |= bit
    # Clamp to the device's own range, not 0x00. Confirmed against the Konnect
    # decompile: the app's encoder is `hex(round(setpoint_0_50 * 4))` with no clamp of
    # its own — all clamping happens upstream at the slider, bounded by the per-outlet
    # `minimumFlowRate`/`maximumFlowRate`. Our `* 2` on percent is arithmetically the
    # same value, since percent = 2 x setpoint.
    flow_byte = min(
        max(round(flow_percent * FLOW_PER_PERCENT), FLOW_BYTE_MIN), FLOW_BYTE_MAX
    )
    return f"{byte0:02X}{tenths & 0xFF:02X}{flow_byte:02X}"


class ValveHexError(ValueError):
    """Raised when a valve word is malformed or a value is out of range."""


@dataclass(frozen=True)
class ValveWord:
    """A decoded valve command word."""

    prefix: int
    temperature_celsius: float
    flow_percent: float
    outlet_mask: int
    paused: bool
    # Read-only status the device reports; always zero in a word we send.
    at_temperature: bool = False
    at_flow: bool = False
    error_flag: bool = False
    # Live sensor feedback from the second half of a 16-character status word. None when
    # only the 8-character command half was available.
    measured_temperature_celsius: float | None = None
    measured_flow_percent: float | None = None
    error_code: int | None = None
    # The word exactly as it arrived, so anything wanting to *show* the wire value never
    # re-encodes it from the decoded fields — a reconstruction silently goes stale whenever
    # the codec is corrected, and it cannot represent bits this dataclass does not model.
    # Empty for a word built from a REST read, which carries no wire word.
    #
    # Excluded from equality: two words that decode identically are the same state, and
    # letting a reserved-bit difference count as a change would wake every entity.
    raw: str = field(default="", compare=False)

    @property
    def measured_flow_setpoint(self) -> float | None:
        """Measured flow on the device's own 0-50 scale."""
        if self.measured_flow_percent is None:
            return None
        return round(
            self.measured_flow_percent * FLOW_PER_PERCENT / FLOW_PER_SETPOINT, 1
        )

    @property
    def stopped(self) -> bool:
        """True when no outlet is open and the valve is not merely paused."""
        return self.outlet_mask == VALVE_STOP_MASK and not self.paused

    @property
    def flow_setpoint(self) -> float:
        """Flow on the GCS device's own 0-50 scale, as ``gcs-state`` reports it."""
        return round(self.flow_percent * FLOW_PER_PERCENT / FLOW_PER_SETPOINT, 1)

    def outlet(self, index: int) -> bool:
        """Whether this valve's outlet ``index`` (0-2) is open."""
        return bool(self.outlet_mask >> index & 1)


def normalize_word(value: str | None) -> str:
    """Return the uppercased 8-character command half of a valve field."""
    word = str(value or "")[:8].upper()
    if not VALVE_WORD.fullmatch(word):
        raise ValveHexError(f"Not an 8-character valve command word: {value!r}")
    return word


def decode_word(value: str) -> ValveWord:
    """Decode a valve word.

    Accepts both forms. The 8-character word is what ``solowritesystem`` sends: setpoints,
    flags, and the outlet mask. The 16-character word the device *reports* appends four
    more bytes of **live sensor feedback** — so the full status word is symmetric,
    "what was commanded" followed by "what the valve is actually doing":

    ===== ============================================================
    byte  meaning
    ===== ============================================================
    4-5   measured temperature, ``((byte4 & 3) << 8 | byte5) / 10`` °C
    6     measured flow, same scale as the byte-2 setpoint
    7     error code, pairing with ``errorFlag`` in byte 3
    ===== ============================================================

    On the hardware tested these read `00000001` — zero measurement, error code 1 — even
    across 239 messages with an outlet open, so this valve does not appear to report
    measurements over MQTT. The mapping is corroborated by ``gcs-state``, which reports the
    matching ``errorFlag: "0"`` / ``errorCode: "1"``.

    Byte 4's upper six bits are unused, and the app writes the same measurement to all three
    per-outlet sub-objects: it is one per-valve reading, stored redundantly.
    """
    full = str(value or "").strip().upper()
    word = normalize_word(full)
    mask_byte = int(word[6:8], 16)
    byte0 = int(word[0:2], 16)
    tenths = ((byte0 & TEMPERATURE_HIGH_BITS) << 8) | int(word[2:4], 16)
    return ValveWord(
        prefix=byte0,
        temperature_celsius=round(tenths / TEMPERATURE_TENTHS_PER_DEGREE, 1),
        flow_percent=round(int(word[4:6], 16) / FLOW_PER_PERCENT, 1),
        outlet_mask=mask_byte & OUTLET_MASK_BITS,
        paused=bool(mask_byte & VALVE_PAUSE_FLAG),
        at_temperature=bool(byte0 & AT_TEMP_BIT),
        at_flow=bool(byte0 & AT_FLOW_BIT),
        error_flag=bool(mask_byte & VALVE_ERROR_FLAG),
        raw=full,
        **_decode_measurements(full),
    )


def _decode_measurements(full: str) -> dict[str, object]:
    """Pull the live-feedback half out of a 16-character status word."""
    if len(full) < 16 or not VALVE_WORD.fullmatch(full[8:16]):
        return {}
    byte4, byte5, byte6, byte7 = (int(full[i : i + 2], 16) for i in range(8, 16, 2))
    return {
        "measured_temperature_celsius": round(
            (((byte4 & TEMPERATURE_HIGH_BITS) << 8) | byte5)
            / TEMPERATURE_TENTHS_PER_DEGREE,
            1,
        ),
        "measured_flow_percent": round(byte6 / FLOW_PER_PERCENT, 1),
        "error_code": byte7,
    }


def encode_word(
    prefix: int,
    temperature_celsius: float,
    flow_percent: float,
    outlet_mask: int,
    *,
    paused: bool = False,
    skip_warmup: bool = False,
) -> str:
    """Build one valve command word.

    Temperature and flow are clamped to what the device accepts rather than rejected,
    matching the Jinja encoder this replaces. The outlet mask is not clamped: a caller
    passing something outside 0x00-0x07 or the 0x40 PAUSE sentinel has a bug worth
    surfacing rather than silently reinterpreting as a different set of open outlets.
    """
    if outlet_mask & ~OUTLET_MASK_BITS:
        raise ValveHexError(
            f"Outlet mask 0x{outlet_mask:02X} sets bits outside the low three. "
            "Pause is a separate flag — pass paused=True rather than folding 0x40 in."
        )
    tenths = min(
        max(round(temperature_celsius * TEMPERATURE_TENTHS_PER_DEGREE), 0),
        TEMPERATURE_MAX_TENTHS,
    )
    # The temperature's high bit lives in byte 0 alongside the valve index. Callers pass
    # the already-composed byte (0x01 / 0x11), so keep its nibble and set the bit from the
    # temperature rather than trusting what was handed in.
    # Only the valve index and the temperature high bits are ours to set; atFlow/atTemp
    # stay zero because they are status the device reports, not something we command.
    byte0 = (prefix & 0xF0) | ((tenths >> 8) & TEMPERATURE_HIGH_BITS)
    # Clamp to 0xC8, not 0xFF: 0xC8 is 100% / flowSetpoint 50, the device's maximum.
    # Clamp to the device's own range, not 0x00. Confirmed against the Konnect
    # decompile: the app's encoder is `hex(round(setpoint_0_50 * 4))` with no clamp of
    # its own — all clamping happens upstream at the slider, bounded by the per-outlet
    # `minimumFlowRate`/`maximumFlowRate`. Our `* 2` on percent is arithmetically the
    # same value, since percent = 2 x setpoint.
    flow_byte = min(
        max(round(flow_percent * FLOW_PER_PERCENT), FLOW_BYTE_MIN), FLOW_BYTE_MAX
    )
    byte3 = outlet_mask
    if paused:
        byte3 |= VALVE_PAUSE_FLAG
    if skip_warmup:
        byte3 |= VALVE_SKIP_WARMUP_FLAG
    return f"{byte0:02X}{tenths & 0xFF:02X}{flow_byte:02X}{byte3:02X}"


def outlet_mask(*outlets: bool) -> int:
    """Combine up to three outlet flags into a mask (bit 0 is the first)."""
    if len(outlets) > OUTLETS_PER_VALVE:
        raise ValveHexError(
            f"A valve has {OUTLETS_PER_VALVE} outlets, not {len(outlets)}"
        )
    return sum(1 << index for index, is_on in enumerate(outlets) if is_on)


def encode_pair(
    model: ValveModel,
    temperature_celsius: float,
    flow_percent: float,
    outlets: list[bool],
) -> tuple[str, str]:
    """Build both valve words from this model's outlet flags.

    ``outlets`` has one flag per physical outlet, so its length depends on the model. The
    split between valve1 and valve2 is the model's, NOT a fixed 3+3 — on a 4-outlet
    K-28211 it is 2+2, so outlet 3 is valve2's first outlet.

    When the model has no second valve, ``secondaryValve1`` is the all-zero ignore word.
    """
    valve1_flags, valve2_flags = model.split_outlets(outlets)
    valve1 = encode_word(
        VALVE1_PREFIX, temperature_celsius, flow_percent, outlet_mask(*valve1_flags)
    )
    if not model.uses_valve2:
        return valve1, UNUSED_VALVE_WORD
    return valve1, encode_word(
        VALVE2_PREFIX, temperature_celsius, flow_percent, outlet_mask(*valve2_flags)
    )


def _mask_pair(
    model: ValveModel,
    mask: int,
    temperature_celsius: float,
    flow_percent: float,
    *,
    paused: bool = False,
) -> tuple[str, str]:
    """Build both words carrying the same mask, respecting the model's valve count."""
    valve1 = encode_word(
        VALVE1_PREFIX, temperature_celsius, flow_percent, mask, paused=paused
    )
    if not model.uses_valve2:
        return valve1, UNUSED_VALVE_WORD
    return valve1, encode_word(
        VALVE2_PREFIX, temperature_celsius, flow_percent, mask, paused=paused
    )


def stop_pair(
    model: ValveModel,
    temperature_celsius: float = 38.0,
    flow_percent: float = 100,
) -> tuple[str, str]:
    """Build the pair of words that stops every outlet.

    Mask ``0x00`` is STOP. The temperature and flow bytes are ignored by the firmware for a
    stop but still have to be well-formed — which is why the library's ``turn_off()``,
    sending an all-zero ``primaryValve1``, is ignored: prefix ``0x00`` addresses no valve.
    """
    return _mask_pair(model, VALVE_STOP_MASK, temperature_celsius, flow_percent)


def pause_pair(
    model: ValveModel,
    temperature_celsius: float = 38.0,
    flow_percent: float = 100,
    outlet_mask: int = 0x00,
) -> tuple[str, str]:
    """Build the pair of words that pauses the valves, holding the session open.

    ``outlet_mask`` carries forward which outlets the session will resume to — a paused
    valve keeps its assignment, so passing the running mask preserves it.
    """
    return _mask_pair(
        model, outlet_mask, temperature_celsius, flow_percent, paused=True
    )


def preset_valve_to_command(valve_detail: dict, prefix: int) -> str:
    """Build a command word from one entry of a preset's ``valveDetails``.

    A preset stores its outlets in the ``outlets`` array, **not** in ``hexString``. The
    three bytes of ``hexString`` are ``[prefix][temperature][flow]`` — the leading byte is
    the same unexplained prefix seen in ``GCS_SOLO_STS`` (values 01, 05, 11), not an outlet
    mask. Verified against two live presets where all four valve entries disagreed with a
    mask reading::

        Default shower  Valve1 hex 018448  byte0=01  outlets [0,0,0]  (mask would be 00)
        Default shower  Valve2 hex 05849c  byte0=05  outlets [1,0,0]  (mask would be 01)
        Test favourite  Valve1 hex 1190c8  byte0=11  outlets [0,0,1]  (mask would be 04)
        Test favourite  Valve2 hex 0589c8  byte0=05  outlets [1,0,0]  (mask would be 01)

    Temperature and flow are taken from the outlets array too, where they are plain values
    rather than packed bytes: ``temperature`` in Celsius and ``flow`` on the valve's native
    0-50 scale. Returns ``None`` when the preset opens nothing on this valve.
    """
    outlets = valve_detail.get("outlets") or []
    mask = 0
    temperature_c: float | None = None
    flow_native: float | None = None
    for index, outlet in enumerate(outlets[:OUTLETS_PER_VALVE]):
        if not isinstance(outlet, dict):
            continue
        if str(outlet.get("value", "0")).strip() in {"1", "true", "True"}:
            mask |= 1 << index
        if temperature_c is None:
            try:
                temperature_c = float(outlet.get("temperature"))
            except (TypeError, ValueError):
                pass
        if flow_native is None:
            try:
                flow_native = float(outlet.get("flow"))
            except (TypeError, ValueError):
                pass

    # A mask of 0x00 is still a valid, addressed word meaning "this valve stays closed".
    # It must NOT be replaced with the all-zero sentinel: prefix 0x00 addresses no valve,
    # and on a two-valve system that appears to make the device discard the whole command
    # rather than just that valve. Observed live — a preset command sent as
    # v1=00000000 v2=11849C01 opened nothing at all, while v1=0185C800 v2=1185C801 (an
    # addressed, closed valve 1) opened valve 2 immediately.

    # Fall back to the packed bytes if the outlets array omitted the values.
    stored = str(valve_detail.get("hexString") or "").strip().upper()
    if PRESET_WORD.fullmatch(stored):
        if temperature_c is None:
            temperature_c = TEMPERATURE_BASE_C + int(stored[2:4], 16) * TEMPERATURE_STEP_C
        if flow_native is None:
            flow_native = int(stored[4:6], 16) / FLOW_PER_SETPOINT

    percent = (
        (flow_native * FLOW_PER_SETPOINT) / FLOW_PER_PERCENT
        if flow_native is not None
        else 100.0
    )
    return encode_word(prefix, temperature_c or 38.0, percent, mask)


def preset_opens_anything(valve_details: "list[dict]") -> bool:
    """True if the preset opens at least one outlet on any valve.

    Kohler "experiences" carry no outlet data and cannot be started this way, so this is
    how they are told apart from real presets.
    """
    for detail in valve_details or []:
        if not isinstance(detail, dict):
            continue
        for outlet in detail.get("outlets") or []:
            if isinstance(outlet, dict) and str(
                outlet.get("value", "0")
            ).strip() in {"1", "true", "True"}:
                return True
    return False


def preset_to_pair(
    model: ValveModel, valve_details: "list[dict]"
) -> tuple[str, str]:
    """Build both command words for a preset.

    **Every valve the model has gets a real, addressed word**, even one whose outlets are
    all closed — that word simply carries mask ``0x00``. Substituting the all-zero sentinel
    for an unused valve makes the device ignore the entire command on a two-valve system.

    A model with no second valve still needs the field present, and there the all-zero word
    is correct: there is genuinely no valve to address.
    """
    by_index = {
        str(detail.get("valveIndex") or ""): detail
        for detail in valve_details or []
        if isinstance(detail, dict)
    }
    valve1 = preset_valve_to_command(by_index.get("Valve1", {}), VALVE1_PREFIX)
    if not model.uses_valve2:
        return valve1, UNUSED_VALVE_WORD
    return valve1, preset_valve_to_command(by_index.get("Valve2", {}), VALVE2_PREFIX)


def preset_word_to_command(preset_hex: str | None, prefix: int) -> str | None:
    """DEPRECATED — reads byte 0 as an outlet mask, which it is not.

    Kept only so the mistake is documented rather than silently rediscovered. Live data
    disproves the premise: see :func:`preset_valve_to_command`, which reads outlets from the
    preset's ``outlets`` array instead. Use that.
    """
    stored = (preset_hex or "").strip().upper()
    if stored in PRESET_HEX_UNUSED:
        return None
    if not PRESET_WORD.fullmatch(stored):
        raise ValveHexError(f"Not a 6-character preset valve hexString: {preset_hex!r}")
    return f"{prefix:02X}{stored[2:6]}{stored[0:2]}"


def celsius_to_unit(value_c: float, temperature_unit: str) -> float:
    """Convert a decoded Celsius value into the account's display unit.

    Kohler's REST API and this valve byte both report Celsius regardless of the account's
    display preference; the mobile app converts locally. Convert at the edge only.
    """
    if temperature_unit.lower().startswith("f"):
        return round(value_c * 9 / 5 + 32, 1)
    return round(value_c, 1)


def unit_to_celsius(value: float, temperature_unit: str) -> float:
    """Convert an account-unit temperature into Celsius for encoding.

    Fahrenheit goes through `FAHRENHEIT_TO_TENTHS_C`, Kohler's own table, so a value written
    from Home Assistant lands exactly where the touchscreen would put it. See that table for
    why arithmetic is wrong here — it drifts +1 tenth on 12 of the 34 values the slider offers.

    The table holds whole degrees only. A fractional °F — reachable through the service, not
    the slider — falls back to the arithmetic, as does anything outside 59-122 °F. Kohler
    returns 0 there; that would be full cold, so it is not copied.
    """
    if not temperature_unit.lower().startswith("f"):
        return value
    whole = round(value)
    if abs(value - whole) < 0.01 and whole in FAHRENHEIT_TO_TENTHS_C:
        return FAHRENHEIT_TO_TENTHS_C[whole] / TEMPERATURE_TENTHS_PER_DEGREE
    return (value - 32) * 5 / 9


def decode_valve_state(
    model: ValveModel,
    valve1_code: str,
    valve2_code: str,
    temperature_unit: str,
) -> dict[str, object]:
    """Decode both valve words into flat published state fields.

    Only outlets the model actually has are reported, and each is resolved through
    ``model.outlet_location`` rather than assuming a 3+3 split — on a 4-outlet K-28211,
    outlet 3 lives on valve2.
    """
    words: dict[int, ValveWord] = {1: decode_word(valve1_code)}
    if model.uses_valve2:
        words[2] = decode_word(valve2_code)

    decoded: dict[str, object] = {}
    for number, word in words.items():
        decoded[f"valve{number}_temperature"] = celsius_to_unit(
            word.temperature_celsius, temperature_unit
        )
        decoded[f"valve{number}_flow"] = word.flow_percent
        decoded[f"valve{number}_flow_setpoint"] = word.flow_setpoint
        decoded[f"valve{number}_outlet_mask"] = word.outlet_mask
        decoded[f"valve{number}_paused"] = word.paused

    for outlet in range(1, model.total_outlets + 1):
        valve_number, bit = model.outlet_location(outlet)
        word = words.get(valve_number)
        decoded[f"outlet{outlet}"] = (
            "ON" if word is not None and word.outlet(bit) else "OFF"
        )
    return decoded
