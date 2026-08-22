"""Commands for the Anthem digital valve (SKU ``GCS``).

The GCS valve is addressed directly and has **no "run my default"** — every start must
specify the complete valve state as a hex command word. There is no bare on/off command,
which is the fundamental difference from the Anthem Plus HUB.

All direct writes go through ``solowritesystem``. Presets are a stored layer on top:
``controlpresetorexperience`` with ``{preset, action}`` starts one by itself — the valve
runs the stored scene, no valve write follows. (An earlier reading held that it only
*selected* a preset and a start needed two commands; live testing disproved that, and the
two-command path was removed 2026-08-21.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import KohlerClient
from .const import (
    GCS_CONTROL_PRESET,
    GCS_CREATE_PRESET,
    GCS_SOLOWRITESYSTEM,
    GCS_WARMUP,
    GCS_WRITE_PRESET,
    SKU_GCS,
)
from .models import DEFAULT_VALVE_MODEL, ValveModel, get_valve_model
from .valve_hex import (
    UNUSED_VALVE_WORD,
    VALVE1_PREFIX,
    VALVE2_PREFIX,
    ValveHexError,
    encode_pair,
    encode_word,
    pause_pair,
    stop_pair,
    unit_to_celsius,
)

# The payload carries eight valve slots. Only the first two are ever populated; the rest
# must still be present and zeroed.
SECONDARY_SLOTS = tuple(f"secondaryValve{n}" for n in range(2, 8))


@dataclass(frozen=True)
class PresetTimerPlan:
    """What, if anything, to do about one preset's stored ``time``.

    ``reason`` is one of:

    ``absent``
        No such preset slot in the read. Nothing to do.
    ``empty``
        The slot exists but holds no name and no valve words — an unconfigured slot.
        **Deliberately left alone**: writing a timer into a blank slot would half-create a
        preset the owner never asked for.
    ``already``
        The stored timer already matches the target. Nothing to write.
    ``rewrite``
        The timer differs and should be written.
    """

    reason: str
    name: str = ""
    volume: str = "0"
    valves: dict[int, str] = field(default_factory=dict)
    previous: int | None = None

    @property
    def needed(self) -> bool:
        """Whether a ``writepreset`` should actually be sent."""
        return self.reason == "rewrite"


def _preset_record(payload: Any, preset_id: int) -> dict[str, Any] | None:
    """Find one slot in a ``gcs-preset`` read."""
    details = (payload or {}).get("gcsPresetExperienceDetails")
    if not isinstance(details, list):
        return None
    for entry in details:
        if not isinstance(entry, dict):
            continue
        try:
            if int(str(entry.get("presetId"))) == preset_id:
                return entry
        except (TypeError, ValueError):
            continue
    return None


def plan_preset_timer(
    payload: Any, preset_id: int, target_seconds: int
) -> PresetTimerPlan:
    """Decide whether a preset's stored timer needs rewriting, and with what.

    ``writepreset`` **replaces the whole record**, so an omitted field is a silent edit.
    That is why this reads the raw REST payload rather than the parsed state model: only
    the payload still carries the name, volume and per-valve ``hexString`` that have to be
    written straight back unchanged. Everything except ``time`` is preserved byte for byte.

    Kept pure — no I/O, no Home Assistant — so the offline suite can prove the exact
    payload for a write that reconfigures the owner's shower.
    """
    record = _preset_record(payload, preset_id)
    if record is None:
        return PresetTimerPlan("absent")

    valves: dict[int, str] = {}
    for detail in record.get("valveDetails") or []:
        if not isinstance(detail, dict):
            continue
        index = str(detail.get("valveIndex") or "")
        word = str(detail.get("hexString") or "").strip().lower()
        if not index.lower().startswith("valve") or not word or set(word) == {"0"}:
            continue
        try:
            valves[int(index[5:])] = word
        except ValueError:
            continue

    name = str(record.get("title") or record.get("name") or "").strip()
    if not name and not valves:
        return PresetTimerPlan("empty")

    try:
        previous: int | None = int(str(record.get("time")))
    except (TypeError, ValueError):
        previous = None

    volume = str(record.get("volume") or "0")
    if previous == target_seconds:
        return PresetTimerPlan("already", name, volume, valves, previous)
    return PresetTimerPlan("rewrite", name, volume, valves, previous)


class GcsDevice:
    """Command surface for one Anthem digital valve."""

    def __init__(
        self,
        client: KohlerClient,
        device_id: str,
        temperature_unit: str = "Fahrenheit",
        model: ValveModel | str = DEFAULT_VALVE_MODEL,
    ) -> None:
        self._client = client
        self.device_id = device_id
        self.temperature_unit = temperature_unit
        # The valve model decides how many outlets exist and which valve each sits on.
        # It cannot be read reliably from the API, so the user picks it at setup.
        self.model = model if isinstance(model, ValveModel) else get_valve_model(model)

    @property
    def outlet_count(self) -> int:
        """How many physical outlets this valve has."""
        return self.model.total_outlets

    # ------------------------------------------------------------------ #
    # Raw valve writes
    # ------------------------------------------------------------------ #
    async def async_write_valves(self, valve1: str, valve2: str) -> Any:
        """Send a pair of already-encoded valve command words.

        This is the one write path the device honours; everything else here builds the
        two words and calls through to it.
        """
        payload = {
            "deviceId": self.device_id,
            "sku": SKU_GCS,
            "tenantId": self._client.tenant_id,
            "gcsValveControlModel": {
                "primaryValve1": valve1.upper(),
                "secondaryValve1": valve2.upper(),
                **{slot: UNUSED_VALVE_WORD for slot in SECONDARY_SLOTS},
            },
        }
        return await self._client.async_request(
            "POST", GCS_SOLOWRITESYSTEM, json_body=payload
        )

    async def async_turn_on(
        self,
        outlets: list[bool],
        temperature: float,
        flow_percent: float = 100,
    ) -> Any:
        """Open the given outlets at a temperature and flow.

        ``outlets`` has one flag per physical outlet on this model — two for a K-28209,
        six for a K-28212.

        ``temperature`` is in the account's unit and converted to Celsius here, because
        the valve byte is always Celsius regardless of the account's display preference.
        """
        if len(outlets) != self.model.total_outlets:
            raise ValveHexError(
                f"{self.model.sku} has {self.model.total_outlets} outlets, "
                f"got {len(outlets)} flags"
            )
        celsius = unit_to_celsius(temperature, self.temperature_unit)
        valve1, valve2 = encode_pair(self.model, celsius, flow_percent, outlets)
        return await self.async_write_valves(valve1, valve2)

    async def async_turn_off(self, temperature: float | None = None) -> Any:
        """Stop every outlet on both valves.

        Uses mask ``0x00`` with a valid prefix. The upstream library's ``turn_off()``
        sends an all-zero ``primaryValve1``, whose ``0x00`` prefix addresses no valve at
        all, so the firmware ignores it — that is the "could turn on but never off" bug.
        """
        celsius = (
            unit_to_celsius(temperature, self.temperature_unit)
            if temperature is not None
            else 38.0
        )
        valve1, valve2 = stop_pair(self.model, celsius)
        return await self.async_write_valves(valve1, valve2)

    async def async_pause(self, temperature: float | None = None) -> Any:
        """Pause both valves, holding the session open (mask ``0x40``)."""
        celsius = (
            unit_to_celsius(temperature, self.temperature_unit)
            if temperature is not None
            else 38.0
        )
        valve1, valve2 = pause_pair(self.model, celsius)
        return await self.async_write_valves(valve1, valve2)

    async def async_set_outlet_mask(
        self,
        valve1_mask: int,
        valve2_mask: int,
        temperature: float,
        flow_percent: float = 100,
    ) -> Any:
        """Write explicit per-valve outlet masks, for callers that already have them."""
        celsius = unit_to_celsius(temperature, self.temperature_unit)
        return await self.async_write_valves(
            encode_word(VALVE1_PREFIX, celsius, flow_percent, valve1_mask),
            encode_word(VALVE2_PREFIX, celsius, flow_percent, valve2_mask),
        )

    # ------------------------------------------------------------------ #
    # Presets
    # ------------------------------------------------------------------ #
    async def async_activate_preset(self, preset_id: Any, on: bool = True) -> Any:
        """Start or stop a preset. **One call — no valve write needed.**

        The controller runs the stored preset itself, so this replaces the two-step
        "select then open the valves" dance entirely.

        The body is ``{preset, action}``. The ``kohler-anthem`` library posts
        ``presetOrExperienceId`` instead, which the backend accepts with a correlationId
        and then ignores — the reason presets "returned success but nothing happened", and
        why a ``solowritesystem`` follow-up was bolted on to compensate. Confirmed live:
        the library's body left ``presetOrExperienceId`` at ``'0'`` and moved no valve.
        """
        payload = {
            "deviceId": self.device_id,
            "sku": SKU_GCS,
            "tenantId": self._client.tenant_id,
            "preset": str(preset_id),
            "action": "On" if on else "Off",
        }
        return await self._client.async_request(
            "POST", GCS_CONTROL_PRESET, json_body=payload
        )

    async def async_write_preset(
        self,
        preset_id: Any,
        name: str,
        valves: dict[int, str],
        *,
        time_seconds: int = 1800,
        volume: str = "",
    ) -> Any:
        """Overwrite an existing preset.

        ``valves`` maps a 1-based valve number to a **3-byte preset word** (see
        :func:`~.valve_hex.encode_preset_word`). Unlisted valves are sent empty.

        Three shapes make this silently no-op while still returning success: posting to
        ``createpreset`` (which makes a new preset instead of editing), omitting the
        ``gcsPresetControlModel`` wrapper or the ``presetId`` inside it, or sending 4-byte
        command words where 3-byte preset words belong.
        """
        model = {
            "presetId": str(preset_id),
            "name": name,
            "time": str(time_seconds),
            "volume": volume,
        }
        model.update(self._valve_fields(valves))
        payload = {
            "deviceId": self.device_id,
            "sku": SKU_GCS,
            "tenantId": self._client.tenant_id,
            "gcsPresetControlModel": model,
        }
        return await self._client.async_request(
            "POST", GCS_WRITE_PRESET, json_body=payload
        )

    async def async_sync_preset_timer(
        self, preset_id: int, target_seconds: int, *, presets: Any = None
    ) -> PresetTimerPlan:
        """Read one preset and, if its stored timer differs, write the target in.

        Read-then-conditionally-write, so it is idempotent: run it a hundred times and it
        sends at most one write, the first time. Everything except ``time`` is written back
        exactly as read — see :func:`plan_preset_timer` for why that matters.

        Returns the plan, whose ``reason`` says what happened. Raises whatever the client
        raises; the caller decides whether a failure is worth failing setup over.

        ``presets`` is an already-fetched ``gcs-preset`` payload, to save re-reading an
        endpoint the caller just read. Added 2026-08-21: the coordinator seeds state at
        setup and then calls this on the next line, which read the same endpoint twice.

        ⚠️ **Whatever is passed here is written back to the owner's shower.**
        ``writepreset`` replaces the whole record, so the name, volume and per-valve
        ``hexString`` in this payload are echoed verbatim — a stale payload silently reverts
        the preset to whatever it held when the payload was taken. **Pass only a read from
        moments ago, in the same setup pass. When in doubt, pass nothing and let it read.**
        """
        payload = (
            presets
            if presets is not None
            else await self._client.async_get_gcs_presets(self.device_id)
        )
        plan = plan_preset_timer(payload, preset_id, target_seconds)
        if plan.needed:
            await self.async_write_preset(
                preset_id,
                plan.name,
                plan.valves,
                time_seconds=target_seconds,
                volume=plan.volume,
            )
        return plan

    async def async_create_preset(
        self,
        name: str,
        valves: dict[int, str],
        *,
        time_seconds: int = 1800,
        volume: str = "",
    ) -> Any:
        """Create a new preset. Flat body, no wrapper and no ``presetId``."""
        payload = {
            "deviceId": self.device_id,
            "sku": SKU_GCS,
            "tenantId": self._client.tenant_id,
            "name": name,
            "time": str(time_seconds),
            "volume": volume,
        }
        payload.update(self._valve_fields(valves))
        return await self._client.async_request(
            "POST", GCS_CREATE_PRESET, json_body=payload
        )

    @staticmethod
    def _valve_fields(valves: dict[int, str]) -> dict[str, str]:
        """Build valve1..valve8 fields. Empty string for unused, per the app's own body."""
        fields = {}
        for number in range(1, 9):
            word = valves.get(number)
            fields[f"valve{number}"] = word.lower() if word else ""
        return fields

    # ------------------------------------------------------------------ #
    # Warmup
    # ------------------------------------------------------------------ #
    async def async_set_warmup(self, mode: str) -> Any:
        """Set the warmup mode.

        Warmup is a **mode toggle**, not a run-now command — there is no separate start and
        stop. The mode *is* the on/off state, and once enabled the valve runs it by itself.

        The four fields below are the whole request model
        (``AnthemWriteWarmUpRequestModel``): there is no duration, no delay, no outlet list
        and no temperature. Re-confirmed against Konnect Android 3.0.1 on 2026-08-20.

        ⚠️ **``warmUp`` is required, and omitting it fails silently** — Kohler's cloud
        returns 200 and the device ignores the request. That is the single most common bug in
        implementations of this call, because the published curl examples show a three-field
        body; the upstream ``kohler-anthem`` library has it. Hence the guard: a caller that
        cannot name a mode must not reach the API at all, because the failure it would get
        back is indistinguishable from success.

        The app blocks this while the system is active, so set it when idle — see
        ``KohlerAnthemPlusCoordinator.async_set_warmup``, which mirrors that guard.

        ⚠️ **Turning warmup off means writing ``warmUpDisabled`` here.** It is *not* posting
        ``presetOrExperienceId: 0`` to ``controlpresetorexperience``, which is what
        ``kohler-anthem``'s ``stop_warmup`` does: that clears a running preset and leaves the
        warmup mode exactly as it was — a different field on a different endpoint.

        ``mode`` is validated by the caller, not here. ``WARMUP_MODES_CURRENT`` in
        ``const.py`` holds the three the current app offers; the two legacy delayed-start
        values are decodable but should not be written. See ``docs/gcs/api.md`` §3.
        """
        if not mode or not mode.strip():
            raise ValueError(
                "warmUp mode is required: an empty mode is accepted by Kohler's cloud with "
                "HTTP 200 and then ignored by the valve"
            )
        payload = {
            "deviceId": self.device_id,
            "sku": SKU_GCS,
            "tenantId": self._client.tenant_id,
            "warmUp": mode,
        }
        return await self._client.async_request("POST", GCS_WARMUP, json_body=payload)

