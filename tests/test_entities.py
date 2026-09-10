"""Every entity must construct, and be named and identified as intended.

**This file exists because v0.6.6 shipped with two entities missing.** An edit removed the
body of `ZoneNumberBase` — `__init__`, `_word`, `_attr_mode` — leaving the class declaration
behind. `python -m py_compile` passes on an empty class, so the only signal was a user
installing the release and finding the Temperature and Flow controls gone.

The lesson is narrow: *syntax checking is not verification*. These tests run each platform's
real `async_setup_entry` and assert the resulting entity set, so a deleted method, a broken
constructor, an entity dropped from setup, or a rename that collides with another id fails
here rather than on someone's shower.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from .conftest import make_coordinator, make_valve

PLATFORMS = ("number", "switch", "sensor", "binary_sensor", "select", "button")


def platform(name: str):
    return importlib.import_module(f"custom_components.kohler_anthem_plus.{name}")


def collect(name: str, coordinator) -> list:
    """Run a platform's real `async_setup_entry` and return what it added."""
    added: list = []
    hass = SimpleNamespace(data={"kohler_anthem_plus": {"test": coordinator}})
    entry = SimpleNamespace(entry_id="test", data={}, options={})
    asyncio.run(
        platform(name).async_setup_entry(
            hass, entry, lambda e, *a, **k: added.extend(e)
        )
    )
    return added


# --------------------------------------------------------------------------- #
# The regression that started all this
# --------------------------------------------------------------------------- #
def test_temperature_and_flow_numbers_exist(coordinator):
    """**The 0.6.6 regression test.** Both numbers must be created and usable."""
    entities = collect("number", coordinator)
    assert sorted(e.name for e in entities) == ["Flow", "Temperature"]
    for entity in entities:
        # A constructor that produced an unusable entity would still pass a name check;
        # reading the value proves the inherited plumbing survived.
        assert entity.unique_id
        assert entity.native_value is not None


def test_number_unique_ids_are_stable(coordinator):
    """Renames are display-only — these ids are what existing automations resolve through."""
    entities = {e.name: e for e in collect("number", coordinator)}
    assert entities["Temperature"].unique_id == "gcs-test0001_temperature_zone_1"
    assert entities["Flow"].unique_id == "gcs-test0001_flow_zone_1"


# --------------------------------------------------------------------------- #
# Every platform builds
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", PLATFORMS)
def test_platform_constructs(name, coordinator):
    """Each platform's setup runs and every entity it makes exposes a unique id."""
    for entity in collect(name, coordinator):
        assert entity.unique_id, f"{name}: {entity} has no unique id"


def test_no_unique_id_collisions(coordinator):
    """Two entities sharing an id is not an error in Home Assistant — the second is
    dropped silently, indistinguishable from never having been written."""
    seen: dict[str, str] = {}
    for name in PLATFORMS:
        for entity in collect(name, coordinator):
            uid = entity.unique_id
            assert uid not in seen, f"{uid} claimed by both {seen[uid]} and {name}"
            seen[uid] = name


# --------------------------------------------------------------------------- #
# Naming
# --------------------------------------------------------------------------- #
def test_outlets_named_after_their_fixture(coordinator):
    names = {e.name for e in collect("switch", coordinator)}
    assert {"Rainhead", "Showerhead", "Handshower"} <= names, sorted(names)
    assert "Shower on" in names


def test_run_time_sensors_follow_outlet_names(coordinator):
    names = {e.name for e in collect("sensor", coordinator)}
    assert "Rainhead Max Run Time" in names, sorted(names)


def test_single_zone_valve_drops_the_zone_prefix(coordinator):
    names = {e.name for e in collect("number", coordinator)}
    assert names == {"Temperature", "Flow"}


