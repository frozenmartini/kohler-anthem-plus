"""Home Assistant constants for the Kohler Anthem Plus integration.

Protocol constants live in ``anthem_plus/const.py``. This module holds only what Home
Assistant itself needs: the domain, config-entry keys, and tuning.
"""

from __future__ import annotations

DOMAIN = "kohler_anthem_plus"

# ---------------------------------------------------------------------------
# Config-entry keys
# ---------------------------------------------------------------------------
# username comes from homeassistant.const.CONF_USERNAME.
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TENANT_ID = "tenant_id"
CONF_VALVE_MODEL = "valve_model"
# The detected outlet split, e.g. [3, 3]. Stored alongside the SKU so an install that does
# not match a catalogue model still works, and so a later SKU rename cannot change topology.
CONF_ZONE_OUTLETS = "zone_outlets"
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_WATER_UNITS = "water_units"
# The Azure IoT Hub identity this install registers as, generated once and then reused.
#
# Without this, every connect registered a fresh `uuid4()` identity — so each restart and
# each reconnect left another dead "phone" on the Kohler account. Reusing one identity also
# means any first-registration delay is paid once, ever, rather than on every connect.
#
# Stored per config entry, never global: two Home Assistant instances on one account must
# not share an identity or they would fight over the same MQTT client id.
CONF_MOBILE_DEVICE_ID = "mobile_device_id"

# ---------------------------------------------------------------------------
# Polling — deliberately none
# ---------------------------------------------------------------------------
# `None` disables the coordinator's interval entirely. This integration is push-driven:
# every state change arrives over MQTT, and REST is read on two **events** — setup, and each
# MQTT (re)connect — never on a clock.
#
# The reads cannot be dropped altogether, because **the broker replays nothing on connect**.
# Measured across 27 capture sessions: the first message after connecting is always a change
# event, never a state dump. Six sessions received nothing at all, and the longest silence
# was 11.9 hours. Without a read at connect, every restart would leave entities `unknown`
# until somebody next used the shower.
#
# `homeassistant.update_entity` still forces a refresh on demand — that is the manual path,
# and the only one.
SCAN_INTERVAL = None

# ---------------------------------------------------------------------------
# Shower switch
# ---------------------------------------------------------------------------
# Turning `switch.anthem_valve_shower` on activates this preset. The valve has no "run my
# default" command, so a whole-shower start has to name a stored preset — see ShowerSwitch.
#
# Preset ids are positional and the app hides preset 1 from its own list, so the id shown in
# the app is not this id. Adding a preset appends (a new one became id 3, leaving 1 and 2
# alone), but a deletion is expected to renumber, exactly as HUB favourites do. If a start
# ever runs the wrong scene, re-read the preset list before assuming the valve misbehaved.
SHOWER_ON_PRESET_ID = 1

# Presets never offered to the user as a choosable scene.
#
# Preset 1 is the valve's mandatory default-shower configuration and the Konnect app hides it
# from its own list, so surfacing it would show something the app does not. It stays
# reachable — it is exactly what `SHOWER_ON_PRESET_ID` above activates — but it is the
# shower switch's business, not an entry in a preset picker.
PRESET_HIDDEN_IDS: frozenset[int] = frozenset({1})

# ---------------------------------------------------------------------------
# Temporary debugging
# ---------------------------------------------------------------------------
# **TEMPORARY — set back to False when done.**
#
# Normally nothing derived from `SHOWER_VALVE_STS` is published on an account that also has
# a valve: the controller does not observe a valve-driven session and reports `status: OFF`
# with an all-zero outlet array while water is running, so it would contradict the valve's
# own entities on the same dashboard.
#
# Set True to publish them anyway, as diagnostics, for comparing the two sources side by
# side while debugging. They are *expected* to disagree — that is the point of looking.
EXPOSE_CONTROLLER_WATER_STATE = True

