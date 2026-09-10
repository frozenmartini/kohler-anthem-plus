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
        platform(name).async_setup_entry(hass, entry, lambda e, *a, **k: added.extend(e))
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
    assert "Shower Valves" in names


def test_run_time_sensors_follow_outlet_names(coordinator):
    names = {e.name for e in collect("sensor", coordinator)}
    assert "Rainhead Max Run Time" in names, sorted(names)


def test_single_zone_valve_drops_the_zone_prefix(coordinator):
    names = {e.name for e in collect("number", coordinator)}
    assert names == {"Temperature", "Flow"}


def test_two_zone_valve_keeps_the_zone_prefix(valve_model):
    from custom_components.kohler_anthem_plus.anthem_plus.models import get_valve_model

    model = get_valve_model("K-28212")
    coordinator = make_coordinator([make_valve(model, [31, 11, 1, 11, None, 21])])
    names = {e.name for e in collect("number", coordinator)}
    assert names == {
        "Zone 1 Temperature",
        "Zone 1 Flow",
        "Zone 2 Temperature",
        "Zone 2 Flow",
    }, sorted(names)


def test_unknown_outlet_type_falls_back_to_position(valve_model):
    """An unconfirmed type code must never be given an invented fixture name."""
    coordinator = make_coordinator([make_valve(valve_model, [999, 11, 1])])
    names = {e.name for e in collect("switch", coordinator)}
    assert "Zone 1 Outlet 1" in names, sorted(names)


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