def test_two_zone_valve_numbers_each_zone(valve_model):
    """0.7.3: `Temperature 1`/`Temperature 2`, not `Zone 1 Temperature`.

    The number is a suffix so the pair sorts together in every Home Assistant list.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    model = get_valve_model("K-28212")
    coordinator = make_coordinator([make_valve(model, [31, 11, 1, 11, None, 21])])
    names = {e.name for e in collect("number", coordinator)}
    assert names == {
        "Temperature 1",
        "Flow 1",
        "Temperature 2",
        "Flow 2",
    }, sorted(names)


def test_unknown_outlet_type_falls_back_to_position(valve_model):
    """An unconfirmed type code must never be given an invented fixture name."""
    coordinator = make_coordinator([make_valve(valve_model, [999, 11, 1])])
    names = {e.name for e in collect("switch", coordinator)}
    # Single-zone valve, so no zone number — `Outlet 1`, not `Zone 1 Outlet 1`.
    assert "Outlet 1" in names, sorted(names)


def test_duplicate_fixtures_get_distinct_ids(valve_model):
    """Two outlets of one fixture type in a zone is a legal install."""
    coordinator = make_coordinator([make_valve(valve_model, [11, 11, 1])])
    entities = collect("switch", coordinator)
    ids = [e.unique_id for e in entities]
    assert len(ids) == len(set(ids)), ids


# --------------------------------------------------------------------------- #
# Multiple devices
# --------------------------------------------------------------------------- #
def test_two_valves_do_not_share_ids(valve_model):
    """The account this integration is developed against has two valves."""
    coordinator = make_coordinator(
        [
            make_valve(valve_model, [31, 11, 1], device_id="gcs-left", run_time=1800),
            make_valve(valve_model, [31, 11, 1], device_id="gcs-right", run_time=3600),
        ]
    )
    for name in PLATFORMS:
        ids = [e.unique_id for e in collect(name, coordinator)]
        assert len(ids) == len(set(ids)), f"{name}: {ids}"


# --------------------------------------------------------------------------- #
# Naming: Shower Active
# --------------------------------------------------------------------------- #
def test_zone_active_is_named_shower_active(valve_model):
    """0.7.2 renamed `Zone 1 Active`, which said nothing a user recognised.

    Asserts the name AND that the unique id still carries `zone_1` — a rename that moved the
    id would silently orphan history and every automation referencing it.
    """
    coordinator = make_coordinator([make_valve(valve_model, [31, 11, 1])])
    active = [
        e
        for e in collect("binary_sensor", coordinator)
        if e.unique_id.endswith("_zone_1_active")
    ]
    assert len(active) == 1, [
        e.unique_id for e in collect("binary_sensor", coordinator)
    ]
    assert active[0].name == "Shower Active"


# --------------------------------------------------------------------------- #
# Firmware: Kohler reports it in more than one shape
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        ({"about": {"firmware": "00.74"}}, "00.74"),
        ({"otaReportedProperties": {"currentFirmwareVersion": "01.02"}}, "01.02"),
        ({"otaReportedProperties": {"reported": {"swVersion": "02.10"}}}, "02.10"),
        ({"otaReportedProperties": "03.01"}, "03.01"),
        ({"firmwareUpdate": {"currentVersion": "04.05"}}, "04.05"),
        ({"version": "05.06"}, "05.06"),
        ({"version": 74}, "74"),
        # The owner's real shape before 0.7.2: no `about`, so this read `unknown`.
        ({"createdTime": "x", "deviceId": "y", "sku": "z"}, None),
        # A version the cloud WANTS installed is not the one running. Reporting it would be
        # worse than reporting nothing.
        ({"firmwareUpdate": {"targetVersion": "09.99"}}, None),
        ({"version": "   "}, None),
        ({"version": True}, None),
        ({}, None),
    ],
)
def test_firmware_reads_every_known_shape(configuration, expected):
    """Exercises the REAL `Valve.firmware`, not the stand-in.

    `make_valve` returns a `SimpleNamespace`, which cannot carry a property — it holds a
    static `firmware` attribute instead. Asserting against that would test the fake and pass
    no matter what the integration does, which is how the first draft of this test "passed"
    one case by coincidence. So the real property is bound to a minimal object here.
    """
    from custom_components.kohler_anthem_plus.coordinator import Valve

    holder = SimpleNamespace(configuration=configuration)
    assert Valve.firmware.fget(holder) == expected


# --------------------------------------------------------------------------- #
# Naming: zone numbers and fixture numbers must not blur together
# --------------------------------------------------------------------------- #
def test_duplicate_fixture_in_a_multi_zone_valve_reads_zone_dot_position():
    """`Showerhead 1.2`, never `Showerhead 2 1`.

    Both the zone suffix and the duplicate-fixture suffix are bare numbers, so a valve with
    two zones AND a repeated fixture would otherwise emit two numbers in an order nobody can
    read. The zone leads, separated by a dot.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model
    from custom_components.kohler_anthem_plus.entity import outlet_name

    model = get_valve_model("K-28211")
    valve = make_valve(model, [11, 11, 11, 11])
    assert outlet_name(valve, 1, 1) == "Showerhead 1.1"
    assert outlet_name(valve, 1, 2) == "Showerhead 1.2"
    assert outlet_name(valve, 2, 1) == "Showerhead 2.1"


