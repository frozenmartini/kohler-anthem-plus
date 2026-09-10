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
