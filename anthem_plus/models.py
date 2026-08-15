"""Kohler Anthem hardware models and their outlet topology.

The number of outlets, and **which valve each one lives on**, varies by valve model. This
cannot be inferred reliably from the API, so the user selects their model at setup and
everything downstream derives from it.

Getting this wrong is not cosmetic. On a 4-outlet system, outlet 3 is the *first* outlet of
valve 2 — but on a 6-outlet system, outlet 3 is the *third* outlet of valve 1. Code that
assumes "valve1 carries outlets 1-3" silently commands the wrong outlet on a K-28211.

Each valve exposes three outlet bits in its command word regardless of how many are
physically installed; a model simply uses fewer of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Every valve's command word has three outlet bits, whatever the model populates.
OUTLET_BITS_PER_VALVE = 3


@dataclass(frozen=True)
class ValveModel:
    """One Anthem digital valve model and how its outlets map onto the two valves."""

    sku: str
    name: str
    outlets_valve1: int
    outlets_valve2: int

    @property
    def total_outlets(self) -> int:
        """How many physical outlets this model has."""
        return self.outlets_valve1 + self.outlets_valve2

    @property
    def uses_valve2(self) -> bool:
        """Whether the second valve is populated.

        When it is not, ``secondaryValve1`` must still be present in the payload and is
        sent as the all-zero ignore word.
        """
        return self.outlets_valve2 > 0

    @property
    def zones(self) -> list[int]:
        """The zone numbers this model actually has — ``[1]`` or ``[1, 2]``.

        Zones are the hardware's own unit: a multi-outlet Anthem is physically two valve
        bodies joined, and every API surface addresses them separately. Naming entities per
        zone means no global outlet numbering has to be invented, and therefore no
        model-dependent mapping can be got wrong.
        """
        return [1, 2] if self.uses_valve2 else [1]

    def outlets_in_zone(self, zone: int) -> int:
        """How many outlets that zone has."""
        if zone == 1:
            return self.outlets_valve1
        if zone == 2:
            return self.outlets_valve2
        raise ValueError(f"{self.sku} has zones {self.zones}; got {zone}")

    def outlet_location(self, outlet: int) -> tuple[int, int]:
        """Map a 1-based GLOBAL outlet number to ``(zone, bit_index)``.

        Retained for the few places that genuinely need a flat sequence — chiefly combining
        the controller's two zone arrays. **Entities are named per zone instead**, because
        this mapping is model-dependent (outlet 3 is zone 2's first on a K-28211 but zone
        1's third on a K-28212) and getting it wrong silently commands the wrong outlet.
        """
        if not 1 <= outlet <= self.total_outlets:
            raise ValueError(
                f"{self.sku} has outlets 1-{self.total_outlets}; got {outlet}"
            )
        if outlet <= self.outlets_valve1:
            return 1, outlet - 1
        return 2, outlet - self.outlets_valve1 - 1

    def split_outlets(self, outlets: list[bool]) -> tuple[list[bool], list[bool]]:
        """Split per-outlet flags into (valve1 flags, valve2 flags)."""
        if len(outlets) != self.total_outlets:
            raise ValueError(
                f"{self.sku} has {self.total_outlets} outlets, got {len(outlets)} flags"
            )
        return (
            outlets[: self.outlets_valve1],
            outlets[self.outlets_valve1 :],
        )

    def outlet_labels(self) -> list[str]:
        """Human labels per zone, e.g. ``["Zone 1 Outlet 1", ...]``."""
        return [
            f"Zone {zone} Outlet {n}"
            for zone in self.zones
            for n in range(1, self.outlets_in_zone(zone) + 1)
        ]


# The four Anthem digital valve models. Valve/outlet splits are from the product line;
# only K-28212 has been exercised against real hardware.
VALVE_MODELS: dict[str, ValveModel] = {
    "K-28209": ValveModel("K-28209", "Anthem 2-outlet valve", 2, 0),
    "K-28210": ValveModel("K-28210", "Anthem 3-outlet valve", 3, 0),
    "K-28211": ValveModel("K-28211", "Anthem 4-outlet valve", 2, 2),
    "K-28212": ValveModel("K-28212", "Anthem 6-outlet valve", 3, 3),
}

DEFAULT_VALVE_MODEL = "K-28212"


def model_for_topology(outlets_valve1: int, outlets_valve2: int) -> ValveModel:
    """Build a model from a detected outlet split, naming it if it matches a known SKU.

    Real installs are not obliged to match Kohler's four catalogue models, so an
    unrecognised split still produces a usable model rather than an error.
    """
    for model in VALVE_MODELS.values():
        if (model.outlets_valve1, model.outlets_valve2) == (
            outlets_valve1,
            outlets_valve2,
        ):
            return model
    label = (
        f"{outlets_valve1}+{outlets_valve2}"
        if outlets_valve2
        else str(outlets_valve1)
    )
    return ValveModel(
        sku="detected",
        name=f"Detected valve ({label} outlets)",
        outlets_valve1=outlets_valve1,
        outlets_valve2=outlets_valve2,
    )


def get_valve_model(sku: str) -> ValveModel:
    """Look up a valve model by SKU, case-insensitively."""
    model = VALVE_MODELS.get(sku.strip().upper())
    if model is None:
        raise ValueError(
            f"Unknown valve model {sku!r}; expected one of {sorted(VALVE_MODELS)}"
        )
    return model


# ---------------------------------------------------------------------------
# Unverified assumption, flagged deliberately
# ---------------------------------------------------------------------------
# On a 2-outlet valve (K-28209, and each half of a K-28211), outlets are assumed to use
# mask bits 0 and 1 — the same low bits a 3-outlet valve uses for its first two outlets.
# This has NOT been confirmed on hardware: the only system tested has 3-outlet valves. If
# a 2-outlet valve turns out to use different bits, `outlet_location` is the single place
# to correct it.
TWO_OUTLET_BIT_MAPPING_VERIFIED = False


# ---------------------------------------------------------------------------
# Where outlet / temperature / flow state comes from
# ---------------------------------------------------------------------------
class OutletStateSource(Enum):
    """Which channel feeds the outlet, temperature, and flow entities."""

    GCS_VALVE_HEX = "gcs_valve_hex"
    """The GCS ``GCS_SOLO_STS`` valve command word. Authoritative and always current."""

    HUB_MQTT = "hub_mqtt"
    """The HUB ``SHOWER_VALVE_STS`` message. The only option on a HUB-only account."""


def resolve_outlet_source(has_gcs: bool, has_hub: bool) -> OutletStateSource | None:
    """Pick the outlet state source for an account.

    **Whenever a GCS device is present, use the GCS valve word — never the HUB's.**

    Partly latency: the HUB trails the valve word by 0.3-2 seconds and briefly reports
    pre-transition values. But mainly correctness — when the shower is driven through the
    GCS ``solowritesystem`` endpoint and the Anthem Plus touchscreen is never touched, the
    HUB's reported state does not follow the valve. Verified live: 21 seconds with outlet 4
    open and ``hub-state`` reporting an idle system throughout, corroborated by the HUB's
    Alexa and Google Home states also staying off.

    Measured precisely: the HUB emits ``SHOWER_VALVE_STS`` only for transitions that land in
    an **OFF** state. With outlet 4 held open for five minutes it emitted nothing at all;
    the stop produced one message reporting ``status=OFF``, an all-zero ``outlets`` array,
    and null ``temperature``/``flowrate``. Confirmed by two independent MQTT clients.

    So the HUB never reports a GCS-driven open outlet on any surface.

    A HUB-only account has no valve word available, so it uses the HUB stream. That works
    because such a system is driven through favourites and the touchscreen, and the outlet
    array does populate for those.

    Returns ``None`` when neither device is present.
    """
    if has_gcs:
        return OutletStateSource.GCS_VALVE_HEX
    if has_hub:
        return OutletStateSource.HUB_MQTT
    return None


# ---------------------------------------------------------------------------
# Touchscreen interfaces — which controller gets a device into the Konnect app
# ---------------------------------------------------------------------------
# This determines what appears on an account, and is not documented by Kohler:
#
#   K-28214       first-generation Anthem touchscreen. Plugs directly into the digital
#                 valve. This is the ONLY way to add a GCS valve to the Konnect app.
#   K-28214-ACS   Anthem Plus touchscreen. Plugs into the HUB system controller, not the
#                 valve. Adds the HUB to the Konnect app — and offers NO option to add the
#                 GCS valve.
#
# So an Anthem Plus owner with only the -ACS screen sees a HUB on their account and no
# GCS, even though a digital valve is physically present.
#
# A digital valve has TWO interface ports, and although the manual does not say so, a
# first-gen K-28214 and a HUB controller can be connected to the SAME valve at once. Both
# interfaces stay consistent because they read state from MQTT and the wired link. That is
# how an account ends up with both a GCS and a HUB entry for one physical shower.
TOUCHSCREEN_GCS = "K-28214"
TOUCHSCREEN_HUB = "K-28214-ACS"