def test_duplicate_fixture_in_a_single_zone_valve_has_no_zone_number(valve_model):
    """One zone means the number can only mean the fixture — `Showerhead 1`, `Showerhead 2`."""
    from custom_components.kohler_anthem_plus.entity import outlet_name

    valve = make_valve(valve_model, [11, 11, 1])
    assert outlet_name(valve, 1, 1) == "Showerhead 1"
    assert outlet_name(valve, 1, 2) == "Showerhead 2"
    assert outlet_name(valve, 1, 3) == "Handshower"


def test_multi_zone_names_stay_unique_across_every_platform():
    """A name collision builds the same unique id twice and HA drops one entity silently."""
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    model = get_valve_model("K-28212")
    coordinator = make_coordinator([make_valve(model, [11, 11, 11, 11, 11, 11])])
    for platform in PLATFORMS:
        entities = collect(platform, coordinator)
        ids = [e.unique_id for e in entities]
        assert len(ids) == len(set(ids)), f"{platform}: {sorted(ids)}"
        names = [e.name for e in entities if e.name]
        assert len(names) == len(set(names)), f"{platform}: {sorted(names)}"


# --------------------------------------------------------------------------- #
# Water total: published exactly as the device reports it
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The owner's Konnect app read 2056.00 and 6488.75 for the two valves, which are
        # exactly these raw counter values. 0.7.3 divided by four on a misreading of which
        # capture those app figures matched; 0.7.6 reverted it. No scaling belongs here.
        (2056.0, 2056.0),
        (6488.75, 6488.75),
        (8224.0, 8224.0),
        (413.25, 413.25),
        (None, None),
    ],
)
def test_total_flow_is_published_unscaled(raw, expected):
    from custom_components.kohler_anthem_plus.anthem_plus.state import GcsState

    holder = SimpleNamespace(total_flow_filtered=raw)
    assert GcsState.total_flow_gallons.fget(holder) == expected


# --------------------------------------------------------------------------- #
# Flow percentage: the byte is 2 units per percent
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The owner's two valves, verbatim from diagnostics captured 2026-09-10. Both carry
        # ODD flow bytes, which is the case an integer-truncating decode gets wrong.
        ("0195310000000001", 24.5),
        ("0189350000000001", 26.5),
    ],
)
def test_flow_decodes_from_real_hardware_words(raw, expected):
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import decode_word

    assert decode_word(raw).flow_percent == expected


def test_every_legal_flow_byte_round_trips():
    """All 185 bytes in [16, 200] must survive decode -> encode unchanged.

    Half-percent values are ordinary on this hardware, so a decode that truncated or an
    encode that rounded to whole percents would quietly move the valve.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        FLOW_BYTE_MAX,
        FLOW_BYTE_MIN,
        FLOW_PER_PERCENT,
        decode_word,
    )

    for byte in range(FLOW_BYTE_MIN, FLOW_BYTE_MAX + 1):
        percent = decode_word(f"0195{byte:02x}0000000001").flow_percent
        assert round(percent * FLOW_PER_PERCENT) == byte, (byte, percent)


def test_flow_slider_is_whole_percent():
    """Whole-number percentages, by the owner's decision — step and both bounds.

    The wire resolves to 0.5 %, but the control deliberately does not: see `ZoneFlowNumber`.
    The bounds matter as much as the step, because a half-valued bound would put every
    position on the slider on a half and defeat the whole thing.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    coordinator = make_coordinator(
        [make_valve(get_valve_model("K-28210"), [31, 11, 1])]
    )
    flows = [e for e in collect("number", coordinator) if e.name == "Flow"]
    assert len(flows) == 1
    flow = flows[0]
    assert flow.native_step == 1
    assert float(flow.native_min_value).is_integer(), flow.native_min_value
    assert float(flow.native_max_value).is_integer(), flow.native_max_value


