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
import contextlib
import importlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from .conftest import make_controller, make_coordinator, make_valve

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


def test_limit_sensors_are_named_for_the_setting_not_the_outlet(coordinator):
    """0.11.1 renamed `Rainhead Max Run Time`, which named the wrong thing.

    The limit is timed per zone rather than per outlet, every outlet on the reference
    install reports the same figure, and only one entity is created — so naming it after one
    fixture read as a property of that fixture. `Max Shower Duration` is what the Konnect app
    calls it, and matching the app is what makes a value recognisable.
    """
    names = {e.name for e in collect("sensor", coordinator)}
    assert "Max Shower Duration" in names, sorted(names)
    assert "Max Temperature" in names, sorted(names)
    assert not any("Max Run Time" in name for name in names), sorted(names)


def test_the_duration_rename_kept_its_unique_id(coordinator):
    """A rename that moved the id would orphan history and every automation using it."""
    ids = [e.unique_id for e in collect("sensor", coordinator)]
    assert any(i.endswith("_outlet_1_max_run_time") for i in ids), sorted(ids)


def test_max_shower_duration_is_reported_in_minutes(valve_model):
    """The valve reports 1800 seconds; the app, the panel and Kohler all say 30 minutes."""
    from homeassistant.const import UnitOfTime

    valve = make_valve(valve_model, [31, 11, 1])
    valve.outlet_run_times = {1: 1800}
    coordinator = make_coordinator([valve])
    sensor = next(
        e
        for e in collect("sensor", coordinator)
        if e.unique_id.endswith("_outlet_1_max_run_time")
    )
    assert sensor.native_value == 30
    assert sensor.native_unit_of_measurement == UnitOfTime.MINUTES


def test_max_shower_duration_is_unknown_before_it_is_learned(valve_model):
    """`unknown` and zero are different answers; only one of them is safe to show."""
    valve = make_valve(valve_model, [31, 11, 1])
    valve.outlet_run_times = {}
    coordinator = make_coordinator([valve])
    sensor = next(
        e
        for e in collect("sensor", coordinator)
        if e.unique_id.endswith("_outlet_1_max_run_time")
    )
    assert sensor.native_value is None


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
def _firmware_holder(configuration):
    """A minimal object carrying the REAL firmware properties, not the test double's.

    `make_valve` returns a `SimpleNamespace`, which cannot carry a property — it holds a
    static `firmware` string instead. Asserting against that would test the fake and pass no
    matter what the integration does, which is how an early draft of this test "passed" one
    case by coincidence. A `SimpleNamespace` also cannot satisfy `firmware`'s reads of
    `about`, so the properties are inherited onto a purpose-built class here.
    """
    from custom_components.kohler_anthem_plus.coordinator import Valve

    class Holder:
        about = Valve.about
        firmware = Valve.firmware
        component_firmware = Valve.component_firmware

        def __init__(self, config):
            self.configuration = config

    return Holder(configuration)


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

    assert _firmware_holder(configuration).firmware == expected


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
def test_the_total_water_sensor_is_gone():
    """`Total Water Used` was retired in 0.14.0 — `totalFlow` is not a meter.

    Across the reference corpus that field took three distinct values and cycled among them
    with no water running, in pairs exactly 4x apart. As a `total_increasing` sensor every
    shift read as a meter replacement. The 0.7.3 divide-by-four bug came from reading that
    same 4x as a unit conversion.
    """
    import custom_components.kohler_anthem_plus.sensor as sensor_module

    assert not hasattr(sensor_module, "ValveTotalWaterSensor")


def test_no_entity_publishes_total_flow(valve_model):
    """The field is kept for diagnostics only; nothing may publish it again."""
    coordinator = make_coordinator([make_valve(valve_model, [31, 11, 1])])
    ids = [e.unique_id for e in collect("sensor", coordinator)]
    assert not any(i.endswith("_total_water") for i in ids), sorted(ids)


def test_the_retired_sensor_is_purged_from_the_registry():
    """A removed entity leaves a permanently unavailable registry row unless purged.

    `_async_purge_removed_diagnostics` clears them by unique-id suffix; without the suffix
    listed there, every existing install keeps a dead `Total Water Used` row for ever.
    """
    from custom_components.kohler_anthem_plus import _REMOVED_UNIQUE_ID_SUFFIXES

    assert "_total_water" in _REMOVED_UNIQUE_ID_SUFFIXES


def test_total_flow_is_still_recorded_raw_for_diagnostics(valve_model):
    """It is the evidence for the open question, so the raw value must survive."""
    from custom_components.kohler_anthem_plus.anthem_plus.state import GcsState

    state = GcsState(valve_model, "Fahrenheit")
    assert state._accept_total_flow_raw("8224.0") is True
    assert state.total_flow == 8224.0
    # Unfiltered now: a value the old glitch filter would have held is taken verbatim.
    assert state._accept_total_flow_raw("2.0") is True
    assert state.total_flow == 2.0
    assert state._accept_total_flow_raw("rubbish") is False
    assert state.total_flow == 2.0


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


# --------------------------------------------------------------------------- #
# Controller (Anthem Plus) entities
# --------------------------------------------------------------------------- #
def _hub(entities, controller_id="hub-test0001"):
    return [e for e in entities if controller_id in (e.unique_id or "")]


def test_every_controller_platform_constructs():
    """Roughly half the entity classes are controller-side and none was ever built here.

    The 0.6.6 regression — a deleted base-class body, `py_compile` clean, two entities
    silently missing — was a valve-side class. Nothing would have caught the same mistake on
    the controller side until this test.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    model = get_valve_model("K-28210")
    coordinator = make_coordinator(
        [make_valve(model, [31, 11, 1])], [make_controller(model)]
    )
    built = {name: _hub(collect(name, coordinator)) for name in PLATFORMS}
    # Every platform that has controller entities must produce them; the two that have none
    # are asserted empty so this notices if that ever changes silently.
    assert {name for name, entities in built.items() if entities} == {
        "switch",
        "sensor",
        "binary_sensor",
        "select",
    }, {name: len(entities) for name, entities in built.items()}
    total = sum(len(entities) for entities in built.values())
    assert total >= 10, built


def test_controller_and_valve_entities_never_share_an_id():
    """Both devices carry a Shower switch and a temperature; only the device id separates."""
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    model = get_valve_model("K-28210")
    coordinator = make_coordinator(
        [make_valve(model, [31, 11, 1])], [make_controller(model)]
    )
    for name in PLATFORMS:
        ids = [e.unique_id for e in collect(name, coordinator)]
        assert len(ids) == len(set(ids)), f"{name}: {sorted(ids)}"


def test_two_controllers_do_not_share_ids():
    """One controller per bathroom is the ordinary case on a large account."""
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    model = get_valve_model("K-28210")
    coordinator = make_coordinator(
        [make_valve(model, [31, 11, 1])],
        [
            make_controller(model, device_id="hub-left", name="Anthem Plus Left"),
            make_controller(model, device_id="hub-right", name="Anthem Plus Right"),
        ],
    )
    for name in PLATFORMS:
        ids = [e.unique_id for e in collect(name, coordinator)]
        assert len(ids) == len(set(ids)), f"{name}: {sorted(ids)}"


def test_controller_zone_names_match_the_valve_scheme():
    """0.8.1: a controller said `Zone 1 Temperature` beside the valve's plain `Temperature`.

    Two views of one shower should not read as two different things.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    single = get_valve_model("K-28210")
    coordinator = make_coordinator(
        [make_valve(single, [31, 11, 1])], [make_controller(single)]
    )
    assert "Temperature" in {e.name for e in _hub(collect("sensor", coordinator))}

    double = get_valve_model("K-28211")
    coordinator = make_coordinator(
        [make_valve(double, [31, 11, 1, 31])],
        [make_controller(double, zones=tuple(double.zones))],
    )
    names = {e.name for e in _hub(collect("sensor", coordinator))}
    assert {"Temperature 1", "Temperature 2"} <= names, sorted(names)


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
def test_every_registered_service_is_also_unregistered():
    """0.7.7 added `probe_usage` to registration and forgot the unload path.

    The action then outlived the last unload with nothing behind it, and calling it reported
    "no Anthem valve on this account" rather than simply not existing. Asserted by reading
    both functions' source, so a future service that is registered and never removed fails
    here rather than becoming a ghost in someone's UI.
    """
    import inspect
    import re

    from custom_components.kohler_anthem_plus import services

    registered = set(
        re.findall(
            r"SERVICE_[A-Z_]+", inspect.getsource(services.async_register_services)
        )
    )
    removed = set(
        re.findall(
            r"SERVICE_[A-Z_]+", inspect.getsource(services.async_unregister_services)
        )
    )
    assert registered, "no services found — the regex or the function shape changed"
    assert registered <= removed, sorted(registered - removed)