# ---------------------------------------------------------------------------
# RAW MQTT LOG — diagnostic capture of every payload, before decoding
# ---------------------------------------------------------------------------
# Full explanation, file format, and the runtime switch: `anthem_plus/raw_log.py`.
# Find every piece of this feature with:
#
#     grep -rn "RAW MQTT LOG" custom_components/kohler_anthem_plus/
#
# Prefer the runtime switch over this constant — it needs no restart and no file edit.
# Developer Tools -> Actions -> `logger.set_level`:
#
#     custom_components.kohler_anthem_plus.anthem_plus.raw_log: debug
#
# This constant pins capture on across restarts instead.
#
# **Currently ON, deliberately** — switched on 2026-08-13 (session 5) at the user's request
# for a stretch of work involving frequent restarts, where a UI toggle that resets on every
# restart would be useless. Set back to False when that debugging is done; the capture is
# bounded (8 MB x 6 files) so leaving it on is untidy rather than dangerous.
ENABLE_RAW_MQTT_LOG = True

# Written under the Home Assistant config directory, so it is reachable from the File editor
# and Samba add-ons rather than buried in the container.
RAW_MQTT_LOG_DIR = "kohler_anthem_plus_raw"
RAW_MQTT_LOG_MAX_BYTES = 8 * 1024 * 1024
# None = no limit on the number of files; every capture is kept forever. Set at the user's
# request on 2026-08-14 — this directory is meant to be a permanent record, not a rotating
# buffer, and deleting old captures automatically risks losing the ones a future session
# needs. Each file is still capped at RAW_MQTT_LOG_MAX_BYTES, so growth is in file count, not
# a single unbounded file.
RAW_MQTT_LOG_KEEP_FILES = None

# ---------------------------------------------------------------------------
# CUTOFF DEBUG LOG — why the run-time cutoff fired, or didn't
# ---------------------------------------------------------------------------
# Full explanation and how to read it against the raw capture: `anthem_plus/cutoff_log.py`.
# Find every piece of this feature with:
#
#     grep -rn "CUTOFF DEBUG LOG" custom_components/kohler_anthem_plus/
#
# Runtime switch, no restart needed — Developer Tools -> Actions -> `logger.set_level`:
#
#     custom_components.kohler_anthem_plus.anthem_plus.cutoff_log: debug
#
# **Currently ON, deliberately** — switched on 2026-08-14 (session 6) after the detector was
# found to be timing the wrong thing. A cutoff that fails to fire writes nothing to
# `home-assistant.log`, so the only way to tell "no cutoff happened" from "a cutoff was
# missed" is this log. Written into the same directory as the raw capture and stamped from
# the same clock, so the two interleave by sorting on `ts`.
#
# Volume is a handful of lines per shower. Set back to False once the zone-based detector has
# been trusted for a while.
ENABLE_CUTOFF_DEBUG_LOG = True

# None = no limit on the number of files; every log is kept forever, matching
# RAW_MQTT_LOG_KEEP_FILES. Deliberately the same directory as the raw capture: these two logs
# are read together, and splitting them across directories only makes the join harder.
CUTOFF_DEBUG_LOG_KEEP_FILES = None

# ---------------------------------------------------------------------------
# Run-time cutoff restart (option, default off)
# ---------------------------------------------------------------------------
# The valve shuts a **zone** off once it has been running for `maximumRunTime` — 900 s on the
# reference install now, 3600 s before it was reconfigured, reported per outlet in
# `READ_GCS_OUTLET_CONFIG_CFG` but timed per zone. With this option on, the integration
# re-opens the outlets that were running and the shower carries on.
#
# The per-zone part is not a detail: the timer starts when a zone begins flowing and does not
# reset when outlets change within it. Timing each outlet instead — which shipped until
# 2026-08-14 — misses every cutoff where somebody moved between shower heads. See
# `anthem_plus/runtime_cutoff.py`.
#
# **This defeats a manufacturer cutoff, and there is no resume limit.** Water will keep
# coming back for as long as somebody leaves it running, with no software or hardware stop
# behind it — the hardware stop is the thing being overridden. That is the owner's stated
# choice, made after the trade-off was put to them explicitly; it is not an oversight to
# "fix". Leave it default-off, keep every restart logged at WARNING, and do not extend it to
# fire on anything other than a positive run-time match.
CONF_RESTART_ON_RUNTIME_CUTOFF = "restart_on_runtime_cutoff"

