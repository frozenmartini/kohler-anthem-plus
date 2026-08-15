"""Commands for the Anthem Plus system controller (SKU ``HUB``).

The HUB is favourite-centric. There is **no direct "set outlet/temperature/flow now"**
command: to run a specific configuration you create or edit a *favourite* and activate it.
The only direct commands are bare on/off for the controller's own stored default
(``valvecontrol`` / ``steamcontrol``) and ``stopall``.

Two constraints shape every caller:

* **Editing a favourite is rejected while the system runs** (``statusCode 902``), surfaced
  as :class:`~.client.DeviceRunning`. Activating one is allowed at any time — so the
  practical pattern is to pre-create a favourite per state you want and switch between
  them by activation, never editing at runtime.
* **An all-off favourite is not the same as ``stopall``.** Activating an empty favourite
  stops the outputs but leaves the system reporting that favourite as running; only
  ``stopall`` fully idles it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import KohlerClient
from .models import ValveModel
from .const import (
    EXPERIENCE_ENDPOINTS,
    HUB_FAVORITE,
    HUB_FAVORITE_CONTROL,
    HUB_STEAM_CONTROL,
    HUB_STOP_ALL,
    HUB_VALVE_CONTROL,
    SKU_HUB,
)

ON = "ON"
OFF = "OFF"

# Read and write disagree on shape, which is a standing source of bugs:
#   READ  water.zoneN.outlets     = a COUNT, and outletState = a 6-slot array
#   WRITE water.zoneN.outlets     = a list of 0-BASED POSITIONS to open
#
# The MQTT SHOWER_VALVE_STS message reports the same 6-slot array per zone, e.g.
# [1,0,0,0,0,0] meaning that zone's outlet 1 is on. Every array is padded to six slots
# regardless of hardware; only the leading slots for THAT zone's valve carry meaning —
# three on a K-28210/K-28212, two on a K-28209 or either half of a K-28211. The trailing
# slots are always zero and must be ignored, not read as extra outlets.
#
# A zone maps to a valve: zone1 is valve1, zone2 is valve2.
OUTLETS_PER_ZONE = 3
ZONE_ARRAY_SLOTS = 6


def outlet_positions(outlets: list[bool]) -> list[int]:
    """Convert one zone's outlet flags into the 0-based position list a write expects."""
    return [index for index, is_on in enumerate(outlets) if is_on]


def outlet_flags(
    outlet_state: list[int] | None, outlet_count: int = OUTLETS_PER_ZONE
) -> list[bool]:
    """Convert one zone's padded outlet array into that zone's real outlet flags.

    ``outlet_count`` is how many outlets that zone's valve actually has; the remaining
    slots are padding.
    """
    state = outlet_state or []
    return [bool(state[i]) if i < len(state) else False for i in range(outlet_count)]


def zone_outlet_flags(
    model: ValveModel,
    zone1_outlets: list[int] | None,
    zone2_outlets: list[int] | None = None,
) -> list[bool]:
    """Combine both zones' padded arrays into global Home Assistant outlet flags.

    Returns one flag per physical outlet, numbered the way every surface in this
    integration numbers them: zone1's outlets first, then zone2's. On a 4-outlet K-28211
    that makes zone2's first outlet "Outlet 3".
    """
    flags = outlet_flags(zone1_outlets, model.outlets_valve1)
    if model.uses_valve2:
        flags += outlet_flags(zone2_outlets, model.outlets_valve2)
    return flags


def split_zone_outlets(
    model: ValveModel, outlets: list[bool]
) -> tuple[list[bool], list[bool]]:
    """Split global outlet flags into (zone1 flags, zone2 flags) for a write."""
    return model.split_outlets(outlets)


# The HUB uses "zone" and "valve" interchangeably, and not consistently within one payload:
# hub-state's shower entries carry `zone: "1"`, favourites nest under `water.zone1`,
# hub-configuration's parts are `valve1`/`valve2`, and MQTT SHOWER_VALVE_STS attributes may
# carry either a `zone` number or a `component` of "valve1"/"valve2". They all mean the same
# thing. Anything reading a HUB payload should go through zone_number() rather than picking
# one field and hoping.
_ZONE_FIELDS = ("zone", "component", "valve", "valveIndex", "zoneIndex")


def zone_number(attribute: dict[str, Any]) -> int | None:
    """Identify which zone/valve a HUB payload entry refers to, or None.

    Accepts every spelling seen in the wild: ``zone: "1"``, ``zone: 1``,
    ``component: "valve1"``, ``valveIndex: "Valve2"``, and so on.
    """
    for field in _ZONE_FIELDS:
        raw = attribute.get(field)
        if raw is None:
            continue
        text = str(raw).strip().lower()
        # Bare number: "1" / "2".
        if text in {"1", "2"}:
            return int(text)
        # Prefixed forms: "valve1", "zone2", "Valve1".
        for prefix in ("valve", "zone"):
            if text.startswith(prefix):
                suffix = text[len(prefix) :].strip()
                if suffix in {"1", "2"}:
                    return int(suffix)
    return None