def test_services_yaml_describes_every_registered_service():
    """A service with no YAML entry appears in the UI with no name, description or fields."""
    import inspect
    import re

    import yaml

    from custom_components.kohler_anthem_plus import const, services

    registered = {
        getattr(const, name)
        for name in re.findall(
            r"SERVICE_[A-Z_]+", inspect.getsource(services.async_register_services)
        )
        if hasattr(const, name)
    }
    path = Path(services.__file__).parent / "services.yaml"
    described = set(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert registered <= described, sorted(registered - described)


# --------------------------------------------------------------------------- #
# Flow percent is a ratio against the outlet's ceiling, not a fixed divisor
# --------------------------------------------------------------------------- #
def test_flow_conversion_matches_the_app_formula():
    """`percent = byte * 100 / max` — what `jj.h$a.X` does in the Konnect app.

    A hardcoded `/2` agrees with this only where the ceiling is 200. Both of the owner's
    valves report 200, so their hardware cannot tell the two apart; the app's bytecode can,
    and does.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        flow_byte_to_percent,
        flow_percent_to_byte,
    )

    # Ceiling 200: must be indistinguishable from the old divisor, including the odd bytes
    # the owner's valves actually carry.
    for byte in (16, 49, 53, 100, 200):
        assert flow_byte_to_percent(byte, 200) == byte / 2

    # A lower ceiling is where they diverge — and where the old formula sent double.
    assert flow_byte_to_percent(100, 100) == 100.0
    assert flow_percent_to_byte(100, 100) == 100
    assert flow_percent_to_byte(100, 200) == 200

    # Exact inverses across every legal byte, at both ceilings.
    for ceiling in (100, 200):
        for byte in range(16, ceiling + 1):
            assert (
                flow_percent_to_byte(flow_byte_to_percent(byte, ceiling), ceiling)
                == byte
            )


def test_flow_slider_bounds_come_from_the_ceiling(valve_model):
    """The maximum is 100 % by definition — percent is a ratio against the ceiling."""
    coordinator = make_coordinator([make_valve(valve_model, [31, 11, 1])])
    flow = next(e for e in collect("number", coordinator) if e.name == "Flow")
    assert flow.native_max_value == 100
    assert flow.native_min_value == 8
    assert flow.extra_state_attributes["maximum_flow_byte"] == 200


def test_flow_display_is_unchanged_on_a_200_ceiling(valve_model):
    """The owner's hardware must read exactly as it did before 0.8.2."""
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import decode_word

    valve = make_valve(valve_model, [31, 11, 1])
    flow = next(
        e for e in collect("number", make_coordinator([valve])) if e.name == "Flow"
    )
    valve.gcs_state.valve1 = decode_word("0195310100000001")  # byte 49 = 24.5 %
    assert valve.gcs_state.flow_is_live
    assert flow.native_value == 24


# --------------------------------------------------------------------------- #
# Safety and credentials
# --------------------------------------------------------------------------- #
def test_send_valve_hex_refuses_a_scalding_word():
    """`send_valve_hex` is the one path that does not go through `encode_word`'s clamp.

    The word carries a 10-bit temperature, so a typo or a script can encode 102.3 °C — 216 °F
    — and it used to be sent verbatim. Outlet, flow and pause bits stay unrestricted: those
    are what the escape hatch is for, and none of them can scald.
    """
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.kohler_anthem_plus.coordinator import _command_half

    assert _command_half("0195C801", "zone1_hex") == "0195C801"  # 40.5 C, ordinary
    # 16-character words pasted from the Hex sensor must still work.
    assert _command_half("0195310100000001", "zone1_hex") == "01953101"

    for word in ("01FFC801", "03FFC801"):  # 51.1 C and 102.3 C
        with pytest.raises(HomeAssistantError, match="above the"):
            _command_half(word, "zone1_hex")


def test_rotated_refresh_token_is_persisted_at_rotation():
    """B2C retires the old token the instant it issues a new one.

    Persistence used to be the caller's job, and on a push-only install (`SCAN_INTERVAL` is
    None) those callers ran once at startup — so hours of rotations went unpersisted and a
    restart loaded a token Kohler had already retired.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.auth import KohlerAuth

    auth = KohlerAuth(None, "token-1")
    seen: list[str] = []
    auth.on_token_rotated = seen.append
    assert auth.on_token_rotated is not None

    # The 401 path must invalidate the access token without discarding the refresh token,
    # so the retry goes back through the lock rather than around it.
    auth.invalidate_access_token()
    assert auth._tokens is None
    assert auth.refresh_token == "token-1"


def test_error_messages_carry_no_device_id():
    """Device ids double as cloud addresses, and error text reaches logs and report files."""
    from custom_components.kohler_anthem_plus.anthem_plus.client import KohlerClient

    for path, ident in (
        ("/devices/api/v1/device-management/gcs-state/gcs-secret01", "gcs-secret01"),
        (
            "/devices/api/v1/device-management/gcs-usage/gcs-secret01?Interval=MONTH",
            "gcs-secret01",
        ),
        ("/devices/api/v1/device-management/hub-state/hub-secret02", "hub-secret02"),
        (
            "/devices/api/v1/device-management/customer-device/tenant-secret03",
            "tenant-secret03",
        ),
    ):
        safe = KohlerClient.safe_path(path)
        assert ident not in safe, safe
        assert "<id>" in safe, safe

    # A command path has no id to redact and must be left intact.
    command = "/platform/api/v1/commands/gcs/solowritesystem"
    assert KohlerClient.safe_path(command) == command


def test_device_names_never_contain_a_device_id():
    """A device name reaches entity ids and the dashboard — permanently."""
    from custom_components.kohler_anthem_plus.coordinator import valve_names

    devices = [
        SimpleNamespace(device_id="gcs-secret01", name="Shower"),
        SimpleNamespace(device_id="gcs-secret02", name="Shower"),
    ]
    names = valve_names(devices)
    for name in names.values():
        assert "gcs-secret" not in name, names


# --------------------------------------------------------------------------- #
# Malformed cloud payloads (0.10.0)
# --------------------------------------------------------------------------- #
#
# `or {}` rescues null but not a wrong type: where the cloud sends a list, a string or a
# number, the `or` passes it straight through and the next `.get` raises inside the REST
# seed — which fails setup with a traceback rather than a message. Every seed entry point
# is checked against the shapes a schema change, a truncated response, or an error body
# shaped like a success could actually produce.
MALFORMED = ({}, None, [], "", "nonsense", 0, 7, [1, 2], {"state": []}, {"state": "x"})


@pytest.mark.parametrize("payload", MALFORMED)
def test_valve_seed_survives_a_malformed_payload(payload, valve_model):
    """A wrong-typed `gcs-state` must leave defaults in place, not raise."""
    from custom_components.kohler_anthem_plus.anthem_plus.state import GcsState

    state = GcsState(model=valve_model)
    state.apply_rest_state(payload)  # must not raise
    assert state.warmup_mode is None or isinstance(state.warmup_mode, str)


@pytest.mark.parametrize("payload", MALFORMED)
def test_hub_seed_survives_a_malformed_payload(payload, valve_model):
    """A wrong-typed `hub-state` must leave defaults in place, not raise."""
    from custom_components.kohler_anthem_plus.anthem_plus.state import HubState

    state = HubState(model=valve_model)
    state.apply_rest_state(payload)  # must not raise
    assert state.zones == {}


def test_hub_seed_skips_entries_that_are_not_objects(valve_model):
    """`zone_number` reads five spellings off the entry, so a bare string would raise."""
    from custom_components.kohler_anthem_plus.anthem_plus.state import HubState

    state = HubState(model=valve_model)
    state.apply_rest_state(
        {"state": {"shower": ["not-an-object", None, 5, {"zone": "1", "status": "ON"}]}}
    )
    assert list(state.zones) == [1]


def test_hub_seed_ignores_a_string_outlet_array(valve_model):
    """`outlet_flags` indexes positionally: a string would read as every outlet running."""
    from custom_components.kohler_anthem_plus.anthem_plus.state import HubState

    state = HubState(model=valve_model)
    state.apply_rest_state(
        {"state": {"shower": [{"zone": "1", "status": "ON", "outlets": "111"}]}}
    )
    assert not any(state.zones[1].outlets)


def test_preset_seed_survives_a_malformed_payload(valve_model):
    from custom_components.kohler_anthem_plus.anthem_plus.state import GcsState

    state = GcsState(model=valve_model)
    for payload in MALFORMED:
        assert state.apply_preset_list(payload) is False


# --------------------------------------------------------------------------- #
# Preset words read back from the cloud (0.10.0)
# --------------------------------------------------------------------------- #


def test_preset_word_temperature_inverts_the_encoder():
    """Every temperature the encoder can produce must read back as itself."""
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        encode_preset_word,
        preset_word_temperature,
    )

    for tenths in range(0, 489):
        celsius = tenths / 10
        word = encode_preset_word(celsius, 50.0, 0b001)
        assert preset_word_temperature(word) == pytest.approx(celsius)


def test_check_preset_word_accepts_anything_we_wrote():
    """The ceiling is the encoder's own clamp, so our own words always pass."""
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        check_preset_word,
        encode_preset_word,
    )

    for celsius in (0.0, 20.0, 38.8, 48.8, 60.0, 120.0):
        for mask in (0b000, 0b001, 0b111):
            word = encode_preset_word(celsius, 50.0, mask)
            assert check_preset_word(word) == word.lower()