# ---------------------------------------------------------------------------
# Staged promotion of a *learned* run-time limit
# ---------------------------------------------------------------------------
# The integration can notice a limit the valve never announced, by spotting pause durations
# that repeat to the fraction of a second (`MissedCutoffWatcher`). Whether it may then act on
# one is this flag, and it is **off**.
#
# The order to do this in, agreed with the owner 2026-08-14:
#
#   1. Leave it False. Shower normally. The cutoff debug log fills with `suspected_limit`
#      records and, whenever one of them matches a real close, a `would_have_fired` record
#      saying exactly which zone and which outlets it *would* have restored.
#   2. Read those. Check every `would_have_fired` against what actually happened.
#   3. Only when they are all correct, set this True. The suspected limit then joins the
#      announced ones as a candidate and restarts fire on it.
#
# Why the staging: a limit inferred from behaviour is a weaker claim than one the valve
# stated, and being wrong means water turning on with nobody there. `would_have_fired` costs
# nothing and turns "do you trust the inference" into a question with evidence behind it.
#
# This does not gate the *reporting*, which is always on and always harmless.
ACT_ON_LEARNED_LIMITS = False

# Learned per-outlet `maximumRunTime`, persisted because it is **otherwise unobtainable on
# demand**. There is no REST endpoint for outlet configuration — `gcs-outlet-config`,
# `gcs-outletconfig`, `gcs-outlet-configuration`, `gcs-valve-config` and friends all 404 —
# so the only source is `READ_GCS_OUTLET_CONFIG_CFG`, which the valve emits unprompted, one
# outlet per message, roughly twice a session.
#
# Without persistence the cutoff feature is inert after every restart until the valve happens
# to announce again, which can be a long wait and gives no sign of why nothing is happening.
# The value is installation configuration and does not drift, so remembering it is safe; a
# fresh announcement always overwrites what is stored.
CONF_OUTLET_RUN_TIMES = "outlet_run_times"

# ---------------------------------------------------------------------------
# What a config-entry change has to be before it is worth a reload
# ---------------------------------------------------------------------------
# Read by `_async_update_listener` in `__init__.py`; the mechanism is in
# `anthem_plus/entry_reload.py`, which also explains why the comparison needs a snapshot.
#
# Keys the running integration writes to its OWN entry. A change to one of them is
# bookkeeping, not configuration, and must never cause a reload:
#
# * `CONF_REFRESH_TOKEN` — B2C rotates it on every refresh and invalidates the previous one,
#   so the newest has to be persisted immediately or a restart comes up unauthenticated.
#   That makes it the most frequently written key here, and reloading on it would flap every
#   entity and drop MQTT for nothing.
# * `CONF_OUTLET_RUN_TIMES` — written whenever the valve announces a `maximumRunTime`, which
#   it does unprompted and **can do mid-shower**. A reload builds a new coordinator with a
#   fresh `ZoneCutoffDetector`, so every zone clock restarts at zero while the valve's own
#   timer keeps running: the exact mechanism by which a run-time cutoff gets missed. This
#   exclusion matters more than the comparison it is part of.
# * `CONF_MOBILE_DEVICE_ID` — generated once on first connect, then reused forever.
RELOAD_IGNORED_DATA_KEYS = frozenset(
    {CONF_REFRESH_TOKEN, CONF_OUTLET_RUN_TIMES, CONF_MOBILE_DEVICE_ID}
)

# Options the coordinator reads live from `entry.options` on every access instead of caching,
# so they already take effect the moment they are saved and a reload would be pure cost.
#
# Anything NOT listed here reloads. An option added later therefore works by default, and
# only an option proven to be read live gets added to this set — a decision someone has to
# write down rather than inherit by accident.
RELOAD_IGNORED_OPTION_KEYS = frozenset({CONF_RESTART_ON_RUNTIME_CUTOFF})