CONNECTED = "Connected"


@dataclass(frozen=True)
class HubCapabilities:
    """Which accessories are attached, and therefore which favourite fields exist.

    A favourite bundles ``water``, ``steam``, ``music``, and ``light`` components, but only
    those whose hardware is present are meaningful. An account with no amplifier has no
    music field to set.

    None of this affects **activating** a favourite — that is always just an id and a
    name, whatever the favourite contains.
    """

    water: bool = False
    music: bool = False
    light: bool = False
    steam: bool = False
    # Whether this was ever populated from a real read. Cannot be inferred from the flags:
    # a controller with no accessories is legitimately all-False, so "empty" and "unread"
    # look identical without this.
    known: bool = False

    @classmethod
    def from_configuration(cls, configuration: dict[str, Any]) -> HubCapabilities:
        """Read capabilities from a ``hub-configuration`` response.

        ``parts`` reports ``Connected`` / ``NotConnected`` / ``null`` per component.

        Note ``parts.valve1`` / ``valve2`` count **physical valve units**, whereas the GCS
        API's ``valve1``/``valve2`` count **zones** within one unit —
        ``HUB valve1 == GCS valve1 + valve2``. So a 6-outlet K-28212 correctly reports
        ``valve1: Connected`` and ``valve2: NotConnected``: there is no second valve body.

        Never gate zone-2 entities on ``parts.valve2``; it would hide half the outlets on a
        normal install. Use ``zoneone``/``zonetwo`` ``configuredoutlets`` for topology.
        """
        parts = (configuration or {}).get("parts") or {}

        def connected(*names: str) -> bool:
            return any(parts.get(name) == CONNECTED for name in names)

        return cls(
            water=connected("valve1", "valve2", "valveOne", "valveTwo"),
            music=connected("amplifier", "music"),
            light=connected("light", "lightBridge"),
            steam=connected("steam"),
            known=True,
        )

    def describe(self) -> str:
        """A short human summary of the attached accessories."""
        present = [n for n in ("water", "music", "light", "steam") if getattr(self, n)]
        return ", ".join(present) if present else "no accessories detected"


