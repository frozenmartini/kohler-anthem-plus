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
# The controller's own water state, published alongside the valve's
# ---------------------------------------------------------------------------
# **No longer temporary — do NOT set this back to False.** It went in as a debugging aid
# and became load-bearing on 2026-08-18.
#
# Normally nothing derived from `SHOWER_VALVE_STS` is published on an account that also has
# a valve: the controller does not observe a valve-driven session and reports `status: OFF`
# with an all-zero outlet array while water is running, so it would contradict the valve's
# own entities on the same dashboard.
#
# That contradiction turned out to be the information, not the noise. The two sources
# answer different questions — the valve "is water running", the controller "does this
# controller know about it" — and the second decides whether the controller's `stopall`,
# `valvecontrol OFF`, and 60-minute session ceiling apply at all. So the `ControllerOutlet`
# sensors are now the Anthem Plus device's reference for water, and
# `coordinator.hub_water_is_running` — which backs both controller switches — is defined to
# agree with them exactly.
#
# Turning this off would delete the rows the owner reads the controller's view from. The
# switches keep working (they read `hub_state`, not the entities), but the evidence behind
# them becomes invisible.
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


# Learned per-outlet `maximumRunTime`, persisted so the cutoff feature is armed from the first
# second after a restart rather than waiting on an unprompted announcement.
#
# ⚠️ **Corrected 2026-08-17.** This comment used to say the value was "otherwise unobtainable on
# demand" because every `gcs-outlet-config`-style REST path 404s. Those paths really do 404, but
# the data was reachable all along: **`gcsadvancestate` carries
# `setting.valveSettings[].outletConfigurations[]`**, and this integration already calls that
# endpoint — `topology.py` reads `noOfOutlets` from the very same response. Verified live.
#
# Persisting is still worth it (one fewer REST round trip on the hot path), but the "blind
# window" that justified it is not the constraint it was believed to be. Reading it at setup
# would close that window entirely — see `docs/gcs/api.md` §1c. Not yet done.
#
# Without persistence the cutoff feature is inert after every restart until the valve happens
# to announce again, which can be a long wait and gives no sign of why nothing is happening.
# The value is installation configuration and does not drift, so remembering it is safe; a
# fresh announcement always overwrites what is stored.
CONF_OUTLET_RUN_TIMES = "outlet_run_times"

# ---------------------------------------------------------------------------
# Endless Shower — the messages the owner actually reads
# ---------------------------------------------------------------------------
# Written for someone standing in a bathroom, not for whoever wrote the integration. The
# feature is called **Endless Shower** everywhere the owner can see it; `maximumRunTime`,
# `restart_on_runtime_cutoff` and the zone/outlet split are internal and stay out of these.
#
# The one setting a user can act on is **Max Shower Duration** in the Kohler Konnect app, so
# every "it is not working" message points at exactly that and nothing else.
#
# Shared between the startup log in `coordinator.py` and the switch-on log in `switch.py`, so
# the two cannot drift into saying different things about the same state.

# Nothing to work with: no outlet has reported a duration, or only some have. Also used when
# a cutoff fires but no outlet snapshot exists to restore.
# ⚠️ **Reworded 2026-08-17 and it must stay this way.** This used to read "please reconfigure
# 'Max Shower Duration' in the Kohler Konnect app" — advice that existed only because the limit
# arrived over MQTT unprompted, so changing the app setting was the one way to provoke an
# announcement. The integration now reads it over REST at setup (`gcsadvancestate`), so that
# instruction is obsolete: this state is transient and self-healing, not something the owner
# should be sent to the app to fix.
ENDLESS_SHOWER_NOT_SET_UP = (
    "Endless Shower is ON but the shower time limit has not been read from the valve yet, so "
    "nothing will be restarted. It arms itself automatically as soon as the valve reports it."
)

# Armed. %s is the duration in whole minutes, from `describe_duration`.
ENDLESS_SHOWER_ON = (
    "Endless Shower is ON. Your shower will restart automatically every %s minutes, when "
    "'Max Shower Duration' is reached."
)

# ⚠️ Only shown when the account has BOTH an Anthem valve and an Anthem Plus controller.
#
# The two devices each enforce their own maximum shower duration and they signal differently:
# the valve **pauses** (`0x40`), the controller **stops** (`0x00`). Endless Shower acts on the
# pause, because only the valve's cut is one it can safely tell apart from somebody deliberately
# ending their shower.
#
# Measured across five case studies (`docs/case_studies/`): the valve fires marginally early
# (-0.08 to -0.23 s against its limit) and the controller marginally late (+0.20 to +1.00 s),
# so **when the two durations are equal the valve always cuts first** and Endless Shower always
# has a pause to act on. When they are NOT equal, whichever is shorter wins — and if that is the
# controller, its `0x00` is declined and the shower stays off.
#
# %s is the valve's duration in whole minutes.
ENDLESS_SHOWER_MATCH_DURATIONS = (
    "Endless Shower: your Anthem valve's Max Shower Duration is %s minutes. Set the Anthem "
    "Plus controller's Max Shower Duration to the SAME value, or your shower may stop without "
    "restarting. The two devices run separate timers and Endless Shower can only act on the "
    "valve's."
)