def test_flow_rounds_a_half_percent_reading_for_display():
    """The valve reports halves; the control shows whole numbers.

    Both of the owner's valves sit on half-percent bytes, so an unrounded display would show
    a value the slider cannot return to.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import decode_word

    valve = make_valve(get_valve_model("K-28210"), [31, 11, 1])
    flow = next(
        e for e in collect("number", make_coordinator([valve])) if e.name == "Flow"
    )

    # Byte 49 = 24.5 %, with outlet 1 open so the valve's own reading is the one shown.
    valve.gcs_state.valve1 = decode_word("0195310100000001")
    assert valve.gcs_state.flow_is_live
    assert float(flow.native_value).is_integer(), flow.native_value

    # A whole reading is untouched.
    valve.gcs_state.valve1 = decode_word("0195320100000001")  # byte 50 = 25.0 %
    assert flow.native_value == 25


# --------------------------------------------------------------------------- #
# The gcs-usage probe
# --------------------------------------------------------------------------- #
def test_usage_probe_candidates_all_render():
    """Every candidate must survive substitution — one bad placeholder breaks the run.

    The probe makes real network calls, so a `KeyError` here would surface as a failed
    service call against live hardware rather than a test failure.
    """
    from datetime import UTC, datetime, timedelta

    from custom_components.kohler_anthem_plus.services import _USAGE_ATTEMPTS

    now = datetime.now(UTC)
    start = now - timedelta(days=400)
    substitutions = {
        "from": start.date().isoformat(),
        "to": now.date().isoformat(),
        "from_z": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to_z": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from_us": start.strftime("%m-%d-%Y"),
        "to_us": now.strftime("%m-%d-%Y"),
    }
    assert _USAGE_ATTEMPTS
    # The decompiled contract is PascalCase. camelCase is what made the first fifteen
    # candidates fail, so a regression to it is worth catching here.
    parameterised = [query for _, query in _USAGE_ATTEMPTS if query]
    assert parameterised
    for query in parameterised:
        assert "FromDate=" in query and "ToDate=" in query and "Interval=" in query, (
            query
        )
    labels = [label for label, _ in _USAGE_ATTEMPTS]
    assert len(labels) == len(set(labels)), labels
    for _label, query in _USAGE_ATTEMPTS:
        query.format(**substitutions)


def test_usage_probe_is_read_only():
    """The probe must only ever GET. It exists to learn, not to change anything."""
    import inspect

    from custom_components.kohler_anthem_plus.anthem_plus import client

    source = inspect.getsource(client.KohlerClient.async_probe_usage)
    assert '"GET"' in source
    for verb in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"'):
        assert verb not in source, verb


# --------------------------------------------------------------------------- #
# Monthly water usage, from Kohler's own history endpoint
# --------------------------------------------------------------------------- #
#: A real `gcs-usage` response, trimmed. Captured 2026-09-10 from the owner's Shower Left.
_REAL_USAGE = {
    "deviceId": "gcs-test0001",
    "interval": "Month",
    "gcsUsageDataDetailsList": [
        {"intervalKey": "2025-08", "volume": 1319, "onDuration": 14676},
        {"intervalKey": "2026-08", "volume": 1811, "onDuration": 24371},
        {"intervalKey": "2026-09", "volume": 415, "onDuration": 5575},
    ],
}


def _monthly_sensor(usage, *, units="Standard"):
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    valve = make_valve(get_valve_model("K-28210"), [31, 11, 1])
    valve.usage = usage
    coordinator = make_coordinator([valve])
    coordinator.water_units = units
    return next(
        e for e in collect("sensor", coordinator) if e.name == "Water Used This Month"
    )


def test_monthly_water_converts_litres_to_gallons():
    """`volume` is litres on the wire whatever the account's unit — verified from the app.

    1811 L is August 2026 on the owner's valve, and 478.4 gal is what the Konnect app shows
    for it. Matching the app to the tenth is the whole point of using its exact constant.
    """
    sensor = _monthly_sensor(_REAL_USAGE)
    assert sensor.extra_state_attributes["history"]["2026-08"] == 478.4


def test_monthly_water_leaves_litres_alone_on_a_metric_account():
    sensor = _monthly_sensor(_REAL_USAGE, units="Liters")
    assert sensor.extra_state_attributes["history"]["2026-08"] == 1811.0


def test_monthly_water_matches_the_month_rather_than_taking_the_last_entry():
    """The series can end on a month with no data; position is not identity."""
    from datetime import UTC, datetime

    key = datetime.now(UTC).strftime("%Y-%m")
    usage = {
        "gcsUsageDataDetailsList": [
            {"intervalKey": key, "volume": 100, "onDuration": 600},
            {"intervalKey": "1999-01", "volume": 9999, "onDuration": 60},
        ]
    }
    sensor = _monthly_sensor(usage)
    assert sensor.extra_state_attributes["month"] == key
    assert sensor.native_value == round(100 * 0.264172, 1)
    assert sensor.extra_state_attributes["running_minutes"] == 10.0


def test_monthly_water_is_none_without_a_reading():
    """A failed read and a month with no entry must both be `unknown`, never a stale number."""
    assert _monthly_sensor({}).native_value is None
    assert _monthly_sensor({"gcsUsageDataDetailsList": []}).native_value is None
    assert _monthly_sensor({"gcsUsageDataDetailsList": "nonsense"}).native_value is None