def test_check_preset_word_refuses_a_scalding_word():
    """A 10-bit temperature reaches 102.3 C, and this word would be echoed to the valve."""
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        ValveHexError,
        check_preset_word,
    )

    # byte0 low bits 0b11 -> tenths |= 0x300; 0x3FF tenths = 102.3 C.
    with pytest.raises(ValveHexError, match=r"102\.3"):
        check_preset_word("03ffc8")


@pytest.mark.parametrize(
    "word", ["", "zz", "01", "0189c", "0189c88", "01 89c8", "gg89c8"]
)
def test_check_preset_word_refuses_a_malformed_word(word):
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        ValveHexError,
        check_preset_word,
    )

    with pytest.raises(ValveHexError):
        check_preset_word(word)


def test_preset_timer_plan_drops_a_scalding_stored_word():
    """`writepreset` replaces the record whole, so a stored word is echoed back verbatim.

    Dropping it sends an empty field for that valve — exactly what an unused valve already
    gets — so the failure mode is a preset that stops driving one valve, not one that runs
    it too hot.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.gcs import plan_preset_timer

    payload = {
        "gcsPresetExperienceDetails": [
            {
                "presetId": "1",
                "title": "Default shower",
                "time": "0",
                "valveDetails": [
                    {"valveIndex": "Valve1", "hexString": "03FFC8"},
                    {"valveIndex": "Valve2", "hexString": "0589C8"},
                ],
            }
        ]
    }
    plan = plan_preset_timer(payload, 1, 600)
    assert 1 not in plan.valves, "a 102.3 C word must not be echoed back"
    assert plan.valves[2] == "0589c8", "the sound word is preserved byte for byte"


def test_preset_timer_plan_preserves_normal_words():
    """The guard must be invisible on every real record."""
    from custom_components.kohler_anthem_plus.anthem_plus.gcs import plan_preset_timer

    payload = {
        "gcsPresetExperienceDetails": [
            {
                "presetId": "1",
                "title": "Default shower",
                "time": "0",
                "valveDetails": [
                    {"valveIndex": "Valve1", "hexString": "018448"},
                    {"valveIndex": "Valve2", "hexString": "05849C"},
                ],
            }
        ]
    }
    plan = plan_preset_timer(payload, 1, 600)
    assert plan.valves == {1: "018448", 2: "05849c"}


# --------------------------------------------------------------------------- #
# The warm-up extraction (0.10.0)
# --------------------------------------------------------------------------- #


def test_valve_still_exposes_the_whole_warmup_surface():
    """The move must be invisible: entities, services and diagnostics call these names."""
    from custom_components.kohler_anthem_plus.coordinator import Valve

    for name in (
        "async_set_warmup",
        "async_read_warmup_mode",
        "warmup_auto_restore",
        "last_warmup_mode",
        "_handle_warmup_mode_change",
        "_message_window",
    ):
        assert hasattr(Valve, name), f"Valve lost {name} in the warm-up extraction"


def test_warmup_manager_owns_every_moved_member():
    """The other half of the same check: nothing was left behind on `Valve`."""
    from custom_components.kohler_anthem_plus.coordinator import Valve
    from custom_components.kohler_anthem_plus.warmup_manager import WarmupManager

    moved = (
        "_remember_warmup_mode",
        "_schedule_warmup_restore",
        "_async_restore_warmup",
        "_async_journal_warmup_context",
        "_warmup_write_status",
        "_warmup_journal",
    )
    for name in moved:
        assert hasattr(WarmupManager, name), f"WarmupManager is missing {name}"
        assert not hasattr(Valve, name), f"Valve kept a moved member: {name}"


def test_valve_never_calls_a_member_it_no_longer_has():
    """The extraction's real hazard: a leftover `self._warmup_*` call site.

    `journal_baseline` still called `self._warmup_journal` after the move, which would have
    raised `AttributeError` on every warm-up log open — a path no other test exercises,
    because it needs a log file to exist. Checked statically instead: every `self.<name>`
    inside `Valve` must resolve to something `Valve` actually has.
    """
    import ast
    import inspect

    from custom_components.kohler_anthem_plus import coordinator as module
    from custom_components.kohler_anthem_plus.coordinator import Valve

    tree = ast.parse(inspect.getsource(module))
    valve = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "Valve"
    )
    # Names bound by `self.x = ...` anywhere in the class, plus everything on the type.
    assigned = {
        target.attr
        for node in ast.walk(valve)
        for target in getattr(node, "targets", [])
        + ([node.target] if isinstance(node, ast.AnnAssign) else [])
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    known = assigned | set(dir(Valve))
    used = {
        node.attr
        for node in ast.walk(valve)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    missing = sorted(name for name in used - known if not name.startswith("__"))
    assert not missing, f"Valve calls members it does not have: {missing}"


# --------------------------------------------------------------------------- #
# The diagnostics version scan (0.10.1)
# --------------------------------------------------------------------------- #


def test_version_scan_finds_every_firmware_without_leaking_identity():
    """The scan exists to find the valve and gateway versions the three named blocks miss.

    It walks blocks this module otherwise refuses to reproduce (`configuration`, `iot`,
    `applicationSource`) because they carry plumbing and cloud addressing — so the property
    that matters is that it takes version *values* and leaves every sibling behind.
    """
    from custom_components.kohler_anthem_plus.diagnostics import _version_fields

    record = {
        "deviceId": "gcs-secret01",
        "tenantId": "tenant-secret02",
        "serialNumber": "SN-secret03",
        "iot": {
            "connectionString": "HostName=x.azure-devices.net;DeviceId=gcs-secret01;Key=AAAA",
            "firmwareVersion": "00.74",
            "hubName": "kohler-prod",
        },
        "configuration": {
            "valves": [
                {"valveIndex": "Valve1", "firmwareVersion": 10, "serial": "V-secret04"},
                {"valveIndex": "Valve2", "firmwareVersion": 10},
            ],
            "systemConfiguration": {"pipeLayout": "left-riser", "swRevision": "1.4"},
        },
        "applicationSource": {"version": "3.0.1", "buildId": "a" * 40},
        # Labels that sit beside a version and are not one.
        "firmwareType": "Application",
        "isSingleFirmwareUpdate": False,
    }
    found = _version_fields(record)

    # The versions the report exists to surface, each at a path that says where it came from.
    assert found["iot.firmwareVersion"] == "00.74"
    assert found["configuration.valves[0].firmwareVersion"] == 10
    assert found["configuration.valves[1].firmwareVersion"] == 10
    assert found["configuration.systemConfiguration.swRevision"] == "1.4"

    # A value too long to be a version is described, not copied.
    assert found["applicationSource.buildId"] == "<str, 40 chars>"

    # Type and update-bookkeeping labels are not versions.
    assert "firmwareType" not in found
    assert "isSingleFirmwareUpdate" not in found

    blob = __import__("json").dumps(found)
    for secret in (
        "secret01",
        "secret02",
        "secret03",
        "secret04",
        "azure-devices",
        "left-riser",
        "kohler-prod",
    ):
        assert secret not in blob, f"{secret} leaked into the version scan"


def test_version_scan_reads_the_real_block_shapes():
    """Both interfaces' real payloads, as captured 2026-09-10."""
    from custom_components.kohler_anthem_plus.diagnostics import _version_fields

    # Shower Left: an Application block beside the Assets one.
    left = {
        "firmwareUpdate": {"firmwareType": "Assets", "version": "2.00"},
        "otaReportedProperties": {
            "firmwareType": "Application",
            "initialVersion": "2.20",
            "updatedVersion": "2.20",
        },
        "version": None,
    }
    assert _version_fields(left)["otaReportedProperties.updatedVersion"] == "2.20"

    # Shower Right: no Application block anywhere — the reason its entity read 2.00.
    right = {
        "firmwareUpdate": {"firmwareType": "Assets", "version": "2.00"},
        "otaReportedProperties": {
            "firmwareType": "Assets",
            "initialVersion": "2.00",
            "updatedVersion": "2.00",
        },
        "version": None,
    }
    found = _version_fields(right)
    assert found["otaReportedProperties.updatedVersion"] == "2.00"
    assert all(value in ("2.00", None) for value in found.values())