# A cutoff was caught and the shower put back. %s is the local time it was cut off.
ENDLESS_SHOWER_RESTARTED = "Max Shower Duration reached at %s. Restarted the shower."

# Defensive only. A cutoff cannot normally fire without a mask to restore: the detector sets
# its start time and its last-running mask on the same update, and `forget()` clears both
# together, so "timed a zone" and "knows what was in it" cannot come apart. It has never
# fired — all seven restores in the capture corpus had a mask.
#
# ⚠️ **This is NOT the "Home Assistant restarted mid-shower" case.** That one produces no log
# at all, and cannot: the clock restarts with the process, so at the valve's real cut-off the
# measured duration falls short of the limit, nothing matches, and no cutoff is detected. The
# shower simply ends. Deliberate — see `ZoneCutoffDetector`, which would rather miss a cutoff
# than reopen a valve on a duration it did not actually measure.
#
# Says nothing about zones: the owner has no use for the zone number, and the cutoff debug
# log carries it for anyone investigating. Logged once per affected zone, so two lines mean
# two zones.
# Repairs card shown while Endless Shower is on but cannot act. A log line states this once,
# at startup, and then scrolls away — it can never answer "is it still broken?", which is the
# only question the owner actually has. A repair is the opposite: it appears when the
# condition becomes true, persists while it stays true, and removes itself when the valve
# finally reports a duration. Nobody has to dismiss it.
#
# Doubles as the `translation_key`, so the text lives in `strings.json` under `issues`.
ISSUE_NOT_SET_UP = "endless_shower_not_set_up"

ENDLESS_SHOWER_NOTHING_TO_RESTORE = (
    "Endless Shower could not restart the shower, because Home Assistant has no record of "
    "what was running."
)

# ---------------------------------------------------------------------------
# Preset 1's hidden timer — normalised once at setup
# ---------------------------------------------------------------------------
# A GCS preset carries its own `time`, a second run-time limit independent of the outlets'
# `maximumRunTime`. Whichever is lower stops the shower, and nothing ever re-syncs the preset
# to the hardware value: `time` is only ever what the last writer sent. Full protocol detail
# in `docs/gcs/api.md`, "two independent timers".
#
# That is a problem for **preset 1 specifically, and only preset 1**, because it is hidden
# from the owner in both the first-generation touchscreen and the Konnect app. Its timer is
# whatever the setup wizard happened to store when the preset was created — on this install,
# 1800 s, frozen at a factory reset on 2026-08-14 and then stranded when `maximumRunTime`
# went to 3600 s. The owner has no interface anywhere that can correct it.
#
# So the integration sets it once, to `DEFAULT_PRESET_TIMER_SECONDS`, and then leaves it
# alone. The intent is not to manage the timer but to take it *out* of the way, so the
# hardware gate is the thing that limits a shower — one limit, in one place, that the owner
# can actually see and change.
#
# **Every other preset is deliberately untouched.** Presets 2-10 are visible and editable in
# the Konnect app, their timers are the owner's choice, and on the first-generation
# touchscreen that timer is also the countdown shown during a run. Normalising those would
# overwrite a deliberate setting and change what the panel displays. Preset 1 is exempt from
# that reasoning precisely because it is the one the owner cannot see.
#
# Why a constant rather than following `maximumRunTime`: the hardware limit cannot be read on
# demand *over MQTT*, which is where this runs: `READ_GCS_OUTLET_CONFIG_CFG` arrives unprompted,
# one outlet at a time, so at setup the value is frequently not known yet. (It **is** readable
# over REST from `gcsadvancestate` — corrected 2026-08-17 — but this sync deliberately does not
# depend on a second network read succeeding.) A fixed target that is at or above every observed hardware value
# leaves the gate to the hardware in every case.
SYNC_DEFAULT_PRESET_TIMER = True
# Preset 1 is "Default shower" on every install seen: created by the setup wizard, and the
# slot the app hides.
DEFAULT_PRESET_ID = 1
# 3600 s is the highest `maximumRunTime` observed on this hardware (900/1800/3600). Setting
# the preset at the ceiling means the outlet limit is always the binding constraint.
DEFAULT_PRESET_TIMER_SECONDS = 3600

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
