# Kohler Anthem Plus / Konnect — reverse-engineering reference

Protocol documentation for the Kohler **Anthem Plus** system, merged from the Windows
research session (2026-08-10) and the live Home Assistant work.

**Start with [`architecture.md`](architecture.md)** — it explains the two products, which
paths can actually carry a control command, and where state comes from. The endpoint
references below assume it.

## The two products in one line each

- **Anthem** (SKU `GCS`) — a digital valve body with built-in Wi-Fi. The app talks to the
  valve directly. Every start specifies the full valve state as a hex command word.
- **Anthem Plus** (SKU `HUB`) — a Linux system controller that drives the valves *and*
  integrates music, lighting, and steam. The app talks to the controller, and control is
  organised around **favourites** rather than direct commands.

Most Home Assistant Kohler integrations only handle GCS, because the upstream
`yon/kohler-anthem` library only reverse-engineered that device.

## Documents

| Path | Covers |
|---|---|
| [`architecture.md`](architecture.md) | **Read first.** The two products, the three control surfaces, why the local API cannot actuate, MQTT vs REST. |
| [`gcs/valve_hex.md`](gcs/valve_hex.md) | The valve command word — temperature, flow, outlet mask, preset byte order. Capture-derived and authoritative. |
| [`gcs/valve_reboot_fault.md`](gcs/valve_reboot_fault.md) | ⚠️ **The diagnostics this document tells you to read were removed 2026-08-15** — see its top banner; confirm from the raw MQTT capture or `moes_correlation.py` instead. **✅ SOLVED 2026-08-15 — it was a smart outlet.** The valve rebooted unprompted 25 times and two factory resets changed nothing, because neither touched the power source: both devices were on the Moes socket Home Assistant knows as `switch.bedroom_closet_lower_outlet`. §3d has the proof — ten off→on cycles, ten valve reboots, all at +18/19 s, with a clean negative control. Never caused by the integration. §3e closes the diagnosis: a second device (a Raspberry Pi) on the same outlet reboots in lockstep at 13 outages/hour, the rest of the house is unaffected, and it is a hardware fault on that Moes unit — not electrical/circuit-wide, not Wi-Fi, not Home Assistant. **Both the valve and controller are now off that outlet** (controller moved 2026-08-15, later the same session) — clean but not yet confirmed over a multi-hour window; confirm whether the Pi was also moved. §5 also closes a separate, related bug: the run-time cutoff's restore now replays the exact pre-cutoff flow instead of forcing 100%. |
| [`gcs/api.md`](gcs/api.md) | GCS cloud endpoints: `solowritesystem`, presets, the warmup mode enum, decompile pointers. **⭐ 2026-08-17: there are TWO run-time limits, not one** — the outlets' hardware `maximumRunTime` and each preset's own software `time`, and the lower one wins. Nothing re-syncs them: `time` is only ever what the last writer sent, proven both ways. Preset 1 is invisible in both UIs, so the integration normalises its timer once at setup and leaves presets 2-10 to the owner. |
| [`hub/cloud_api.md`](hub/cloud_api.md) | HUB cloud REST: favourites CRUD, control, experiences, lighting, music, read shapes. |
| [`hub/local_api.md`](hub/local_api.md) | HUB **local** LAN API: PIN→JWT auth, `req_update_command`, Zigbee pairing, Control4 channel. Config and diagnostics only. |
| [`hub/lighting.md`](hub/lighting.md) | **❌ Zigbee lighting cannot be paired locally on fw 2.88 — live-tested 2026-08-15.** A Hue Zigbee 3.0 bulb never joined the hub's coordinator, while the same bulb joined Zigbee2MQTT in 13 s with the hub's own window still open. Rules out the §5.6 UI bug, payload shape, radio state, window length, reset state, range and coordinator competition. *Why* is unknowable from here: the local API has **no error surface at all** and `get_error_log` times out at 170 s. Also: the "accept the risk" prompt is client-side only and makes no API call, and no command anywhere changes Zigbee security mode. ⚠️ Contains the touchlink/InterPAN trap that froze the whole house's Zigbee network. |
| [`mqtt/capture_runbook.md`](mqtt/capture_runbook.md) | Event-driven MQTT bridge: subscriptions, message codes, HA bridge topics. |
| [`handoff/`](handoff/) | Session handoffs. **Start with [2026-08-17 session 8](handoff/2026-08-17_session8_current.md)** — the Moes fix is confirmed held (zero reboots in 44 h), the config-entry update listener that could never fire is fixed, and preset timers turn out to be a second run-time limit the integration now normalises for the hidden preset 1. Before it, [session 7](handoff/2026-08-15_session7_current.md) closed two things out late on its own day: Zigbee lighting **cannot be paired locally** (→ [`hub/lighting.md`](hub/lighting.md)), and the **valve reboot counter, controller ping and outage counter were all removed**, so `sensor.anthem_valve_valve_reboots`, `sensor.anthem_plus_controller_local_outages` and `binary_sensor.anthem_plus_controller_local_api` no longer exist and any instruction to read them is stale. Below that, the Moes smart-outlet blip precedes **every** controller outage (2 of 2, with blip duration as the discriminator), the controller genuinely **reboots** rather than going unreachable, and the outage counter now **persists across restarts** so the confirming test can actually be read. The valve is clean for 5+ hours and rode out both outages untouched. [Session 6](handoff/2026-08-14_session6_current.md) remains the reference for the run-time cutoff — timed **per zone**, not per outlet, which is why the restart feature was missing most cutoffs, and **verified working on hardware, 4 of 4 cutoffs caught**. It also holds the cutoff debug log, the valve reboot counter and controller reachability probe, the flow-ceiling result (an **uncalibrated** valve has no ceiling at all), and the finding that the valve reasserts its own max shower time seconds after every reboot. [Session 5](handoff/2026-08-13_session5_current.md) remains the reference for everything else — 34 entities, raw MQTT capture inside the integration, the `send_valve_hex` action, reauth on a rejected credential, and the flow/preset/warm-up findings. [Session 4](handoff/2026-08-13_session4_current.md) is still the reference for the push-only architecture and which device answers which question; [session 3](handoff/2026-08-12_session3_current.md) the bug fixes and preset findings; [session 2](handoff/2026-08-12_session2_current.md) the protocol corrections and safety rules. |
| [`../tests/`](../tests/) | Regression harnesses. The ones needing no credentials replay captured data offline. |