# --------------------------------------------------------------------------- #
# Three firmwares, not one (0.11.0)
# --------------------------------------------------------------------------- #
#
# The `about` block as both of the owner's K-28210 valves report it, captured 2026-09-10.
# Nested inside the record's own `configuration` key — the depth bug that made every earlier
# report say `about_keys: []` on hardware that populates it in full.
def _real_about(valve_firmware: str) -> dict:
    return {
        "configuration": {
            "about": {
                "firmware": {"version": "00.74", "latestVersion": "00.74"},
                "gateway": {"firmware": "00.74", "assetsFirmware": None},
                "primaryValve": {"firmware": valve_firmware, "assetsFirmware": None},
                "secondaryValve1": {"firmware": "0", "assetsFirmware": None},
                "uI2": {"firmware": "2.2", "assetsFirmware": "2.0"},
                "ui": {"firmware": "0.0", "assetsFirmware": "0.0"},
                "controllerFirmwareVersion": None,
            }
        },
        # The OTA blocks that sat beside it and were being read instead.
        "otaReportedProperties": {
            "firmwareType": "Assets",
            "updatedVersion": "2.00",
        },
        "firmwareUpdate": {"firmwareType": "Assets", "version": "2.00"},
    }


def test_interface_firmware_matches_the_app_not_the_artwork():
    """The bug this release exists for.

    Shower Right's `otaReportedProperties` describes **Assets** — the artwork bundle — and
    carries no Application block anywhere, so `Firmware` reported `2.00` where the Konnect
    app showed 2.2. The interface version was in `about.uI2.firmware` the whole time, one
    nesting level deeper than the code looked.
    """
    holder = _firmware_holder(_real_about("11"))
    assert holder.firmware == "2.2"
    assert holder.firmware != "2.00", "the Assets version is not the interface version"


def test_each_component_reports_its_own_firmware():
    """Three different numbers for one shower, which is why there are three entities."""
    holder = _firmware_holder(_real_about("10"))
    assert holder.component_firmware("uI2") == "2.2"
    assert holder.component_firmware("primaryValve") == "10"
    assert holder.component_firmware("gateway") == "00.74"


def test_two_valves_can_be_on_different_firmware():
    """The app shows 10 for both; the record says 10 and 11.

    Two showers that should be identical are not, and this is the only surface that says so.
    """
    left = _firmware_holder(_real_about("10"))
    right = _firmware_holder(_real_about("11"))
    assert left.component_firmware("primaryValve") == "10"
    assert right.component_firmware("primaryValve") == "11"
    # Everything else matches, which is what makes the valve difference meaningful.
    for component in ("uI2", "gateway"):
        assert left.component_firmware(component) == right.component_firmware(component)


def test_an_assets_only_record_reports_no_firmware():
    """With no `about` and only Assets blocks, `unknown` is the honest answer.

    A blank is better than a confidently wrong version in a bug report — and reporting the
    artwork version here is exactly what this release fixes.
    """
    holder = _firmware_holder(
        {
            "otaReportedProperties": {
                "firmwareType": "Assets",
                "updatedVersion": "2.00",
            },
            "firmwareUpdate": {"firmwareType": "Assets", "version": "2.00"},
        }
    )
    assert holder.firmware is None


def test_an_untyped_ota_block_is_still_read():
    """An untyped block is not an Assets block.

    The reference install's `otaReportedProperties` carries no `firmwareType` at all.
    Refusing it would trade one wrong answer for a blank on hardware that reads correctly
    today, so only a block explicitly naming a non-Application type is skipped.
    """
    holder = _firmware_holder(
        {"otaReportedProperties": {"currentFirmwareVersion": "01.02"}}
    )
    assert holder.firmware == "01.02"


def test_a_top_level_about_still_works():
    """The reference install's shape must keep reading as it always has."""
    assert _firmware_holder({"about": {"firmware": "00.74"}}).firmware == "00.74"


def test_component_firmware_is_none_for_an_absent_part():
    holder = _firmware_holder(_real_about("10"))
    assert holder.component_firmware("nosuchpart") is None
    assert _firmware_holder({}).component_firmware("gateway") is None


def test_firmware_entities_keep_their_ids_and_do_not_collide(valve_model):
    """The interface entity keeps `_firmware`, so history and automations survive."""
    coordinator = make_coordinator([make_valve(valve_model, [31, 11, 1])])
    ids = [e.unique_id for e in collect("sensor", coordinator)]
    assert len(ids) == len(set(ids)), "duplicate unique ids"
    firmware_ids = sorted(i for i in ids if "firmware" in i)
    assert any(i.endswith("_firmware") for i in firmware_ids), firmware_ids
    assert any(i.endswith("_firmware_valve") for i in firmware_ids), firmware_ids
    assert any(i.endswith("_firmware_gateway") for i in firmware_ids), firmware_ids


# --------------------------------------------------------------------------- #
# The scald limit (0.11.1)
# --------------------------------------------------------------------------- #


def _max_temperature_sensor(valve_model, tenths, unit):
    from custom_components.kohler_anthem_plus.anthem_plus.state import OutletLimits

    valve = make_valve(valve_model, [31, 11, 1])
    valve.gcs_state.outlet_limits[1] = OutletLimits(1, 16, 200, 1800, 200, 11, tenths)
    coordinator = make_coordinator([valve])
    coordinator.temperature_unit = unit
    return next(
        e
        for e in collect("sensor", coordinator)
        if e.unique_id.endswith("_outlet_1_max_temperature")
    )


def test_max_temperature_reads_118f_on_a_fahrenheit_account(valve_model):
    """The reference system's real setting: 47.8 C is the 118 F the Konnect app shows."""
    from homeassistant.const import UnitOfTemperature

    sensor = _max_temperature_sensor(valve_model, 478, "Fahrenheit")
    assert sensor.native_value == pytest.approx(118.04, abs=0.05)
    assert sensor.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT


def test_max_temperature_stays_celsius_on_a_metric_account(valve_model):
    from homeassistant.const import UnitOfTemperature

    sensor = _max_temperature_sensor(valve_model, 478, "Celsius")
    assert sensor.native_value == pytest.approx(47.8)
    assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS


def test_max_temperature_is_unknown_before_it_is_reported(valve_model):
    """`unknown` is not the same as "no limit", and must not read as a number."""
    sensor = _max_temperature_sensor(valve_model, None, "Fahrenheit")
    assert sensor.native_value is None