class HubDevice:
    """Command surface for one Anthem Plus system controller."""

    def __init__(
        self,
        client: KohlerClient,
        device_id: str,
        temperature_unit: str = "Fahrenheit",
    ) -> None:
        self._client = client
        self.device_id = device_id
        # Unlike the GCS valve byte, HUB favourite temperatures are integers in the
        # ACCOUNT's unit — the app sends °F as-is and only converts when the account is
        # set to Celsius. So no conversion happens here.
        self.temperature_unit = temperature_unit

    def _base(self) -> dict[str, Any]:
        return {
            "deviceId": self.device_id,
            "sku": SKU_HUB,
            "tenantId": self._client.tenant_id,
        }

    # ------------------------------------------------------------------ #
    # Direct control (the controller's own stored default)
    # ------------------------------------------------------------------ #
    async def async_set_shower(self, on: bool) -> Any:
        """Run or stop the controller's default shower configuration."""
        return await self._client.async_request(
            "POST", HUB_VALVE_CONTROL, json_body={**self._base(), "valveOnOff": ON if on else OFF}
        )

    async def async_set_steam(self, on: bool) -> Any:
        """Run or stop the controller's default steam configuration."""
        return await self._client.async_request(
            "POST", HUB_STEAM_CONTROL, json_body={**self._base(), "steamOnOff": ON if on else OFF}
        )

    async def async_stop_all(self) -> Any:
        """Fully idle the system — the only true "off"."""
        return await self._client.async_request(
            "POST", HUB_STOP_ALL, json_body=self._base()
        )

    # ------------------------------------------------------------------ #
    # Favourites
    # ------------------------------------------------------------------ #
    async def async_activate_favorite(
        self, favorite_id: Any, name: str, on: bool = True
    ) -> Any:
        """Start or stop a favourite. Allowed even while something else runs."""
        return await self._client.async_request(
            "POST",
            HUB_FAVORITE_CONTROL,
            json_body={
                **self._base(),
                # Control takes the id as a STRING; create/delete take it as an integer.
                "id": str(favorite_id),
                "name": name,
                "state": ON if on else OFF,
            },
        )

    async def async_create_favorite(
        self,
        name: str,
        *,
        zone1: dict[str, Any] | None = None,
        zone2: dict[str, Any] | None = None,
        steam: dict[str, Any] | None = None,
        music: dict[str, Any] | None = None,
        light: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Create a favourite. Omit ``id`` — that is what makes it a create."""
        return await self._client.async_request(
            "POST",
            HUB_FAVORITE,
            json_body=self._favorite_body(
                name, zone1=zone1, zone2=zone2, steam=steam, music=music, light=light
            ),
        )

    async def async_edit_favorite(
        self,
        favorite_id: int,
        name: str,
        *,
        zone1: dict[str, Any] | None = None,
        zone2: dict[str, Any] | None = None,
        steam: dict[str, Any] | None = None,
        music: dict[str, Any] | None = None,
        light: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Edit a favourite.

        Raises :class:`~.client.DeviceRunning` if the system is active — stop it first.
        """
        body = self._favorite_body(
            name, zone1=zone1, zone2=zone2, steam=steam, music=music, light=light
        )
        body["id"] = int(favorite_id)
        return await self._client.async_request("PATCH", HUB_FAVORITE, json_body=body)

    async def async_delete_favorite(self, favorite_id: int, name: str) -> Any:
        """Delete a favourite."""
        return await self._client.async_request(
            "DELETE",
            HUB_FAVORITE,
            json_body={**self._base(), "name": name, "id": int(favorite_id)},
        )

    def _favorite_body(
        self,
        name: str,
        *,
        zone1: dict[str, Any] | None,
        zone2: dict[str, Any] | None,
        steam: dict[str, Any] | None,
        music: dict[str, Any] | None,
        light: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Assemble a favourite body.

        ``music`` is omitted entirely when unset: sending an all-null music object makes
        the whole request fail with HTTP 400, whereas leaving the key out is accepted.
        """
        body: dict[str, Any] = {
            **self._base(),
            "name": name,
            # The app sends null for an unused zone; a zone with outlets: [] also works.
            "water": {"zone1": zone1, "zone2": zone2},
            "steam": steam or {"temperature": 0, "time": 0},
            "light": light if light is not None else [],
        }
        if music is not None:
            body["music"] = music
        return body

    @staticmethod
    def zone(
        temperature: int, outlets: list[bool], flowrate: int = 100
    ) -> dict[str, Any]:
        """Build a water zone for a favourite body.

        ``temperature`` is an integer in the account's unit. ``outlets`` are per-outlet
        flags, converted here to the 0-based position list the API expects.
        """
        return {
            "temperature": int(temperature),
            "flowrate": int(flowrate),
            "outlets": outlet_positions(outlets),
        }

    @staticmethod
    def zones_for(
        model: ValveModel,
        outlets: list[bool],
        temperature: int,
        flowrate: int = 100,
    ) -> dict[str, dict[str, Any] | None]:
        """Build both water zones from GLOBAL outlet flags for this valve model.

        Pass one flag per physical outlet (four for a K-28211, six for a K-28212); this
        splits them across zone1/zone2 the way the model dictates and converts each zone's
        flags to the 0-based position list a write expects.

        A zone the model does not have is sent as ``null``, which is what the app sends
        for an unused zone.
        """
        zone1_flags, zone2_flags = model.split_outlets(outlets)
        zones: dict[str, dict[str, Any] | None] = {
            "zone1": HubDevice.zone(temperature, zone1_flags, flowrate)
        }
        zones["zone2"] = (
            HubDevice.zone(temperature, zone2_flags, flowrate)
            if model.uses_valve2
            else None
        )
        return zones

    @staticmethod
    def music(source: str, volume: int = 70) -> dict[str, Any]:
        """Build a music component. ``source`` is ``"Aux"`` or ``"SdCard"``.

        There is no Bluetooth source. ``songID``/``musicRepeat`` are only meaningful for
        Kohler Playlist streaming and are sent empty otherwise.
        """
        return {
            "source": source,
            "songID": "",
            "musicRepeat": "",
            "volume": int(volume),
        }

    # ------------------------------------------------------------------ #
    # Experiences
    # ------------------------------------------------------------------ #
    async def async_control_experience(
        self, title: str, category: str, on: bool = True
    ) -> Any:
        """Start or stop a firmware experience.

        All three experience endpoints share one body; the path is chosen by the category
        the experience appeared under in the experiences read. Sending a shower experience
        to the steam path does not work.

        ``title`` is the experience's TITLE string, not its numeric id.

        Experiences carry no outlet or curve data in the API — the program is internal to
        the firmware and always runs on the default zone1/outlet1. Use a favourite when
        you need a specific outlet.
        """
        endpoint = EXPERIENCE_ENDPOINTS.get(category)
        if endpoint is None:
            raise ValueError(
                f"Unknown experience category {category!r}; expected one of "
                f"{sorted(EXPERIENCE_ENDPOINTS)}"
            )
        return await self._client.async_request(
            "POST",
            endpoint,
            json_body={**self._base(), "name": title, "status": ON if on else OFF},
        )