## Which source wins

State is read over **MQTT** (event-driven); REST reads are poll-only and partly cached.
Control is **cloud-only** for both SKUs — the HUB's local API cannot turn anything on.

When documents disagree about the valve word, the reference implementation is
`kohler_konnect_custom/mqtt_capture.py` → `decode_valve_state()`. Two decompile-derived
readings were found to contradict it and have been corrected — see
[Superseded readings](gcs/valve_hex.md#superseded-readings).

## Scope: one valve unit, up to 6 outlets

This work covers a **single Anthem valve unit** — one physical body with two zones of up to
three outlets each, so **6 outlets maximum**. That is the K-28209 / K-28210 / K-28211 /
K-28212 range, and it is what the Home Assistant integration supports.

An Anthem Plus controller can drive **two** such units (12 outlets). That configuration is
**out of scope and untested**: the GCS API exposes eight zone slots
(`primaryValve1`, `secondaryValve1`…`secondaryValve7`) and the controller reports a second
unit as `parts.valve2: Connected`, but nothing here reads beyond the first unit's two zones.
A two-unit install would silently under-report — see
[`architecture.md`](architecture.md#valve-means-different-things-on-the-two-apis) for why the
two APIs count different things.

## Test-system caveats — read before generalising

Everything here was derived from **one** installation. Several of its quirks shape what was
observable, and a field reading zero in these captures may simply mean "not exercised here".

| Caveat | Consequence |
|---|---|
| **Flow control is disabled system-wide** — the recommended workaround for a broken per-outlet flow calculation on Anthem Plus firmware **2.88** | `atFlow` (byte 0 `0x08`) is **0 in every capture**, and the measured-flow byte is too. **`atFlow` is untested, not broken.** It may work normally where flow control is enabled. |
| Main shower plumbed to **zone 2 / outlet 1**, not Kohler's expected zone 1 / outlet 1 | Made it visible that `atTemp` is **system-level on the primary valve**, reported even when another zone does the work |
| **Outlet 6** (tub filler) rarely used | Never appeared in 860+ captured messages, though it works |
| HUB reports `valve2: NotConnected`, `light`/`steam` `NotConnected` | Lighting and steam favourite fields are **decompile-mapped only**, never exercised |
| Valve model is **K-28212** (6 outlets, 3+3) | The 2-outlet and 4-outlet bit layouts are inferred, not measured |
| The valve reports **no measured temperature or flow** over MQTT | Bytes 4–6 are always zero; the mapping is corroborated only by `errorCode` matching `gcs-state` |

Firmware on the tested controller is **2.88** throughout. The `nclpl/anthem_shower` project
was built against **2.72**, and behaviour differs — see [`hub/local_api.md`](hub/local_api.md).

## Placeholders

Live credentials have been removed from these documents. Where a real value is needed to run
an example, substitute your own:

| Placeholder | What it is |
|---|---|
| `<HUB_IP>` | The Anthem Plus controller's LAN address |
| `<HUB_PIN>` | The controller's device PIN, from its touchscreen |
| `<TENANT_ID>` | Your account id — the `oid` claim of a decoded access token |
| `<MAC_1>`, `<MAC_2>` | Hardware addresses reported by the local API |

Device IDs (`gcs-sio32343h7`, `gcs-sious0103D`) are left in place as concrete examples. They
identify hardware on one account but are not credentials — substitute your own.

The APIM subscription key `429ecb1d0b5e4258aa0a2bfadd82a493` is **not** a secret: it is
app-global, baked into the Konnect app, and identical across accounts.