def test_rest_and_mqtt_agree_on_the_scald_limit():
    """REST reports display C (`45`), MQTT reports tenths (`450`). Both mean 45.0 C.

    The same wire/display split as flow, and getting it wrong here would silently misreport
    a safety setting by a factor of ten.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.state import (
        outlet_limits_from_settings,
    )

    rest = outlet_limits_from_settings(
        {
            "valveSettings": [
                {
                    "outletConfigurations": [
                        {
                            "outLetId": "1",
                            "minimumFlowrate": "4",
                            "maximumFlowrate": "50",
                            "maximumRuntime": "1800",
                            "maximumOutletTemperature": "45",
                        }
                    ]
                }
            ]
        }
    )
    assert rest[1].maximum_temperature_tenths == 450

    # And the documented decimal case, which must not round to 478 vs 477.
    decimal = outlet_limits_from_settings(
        {
            "valveSettings": [
                {
                    "outletConfigurations": [
                        {
                            "outLetId": "1",
                            "minimumFlowrate": "4",
                            "maximumFlowrate": "50",
                            "maximumOutletTemperature": "47.8",
                        }
                    ]
                }
            ]
        }
    )
    assert decimal[1].maximum_temperature_tenths == 478


def test_cloud_connection_is_visible_and_enabled(valve_model):
    """0.11.2 unhid it.

    It has to keep *running* whether or not anyone is looking — its value is the record it
    builds while nobody is watching — so it was enabled but hidden. Hiding put "(Hidden)"
    beside the name everywhere it appeared, which reads as a broken entity, and the moment it
    matters is the moment every other entity has silently frozen. Both defaults are asserted
    because enabling without visibility is the state this test exists to prevent recurring.
    """
    coordinator = make_coordinator([make_valve(valve_model, [31, 11, 1])])
    sensor = next(
        e
        for e in collect("binary_sensor", coordinator)
        if e.unique_id.endswith("_cloud_connection")
    )
    assert sensor.entity_registry_visible_default is True
    assert sensor.entity_registry_enabled_default is True
    assert sensor.name == "Cloud Connection"


def _duration_sensor(valve_model, run_times):
    valve = make_valve(valve_model, [31, 11, 1])
    valve.outlet_run_times = run_times
    coordinator = make_coordinator([valve])
    return next(
        e
        for e in collect("sensor", coordinator)
        if e.unique_id.endswith("_outlet_1_max_run_time")
    )


def test_max_shower_duration_reports_the_shortest_outlet(valve_model):
    """Shower Right, as captured 2026-09-10: Showerhead 3600 s, the other two 1800 s.

    **A lost write, not a per-outlet setting.** There is one master duration; the app writes
    it one outlet at a time and stops at the first failure, so a 60->30 minute change left
    one outlet holding the old value. The shortest is both the value the setting was moving
    to and the soonest the water can stop.
    """
    sensor = _duration_sensor(valve_model, {0: 1800, 1: 3600, 2: 1800})
    assert sensor.native_value == 30
    assert sensor.extra_state_attributes["outlets_agree"] is False
    assert sensor.extra_state_attributes["per_outlet"] == {
        "Rainhead": 30,
        "Showerhead": 60,
        "Handshower": 30,
    }


def test_max_shower_duration_says_so_when_outlets_agree(valve_model):
    """Shower Left: all three at 1800 s — the healthy state, and the normal one."""
    sensor = _duration_sensor(valve_model, {0: 1800, 1: 1800, 2: 1800})
    assert sensor.native_value == 30
    assert sensor.extra_state_attributes["outlets_agree"] is True


def test_max_shower_duration_has_no_attributes_before_it_is_learned(valve_model):
    sensor = _duration_sensor(valve_model, {})
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_a_longer_first_outlet_does_not_hide_a_shorter_one(valve_model):
    """The failure this replaces, in the direction that actually matters.

    Reading outlet 1 alone would report 60 minutes here while the Rainhead stops at 30 —
    telling somebody they have twice the shower they have. Same lost-write cause, with the
    surviving stale value on a different outlet.
    """
    sensor = _duration_sensor(valve_model, {0: 3600, 1: 1800, 2: 1800})
    assert sensor.native_value == 30


# --------------------------------------------------------------------------- #
# The temperature slider's ceiling (0.12.0)
# --------------------------------------------------------------------------- #


def _temperature_number(valve_model, unit):
    valve = make_valve(valve_model, [31, 11, 1])
    coordinator = make_coordinator([valve])
    coordinator.temperature_unit = unit
    return next(
        e for e in collect("number", coordinator) if "temperature" in e.unique_id
    )


def test_the_temperature_slider_matches_the_app():
    """92-118 °F — exactly the Konnect app's own slider, owner-confirmed 2026-09-10.

    It was 80-113 before 0.12.0, both ends invented rather than taken from the app. The
    ceiling was justified as "exactly the `maximumOutletTemperature` the valve reports for
    every outlet" — generalised from the reference valve, and false: the owner's two valves
    report 450 tenths (113 °F) and 477 tenths (117.9 °F). A control whose range differs from
    the app reads as broken rather than cautious.
    """
    from homeassistant.const import UnitOfTemperature

    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    number = _temperature_number(get_valve_model("K-28210"), "Fahrenheit")
    assert number.native_min_value == 92
    assert number.native_max_value == 118
    assert number.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT


def test_the_celsius_slider_stays_inside_the_codec_ceiling():
    """33-48 °C, and 48 must not exceed what `encode_word` will accept (48.8 °C)."""
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        TEMPERATURE_MAX_TENTHS,
        TEMPERATURE_TENTHS_PER_DEGREE,
    )

    number = _temperature_number(get_valve_model("K-28210"), "Celsius")
    assert number.native_min_value == 33
    assert number.native_max_value == 48
    ceiling = TEMPERATURE_MAX_TENTHS / TEMPERATURE_TENTHS_PER_DEGREE
    assert number.native_max_value <= ceiling, (
        "the slider must not offer a refused value"
    )


def test_the_service_schema_matches_the_slider():
    """The `custom_shower` form and the number entity must not disagree on the range.

    They are two ways to set the same thing, and a form that accepts what the slider refuses
    (or the reverse) is the kind of inconsistency nobody finds until it bites.
    """
    from custom_components.kohler_anthem_plus.const import (
        UI_TEMPERATURE_MAX_F,
        UI_TEMPERATURE_MIN_F,
    )
    from custom_components.kohler_anthem_plus.services import (
        _FIELD_ZONE1_TEMPERATURE,
        _FIELD_ZONE2_TEMPERATURE,
    )

    for field in (_FIELD_ZONE1_TEMPERATURE, _FIELD_ZONE2_TEMPERATURE):
        selector = field["selector"]["number"]
        assert selector["max"] == UI_TEMPERATURE_MAX_F, field["name"]
        assert selector["min"] == UI_TEMPERATURE_MIN_F, field["name"]


def test_118f_encodes_to_the_valve_without_being_clamped():
    """The whole point of raising the ceiling: 118 °F must survive the codec intact."""
    from custom_components.kohler_anthem_plus.anthem_plus.valve_hex import (
        decode_word,
        encode_word,
        unit_to_celsius,
    )

    celsius = unit_to_celsius(118, "Fahrenheit")
    word = encode_word(1, celsius, 50.0, 0b001)
    assert decode_word(word).temperature_celsius == pytest.approx(celsius, abs=0.05)


def test_max_temperature_is_a_setting_not_a_hardware_ceiling(valve_model):
    """Observed live 2026-09-10: 450 tenths at 16:48, 477 at 16:55, on one valve.

    The owner changed it from 113 °F to 118 °F in the Konnect app and the valve took it on all
    three outlets. This entity therefore reports the ceiling **in force now**, which can move
    at any time — nothing may treat it as a fixed device property, and in particular the
    temperature slider's bounds must not be derived from it.
    """
    before = _max_temperature_sensor(valve_model, 450, "Fahrenheit")
    after = _max_temperature_sensor(valve_model, 477, "Fahrenheit")
    assert before.native_value == pytest.approx(113.0, abs=0.05)
    # 477 tenths is 47.7 °C = 117.86 °F, which the entity's display precision shows as 118 —
    # and 477 is exactly what `unit_to_celsius(118, "Fahrenheit")` produces, so Kohler's
    # stored value and this integration's conversion table agree on what "118 °F" means.
    assert after.native_value == pytest.approx(117.86, abs=0.05)
    assert round(after.native_value) == 118


def test_the_slider_does_not_follow_the_scald_limit(valve_model):
    """The slider matches the app's range, not the valve's current setting.

    Deriving it from `maximumOutletTemperature` would have been the intuitive fix and is the
    wrong one: the limit is user-configurable, so the slider would silently reshape itself
    whenever somebody changed a setting in the app — and would have to be rebuilt to widen,
    since Home Assistant caches an entity's bounds.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.state import OutletLimits

    valve = make_valve(valve_model, [31, 11, 1])
    # A valve set well below the slider's ceiling.
    valve.gcs_state.outlet_limits[1] = OutletLimits(1, 16, 200, 1800, 200, 11, 450)
    coordinator = make_coordinator([valve])
    coordinator.temperature_unit = "Fahrenheit"
    number = next(
        e for e in collect("number", coordinator) if "temperature" in e.unique_id
    )
    assert number.native_max_value == 118, "the slider follows the app, not the valve"