# ---------------------------------------------------------------------------
# REMOVED 2026-08-15 — valve reboot counter, controller ping, outage counter
# ---------------------------------------------------------------------------
# `CONF_GCS_REBOOT_COUNT` / `CONF_GCS_REBOOT_LAST` / `CONF_HUB_LOCAL_HOST` /
# `CONF_HUB_OUTAGE_COUNT` / `CONF_HUB_OUTAGE_LAST` / `CONF_HUB_OUTAGE_LAST_SECONDS` /
# `HUB_LOCAL_POLL_SECONDS` all lived here, alongside `anthem_plus/hub_local.py`.
#
# They existed to diagnose the valve reboot fault, and that investigation is closed: the
# cause was a failing Moes smart outlet, not the Kohler hardware
# (`docs/gcs/valve_reboot_fault.md`). With both devices moved off it, the counters had no
# remaining question to answer — and the probe was the integration's **only** polling loop
# in an otherwise push-only design, at 1 Hz against the controller.
#
# Stale keys may remain in the config entry on installations that ran the old code; they are
# ignored. `_async_migrate_entry_data` in `__init__.py` strips them on load.
# ---------------------------------------------------------------------------
# Temperature slider bounds (Home Assistant side only)
# ---------------------------------------------------------------------------
# What the temperature sliders offer. **These are a UI gate, not a device limit.** The valve
# accepts far more — 0 °C is a real setting meaning "full cold", and the app's own ceiling is
# 48.8 °C — and `valve_hex.py` still encodes the whole range, so a preset, the touchscreen,
# or `send_valve_hex` can still put the valve outside these bounds.
#
# Narrowed to the range people actually shower in, because a slider spanning 32-119 °F makes
# every useful degree a pixel wide. 113 °F is also exactly the `maximumOutletTemperature` the
# valve reports for every outlet (450 tenths °C), so the top of the slider matches the
# hardware's own ceiling.
#
# Stated in Fahrenheit and converted for a Celsius account — the reverse would make these
# unrecognisable to anyone checking them against the shower.
#
# Consequence to keep in mind: if the wall panel sets a temperature below the minimum, the
# entity still *reports* it, but the slider cannot represent it accurately.
UI_TEMPERATURE_MIN_F = 80
UI_TEMPERATURE_MAX_F = 113

# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------
# What flow Home Assistant writes when a command does not name one — which is every command
# it can currently issue, since the flow entities were removed (see `docs/gcs/api.md`).
#
# **This must not be "whatever the valve currently holds".** It used to be, and that quietly
# handed control of every HA write to the touchscreen: opening an outlet from Home Assistant
# re-sent the last flow the wall panel wrote. Measured over 1,346 captured valve words, 419 —
# **31%** — were below 100%, the lowest at **8%**. So roughly a third of the time, turning on
# a shower from Home Assistant would have produced a trickle, with nothing in the UI to
# explain why or to fix it.
#
# 100% is the only defensible default: it is what the Konnect app pins favourites to, and it
# is the one value a user who has no flow control cannot be surprised by.
DEFAULT_FLOW_PERCENT = 100.0

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
SERVICE_SET_OUTLETS = "set_outlets"
SERVICE_SEND_VALVE_HEX = "send_valve_hex"
SERVICE_START_PRESET = "start_preset"
SERVICE_ACTIVATE_FAVORITE = "activate_favorite"
SERVICE_STOP_ALL = "stop_all"
SERVICE_SET_WARMUP = "set_warmup"

ATTR_OUTLETS = "outlets"
ATTR_TEMPERATURE = "temperature"
ATTR_FLOW_PERCENT = "flow_percent"
ATTR_VALVE1_HEX = "valve1_hex"
ATTR_VALVE2_HEX = "valve2_hex"
ATTR_FAVORITE = "favorite"
ATTR_PRESET = "preset"
ATTR_WARMUP_MODE = "warmup_mode"