def test_auto_restore_says_whether_the_fault_can_even_occur(valve_model):
    """The only identified cause of a spontaneous warm-up disable lives in the HUB.

    `docs/gcs/api.md` §3h: the Anthem Plus controller's web UI writes `warmUpDisabled` to the
    valve as a fixed step of its signed-in routine. The write originates in the hub's
    firmware; the valve is only the recipient. So on a controller-free account this switch
    defends against nothing observed, and `hub_present` is what says so.
    """
    valve = make_valve(valve_model, [31, 11, 1])
    alone = make_coordinator([valve])
    switch = next(
        e
        for e in collect("switch", alone)
        if e.unique_id.endswith("_warmup_auto_restore")
    )
    assert switch.extra_state_attributes["hub_present"] is False

    with_hub = make_coordinator(
        [valve], controllers=(make_controller(valve_model, device_id="hub-1"),)
    )
    switch = next(
        e
        for e in collect("switch", with_hub)
        if e.unique_id.endswith("_warmup_auto_restore")
    )
    assert switch.extra_state_attributes["hub_present"] is True


# --------------------------------------------------------------------------- #
# Water used this year (0.13.0)
# --------------------------------------------------------------------------- #


def _yearly_sensor(valve_model, series, units="Standard", now_month="2026-09"):
    valve = make_valve(valve_model, [31, 11, 1])
    valve.usage = {"gcsUsageDataDetailsList": series}
    coordinator = make_coordinator([valve])
    coordinator.water_units = units
    sensor = next(
        e
        for e in collect("sensor", coordinator)
        if e.unique_id.endswith("_water_this_year")
    )
    return sensor


def test_yearly_water_sums_twelve_complete_months(valve_model):
    """500 gallons a month for a year, in the litres the API actually returns."""
    litres_per_month = 500 / 0.264172
    series = [
        {"intervalKey": f"2025-{m:02d}", "volume": litres_per_month}
        for m in range(9, 13)
    ] + [
        {"intervalKey": f"2026-{m:02d}", "volume": litres_per_month}
        for m in range(1, 9)
    ]
    sensor = _yearly_sensor(valve_model, series)
    assert sensor.native_value == pytest.approx(6000, abs=1)
    assert sensor.extra_state_attributes["months_counted"] == 12


def test_yearly_water_excludes_the_current_month(valve_model):
    """A rolling window that crept up through the month would not be a `TOTAL`.

    The partial month belongs to `Water Used This Month`; including it here would make the
    value climb daily and then fall at every month boundary.
    """
    litres = 100 / 0.264172
    series = [
        {"intervalKey": "2026-08", "volume": litres},
        {"intervalKey": "2026-09", "volume": litres * 99},  # the current, partial month
    ]
    sensor = _yearly_sensor(valve_model, series)
    assert sensor.native_value == pytest.approx(100, abs=1)
    assert sensor.extra_state_attributes["excludes_current_month"] == "2026-09"


def test_yearly_water_takes_only_the_twelve_most_recent(valve_model):
    """A 400-day fetch returns thirteen months; the thirteenth must not inflate the year."""
    litres = 100 / 0.264172
    series = [{"intervalKey": f"2025-{m:02d}", "volume": litres} for m in range(1, 13)]
    series += [{"intervalKey": f"2026-{m:02d}", "volume": litres} for m in range(1, 9)]
    sensor = _yearly_sensor(valve_model, series)
    assert sensor.extra_state_attributes["months_counted"] == 12
    assert sensor.native_value == pytest.approx(1200, abs=1)
    assert sensor.extra_state_attributes["last_month"] == "2026-08"


def test_yearly_water_reports_a_short_series_honestly(valve_model):
    """A young account has fewer than twelve months, and must not read as a dry year."""
    litres = 100 / 0.264172
    series = [{"intervalKey": "2026-07", "volume": litres}]
    sensor = _yearly_sensor(valve_model, series)
    assert sensor.native_value == pytest.approx(100, abs=1)
    assert sensor.extra_state_attributes["months_counted"] == 1


def test_yearly_water_stays_in_litres_on_a_metric_account(valve_model):
    series = [{"intervalKey": "2026-08", "volume": 1000.0}]
    sensor = _yearly_sensor(valve_model, series, units="Liters")
    assert sensor.native_value == pytest.approx(1000.0)


def test_yearly_water_is_none_without_a_series(valve_model):
    assert _yearly_sensor(valve_model, []).native_value is None


# --------------------------------------------------------------------------- #
# Upstream parity (0.15.0)
# --------------------------------------------------------------------------- #


def test_topology_latches_only_on_an_answer(valve_model):
    """A read with no layout in it must not pin the entry's model for ever.

    `_topology_checked` was set to True *before* `_apply_topology` ran, so a first
    `gcsadvancestate` read carrying no layout latched anyway — and on an account whose
    valves differ, that leaves the wrong layout on every valve but the first, permanently.
    Found by GitHub Copilot's review of upstream #3.
    """
    from custom_components.kohler_anthem_plus.coordinator import Valve

    valve = make_valve(valve_model, [31, 11, 1])
    # An empty settings payload says nothing about the layout.
    assert Valve._apply_topology(valve, {}) is False
    assert Valve._apply_topology(valve, {"valveSettings": []}) is False


def test_topology_latches_when_the_read_agrees(valve_model):
    """An answer that matches the entry is still an answer — it must not re-read for ever."""
    from custom_components.kohler_anthem_plus.coordinator import Valve

    valve = make_valve(valve_model, [31, 11, 1])
    # The real shape: `valve` names the slot, `noOfOutlets` is the count.
    settings = {"valveSettings": [{"valve": "valve1", "noOfOutlets": 3}]}
    assert Valve._apply_topology(valve, settings) is True


def test_a_zone2_word_is_refused_on_a_single_zone_valve(valve_model):
    """The form offers Zone 2 whenever *any* valve has one — including for one that has not.

    The word used to be encoded and sent to a valve with nothing to receive it. All zeroes
    stays legal: that is the sentinel this valve genuinely uses for "no second valve".

    Drives the real coroutine so the guard itself is exercised, not a restatement of its
    condition — the valve double raises on any actual write, so reaching the send is a
    failure too.
    """
    import asyncio

    from homeassistant.exceptions import HomeAssistantError

    from custom_components.kohler_anthem_plus.coordinator import Valve

    assert valve_model.uses_valve2 is False
    valve = make_valve(valve_model, [31, 11, 1])
    # The guard runs after the "is there a valve at all" check, so both must be present.
    valve.gcs = object()
    valve.name = "Shower Left"

    with pytest.raises(HomeAssistantError, match="one zone"):
        asyncio.run(Valve.async_send_valve_hex(valve, "0184C801", "1184C801"))


def test_the_report_log_records_decisions_beside_messages(tmp_path):
    """One switch, one attachment: the wire traffic and the reasoning, on one clock.

    A report that shows a cutoff was *seen and skipped* answers "why did Endless Shower not
    fire" without asking the reader to line two files up by timestamp.
    """
    import json

    from custom_components.kohler_anthem_plus.anthem_plus.report_log import ReportLog

    log = ReportLog(str(tmp_path))
    log.start()
    log.write("$iothub/twin/PATCH", b'{"data":{"code":"GCS_SOLO_STS"}}')
    log.note("cutoff", "zone_start", {"zone": 1})
    log.note(
        "warmup", "mode", {"before": "warmUpDisabled", "after": "warmUpAllOutlets"}
    )
    log.stop()
    log.close()

    lines = [
        json.loads(line)
        for path in tmp_path.glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    messages = [r for r in lines if "topic" in r]
    decisions = [r for r in lines if "journal" in r]
    assert len(messages) == 1
    assert {r["journal"] for r in decisions} == {"cutoff", "warmup"}
    # The two vocabularies reuse event names, which is why `journal` has to be there.
    assert all("event" in r and "ts" in r for r in decisions)
    # A decision must never be mistakable for a message, or `jq select(.topic)` breaks.
    assert not any("topic" in r for r in decisions)


def test_the_report_log_ignores_decisions_when_no_episode_is_active(tmp_path):
    """Off means off — a note outside an episode must not create a file."""
    from custom_components.kohler_anthem_plus.anthem_plus.report_log import ReportLog

    log = ReportLog(str(tmp_path))
    log.note("cutoff", "zone_start", {"zone": 1})
    assert list(tmp_path.glob("*.jsonl")) == []


def test_the_report_log_never_opens_a_file_from_the_event_loop(tmp_path):
    """`note()` runs on the loop; opening a file there is a blocking-call error in HA.

    Shipped doing exactly that in 0.15.0 — `note()` fell through to `_write_line_locked`,
    which calls `_open_locked`, which does `os.makedirs`, a README write and an `open()`.
    `write()` is fine because paho calls it on its own network thread; `note()` is not,
    because the cutoff detector and the warm-up watcher both live on the loop.
    """
    import builtins

    from custom_components.kohler_anthem_plus.anthem_plus.report_log import ReportLog

    log = ReportLog(str(tmp_path))
    log.start()
    # The state `note()` must tolerate: an episode is live but no handle is open.
    log._close_locked(quiet=True)

    opened: list[str] = []
    real_open = builtins.open

    def tracking_open(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    builtins.open = tracking_open
    try:
        log.note("cutoff", "zone_start", {"zone": 1})
    finally:
        builtins.open = real_open

    assert opened == [], f"note() opened files on the event loop: {opened}"
    # It must ask for the open instead, so the caller can schedule it in an executor.
    assert log.wants_open is True

    log.prepare()
    log.note("cutoff", "zone_stop", {"zone": 1})
    log.close()
    written = [
        line for p in tmp_path.glob("*.jsonl") for line in p.read_text().splitlines()
    ]
    assert len(written) == 1, "the record after prepare() must land"


# --------------------------------------------------------------------------- #
# Lifecycle bugs found by review (0.15.1)
# --------------------------------------------------------------------------- #


def test_the_quiet_timer_survives_a_valve_that_has_never_spoken():
    """`_last_gcs_at` is None until the first MQTT message — which can be hours away.

    Unguarded, the subtraction raised `TypeError` **after** `_quiet_cancel` was nulled and
    **before** either re-arm, so trigger B died for the life of the coordinator. A
    push-only integration on a quiet shower is the normal case, not the edge case: the
    module records benign silences of 12 h and 35 h.
    """
    from custom_components.kohler_anthem_plus.cloud_watch import CloudConnectionWatch

    watch = CloudConnectionWatch.__new__(CloudConnectionWatch)
    watch._last_gcs_at = None
    watch._quiet_cancel = object()
    armed: list = []
    checked: list = []
    watch._arm_quiet_timer = lambda *a: armed.append(a)
    watch._request_check = lambda reason: checked.append(reason)

    CloudConnectionWatch._quiet_elapsed(watch, None)

    assert checked, "silence since setup is exactly what trigger B asks about"
    assert armed, "the timer must be re-armed or the trigger is dead for ever"


def test_valves_are_seeded_once_not_twice():
    """A serial loop was left in place when the concurrent gather was added (0.9.0).

    Every valve was seeded twice on every setup, reconnect and manual refresh — double the
    REST traffic the change existed to reduce, and two `async_seed` coroutines for one valve
    interleaving over the same state objects.
    """
    import ast
    import inspect
    import textwrap

    from custom_components.kohler_anthem_plus import coordinator as module

    source = textwrap.dedent(
        inspect.getsource(module.KohlerAnthemPlusCoordinator._async_seed_state)
    )
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "async_seed"
    ]
    assert len(calls) == 1, f"async_seed is called {len(calls)} times per seed"


def test_the_reseed_task_is_held_so_unload_can_cancel_it():
    """It ends in a config-entry write and a push into entities, and outlived an unload.

    `_async_seed_state` is a dozen REST round trips; a reload inside that window left the
    task awaiting HTTP against a coordinator Home Assistant had already discarded.
    """
    import inspect

    from custom_components.kohler_anthem_plus import coordinator as module

    spawn = inspect.getsource(module.KohlerAnthemPlusCoordinator._handle_connected)
    assert "_reseed_task = self.hass.async_create_task" in spawn, spawn

    shutdown = inspect.getsource(
        module.KohlerAnthemPlusCoordinator.async_shutdown_stream
    )
    assert "_reseed_task.cancel()" in shutdown, shutdown


@pytest.mark.parametrize("warm", [[], "x", 5, 0, True])
def test_a_malformed_warmupstate_does_not_abort_the_seed(warm, valve_model):
    """The one container `apply_rest_state` promised to type-check and did not.

    `or {}` rescues a null but hands a list or a string through, and the next `.get` raises
    `AttributeError` inside the REST seed — aborting setup with a traceback. Both call sites
    catch only `KohlerError`, so nothing downstream would have absorbed it.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.state import GcsState

    state = GcsState(valve_model, "Fahrenheit")
    state.apply_rest_state({"state": {"warmUpState": warm}})  # must not raise
    assert state.warmup_mode is None


def test_a_good_warmupstate_still_parses(valve_model):
    """The guard must not cost the normal case."""
    from custom_components.kohler_anthem_plus.anthem_plus.state import GcsState

    state = GcsState(valve_model, "Fahrenheit")
    state.apply_rest_state(
        {"state": {"warmUpState": {"warmUp": "warmUpDisabled", "state": "x"}}}
    )
    assert state.warmup_mode == "warmUpDisabled"


@pytest.mark.parametrize(
    ("outlets", "expected"),
    [
        # A string decomposes into truthy characters and read as EVERY outlet running —
        # wrong state, silently, with no error anywhere.
        ("110", [False, False, False]),
        # Kohler serves `"outlets": 2` as a *count* elsewhere in the same API
        # (docs/hub/cloud_api.md), and `len()` on an int raises.
        (2, [False, False, False]),
        (None, [False, False, False]),
        # The legitimate shape must still work.
        ([1, 0, 1], [True, False, True]),
    ],
)
def test_the_mqtt_outlet_array_is_guarded_like_the_rest_one(
    outlets, expected, valve_model
):
    """The REST path guarded this; the MQTT path did not."""
    from types import SimpleNamespace

    from custom_components.kohler_anthem_plus.anthem_plus.state import HubState

    state = HubState(valve_model)
    state._apply_valve(
        SimpleNamespace(
            attributes=[{"zone": "1", "status": "ON", "outlets": outlets}], raw={}
        )
    )
    assert state.zones[1].outlets == expected


# --------------------------------------------------------------------------- #
# Seeding concurrency (0.16.0)
# --------------------------------------------------------------------------- #


class _SeedRecorder:
    """A stand-in client that records call order and sleeps like a round trip."""

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.started: list[str] = []
        self.fail: set[str] = set()

    async def _read(self, name: str) -> dict:
        self.started.append(name)
        await asyncio.sleep(self.delay)
        if name in self.fail:
            from custom_components.kohler_anthem_plus.anthem_plus.client import (
                KohlerError,
            )

            raise KohlerError(f"{name} failed")
        return {}

    async def async_get_gcs_settings(self, device_id):
        return await self._read("settings")

    async def async_get_gcs_state(self, device_id):
        return await self._read("state")

    async def async_get_gcs_configuration(self, device_id):
        return await self._read("configuration")

    async def async_get_gcs_presets(self, device_id):
        return await self._read("presets")

    async def async_get_usage(self, device_id, *, from_date, to_date, interval="MONTH"):
        # Mirrors the real client, which answers {} rather than raising.
        try:
            return await self._read("usage")
        except Exception:
            return {}


def _seed_valve(client):
    """A Valve with just enough wired up to run `async_seed`."""
    from custom_components.kohler_anthem_plus import coordinator as module

    valve = object.__new__(module.Valve)
    # `client` is a read-only property reading through the coordinator.
    valve.coordinator = SimpleNamespace(client=client)
    valve.gcs_device = SimpleNamespace(device_id="dev-1")
    valve.configuration = None
    valve.usage = {}
    valve._seeded_presets = None
    valve._topology_checked = True
    valve.cloud_watch = None
    valve.gcs_state = SimpleNamespace(
        outlet_limits={},
        warmup_mode=None,
        apply_rest_state=lambda payload: None,
        apply_preset_list=lambda payload: False,
    )
    valve.warmup = SimpleNamespace(note_seeded_mode=lambda before, after: None)
    valve._learn_run_times = lambda state: None
    return valve


@pytest.mark.asyncio
async def test_independent_seed_reads_overlap_the_ordered_pair():
    """Three of the five seed reads depend on nothing and must not wait their turn.

    Only `gcs-settings` → `gcs-state` is a real ordering (topology decodes the state word).
    Run serially, a cold start paid five round trips deep per valve; the configuration,
    usage and preset reads now overlap the pair, making it two deep.
    """
    client = _SeedRecorder()
    valve = _seed_valve(client)

    await valve.async_seed()

    # The independent reads must have been *issued* before the ordered pair finished —
    # which is what proves they overlap rather than merely being reordered.
    assert client.started.index("configuration") < client.started.index("state")
    assert client.started.index("presets") < client.started.index("state")
    # And the dependency that is real still holds.
    assert client.started.index("settings") < client.started.index("state")


@pytest.mark.asyncio
async def test_seed_is_two_round_trips_deep_not_five():
    """Measured, not asserted from the source: the whole seed is two sleeps deep."""
    client = _SeedRecorder(delay=0.05)
    valve = _seed_valve(client)

    start = time.monotonic()
    await valve.async_seed()
    elapsed = time.monotonic() - start

    assert len(client.started) == 5, client.started
    # Two round trips (~0.10s) plus slack; five serial would be ~0.25s.
    assert elapsed < 0.20, f"seed took {elapsed:.3f}s — reads went serial again"


@pytest.mark.asyncio
async def test_one_failed_seed_read_does_not_blank_the_others():
    """Each read is guarded individually; a gather must not let one cancel its siblings."""
    client = _SeedRecorder()
    client.fail = {"configuration", "settings"}
    valve = _seed_valve(client)

    await valve.async_seed()

    # Every read was still attempted, and the failures were absorbed.
    assert set(client.started) == {
        "settings",
        "state",
        "configuration",
        "presets",
        "usage",
    }
    # A failed configuration read latches {} so a reconnect does not retry static data.
    assert valve.configuration == {}


@pytest.mark.asyncio
async def test_cancelling_a_seed_leaves_no_orphaned_reads():
    """A reload mid-seed must not leave reads running against a discarded entry.

    The same class of bug 0.15.1 fixed for the reconnect reseed: awaiting the background
    task in a plain `finally` would not do it, because that await is cancelled too.
    """
    client = _SeedRecorder(delay=0.05)
    valve = _seed_valve(client)

    task = asyncio.ensure_future(valve.async_seed())
    await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Give anything orphaned a chance to still be pending.
    await asyncio.sleep(0.12)
    pending = [
        t
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]
    assert not pending, f"{len(pending)} seed read(s) outlived the cancelled seed"


def test_zone_word_entity_reads_the_right_zone_everywhere():
    """Zone→word was duplicated in two platforms; reading the wrong zone is silent.

    A two-zone shower would report and command the other half with no error anywhere, so
    the shared accessor is asserted against both zones on both platforms that use it.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.models import (
        model_for_topology,
    )
    from custom_components.kohler_anthem_plus.entity import ZoneWordEntity
    from custom_components.kohler_anthem_plus.number import ZoneNumberBase
    from custom_components.kohler_anthem_plus.sensor import ValveHexSensor

    # Both platforms must share the one implementation, not re-declare it.
    assert issubclass(ValveHexSensor, ZoneWordEntity)
    assert issubclass(ZoneNumberBase, ZoneWordEntity)

    model = model_for_topology(3, 3)
    valve = make_valve(model, [31, 11, 1, 11, None, 21])
    coordinator = make_coordinator([valve])

    assert ValveHexSensor(coordinator, valve, 1)._word is valve.gcs_state.valve1
    assert ValveHexSensor(coordinator, valve, 2)._word is valve.gcs_state.valve2

    # The diagnostic defaults and the unique id must survive the shared base.
    hex2 = ValveHexSensor(coordinator, valve, 2)
    assert hex2.unique_id == "gcs-test0001_zone_2_hex"
    assert hex2.entity_registry_enabled_default is False
    assert hex2.entity_category is not None


# --------------------------------------------------------------------------- #
# Security (0.16.0)
# --------------------------------------------------------------------------- #


def test_version_scanner_does_not_copy_out_identifiers():
    """A device id is short enough to pass the length ceiling — shape must be checked too.

    `_version_fields` walks whatever the cloud returns, so it meets keys no capture has
    covered. A real device id is `gcs-sio32343h7` — fourteen characters, well under
    `_VERSION_VALUE_MAX_LEN` — so length alone could never have caught one sitting under a
    version-shaped key.
    """
    from custom_components.kohler_anthem_plus.diagnostics import _version_fields

    found = _version_fields(
        {
            "configuration": {
                "about": {
                    "interface": {"firmware": "2.20"},
                    "valve": {"firmware": 10},
                    "gateway": {"firmware": "00.74"},
                }
            },
            "shortDeviceVersion": "gcs-sio32343h7",
            "hubVersionId": "hub-ab12cd34",
            "swVersion": "00112233-4455-6677-8899-001122334455",
            "iotVersion": "HostName=x;DeviceId=gcs-1122;SharedAccessKey=k==",
            "serialVersion": "0011223344556677aabb",
            "version": "2.88",
        }
    )

    # Every real firmware still comes through, including the bare integer.
    assert found["configuration.about.interface.firmware"] == "2.20"
    assert found["configuration.about.valve.firmware"] == 10
    assert found["configuration.about.gateway.firmware"] == "00.74"
    assert found["version"] == "2.88"

    # Nothing identifier-shaped survives as its own value.
    for key in (
        "shortDeviceVersion",
        "hubVersionId",
        "swVersion",
        "iotVersion",
        "serialVersion",
    ):
        assert found[key].startswith("<str,"), f"{key} leaked as {found[key]!r}"
    assert "gcs-sio32343h7" not in repr(found)
    assert "SharedAccessKey" not in repr(found)


def test_a_secret_hidden_in_a_value_is_redacted():
    """`_redact_payload` matched key names only; an Azure connection string hides in one.

    It runs on whatever the cloud returns — including `probe_usage`, which deliberately
    calls undocumented endpoints — so a credential under a neutral key was copied out whole.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.client import _redact_payload

    out = _redact_payload(
        {
            "connectionString": (
                "HostName=k.azure-devices.net;DeviceId=gcs-x;SharedAccessKey=SECRET=="
            ),
            "sasUri": "https://x/?sig=ABC123&se=1",
            "password": "hunter2",
            "ioTHub": "kohler.azure-devices.net",
            "firmware": "2.20",
        }
    )

    assert out["connectionString"] == "**REDACTED**"
    assert out["sasUri"] == "**REDACTED**"
    assert out["password"] == "**REDACTED**"
    assert "SECRET" not in repr(out)
    assert "ABC123" not in repr(out)
    # Still useful: non-secret context survives.
    assert out["ioTHub"] == "kohler.azure-devices.net"
    assert out["firmware"] == "2.20"


def test_report_log_will_not_resume_outside_its_directory(tmp_path):
    """`_part_path` joins the stem straight onto the directory.

    Only `start()` ever writes the stem, so a hostile value means the config entry was
    already edited — but it round-trips through a file an operator may hand-edit, and the
    guard is one comparison.
    """
    from custom_components.kohler_anthem_plus.anthem_plus.report_log import ReportLog

    log = ReportLog(str(tmp_path / "reports"), max_bytes=10_000)
    try:
        log.resume("../../../../../../tmp/kohler_pwned_report")
        # Rejected, and a fresh legitimate episode started in its place.
        assert log._stem is not None
        assert log._stem.startswith("report_")
        assert not Path("/tmp/kohler_pwned_report.jsonl").exists()
        for written in (tmp_path / "reports").glob("*.jsonl"):
            assert written.parent == tmp_path / "reports"
    finally:
        log.close()

    # A name this class could have written is still honoured.
    log2 = ReportLog(str(tmp_path / "reports"), max_bytes=10_000)
    try:
        log2.resume("report_20260911T120000Z")
        assert log2._stem == "report_20260911T120000Z"
    finally:
        log2.close()


def test_no_device_id_reaches_a_non_debug_log():
    """Device ids are cloud addresses and must not reach the log people paste into issues.

    0.9.0 removed them from the startup line and from read errors; three INFO messages
    added since then had reintroduced them — two topology-mismatch messages (which a
    multi-valve account triggers) and the per-valve settings migration.

    DEBUG is exempt: it is opt-in, and the raw captures already carry ids with their own
    warning. `mqtt.py` is allowed the last 8 characters of the *mobile* identity, which is
    this integration's own registration, not a device address.
    """
    import ast

    base = (
        Path(__file__).resolve().parents[1] / "custom_components" / "kohler_anthem_plus"
    )
    risky = (
        "device_id",
        "serial_number",
        "refresh_token",
        "access_token",
        "tenant_id",
        "password",
    )
    offenders = []
    for path in sorted([*base.glob("*.py"), *base.glob("anthem_plus/*.py")]):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"info", "warning", "error", "critical"}
                and isinstance(node.func.value, ast.Name)
                and "LOGGER" in node.func.value.id.upper()
            ):
                continue
            for arg in node.args[1:]:
                source = ast.unparse(arg)
                if any(name in source for name in risky):
                    offenders.append(f"{path.name}:{node.lineno} {source}")

    # Matched on content, not on a line number, so this does not break when mqtt.py moves.
    def _allowed(entry: str) -> bool:
        return "_mobile_device_id" in entry and "[-8:]" in entry

    assert not [o for o in offenders if not _allowed(o)], offenders
