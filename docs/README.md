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
| [`gcs/api.md`](gcs/api.md) | GCS cloud endpoints: `solowritesystem`, presets, the warmup mode enum, decompile pointers. **⭐ 2026-08-17: there are TWO run-time limits, not one** — the outlets' hardware `maximumRunTime` and each preset's own software `time`, and the lower one wins. Nothing re-syncs them: `time` is only ever what the last writer sent, proven both ways. Preset 1 is invisible in both UIs, so the integration normalises its timer once at setup and leaves presets 2-10 to the owner. **§3 is the warmup reference** — a mode toggle, not a run-now command: §3a lists **four ways the call returns success and does nothing**, and `warmUpEnabled` (seen in older Python projects) does not exist. **Five mode strings, of which the current app offers three** — off, all outlets, selected outlets, all with no start delay; the 2026-08-20 decompile was of an older build and reported only two, and this valve's own captures settle it. **Write three, decode five.** Exposed as `select.anthem_valve_warmup`. ⚠️ Something outside Home Assistant keeps setting it back to off — §3e — §3f documents the diagnostic switch that puts it back a minute later, off by default, and **§3g the `warmup_*.jsonl` journal that is trying to catch the culprit** — on by default, one record per mode change plus a 120 s before / 60 s after window of wire traffic around every disable. |
| [`hub/cloud_api.md`](hub/cloud_api.md) | HUB cloud REST: favourites CRUD, control, experiences, lighting, music, read shapes. |
| [`hub/local_api.md`](hub/local_api.md) | HUB **local** LAN API: PIN→JWT auth, `req_update_command`, Zigbee pairing, Control4 channel. Config and diagnostics only. |
| [`hub/lighting.md`](hub/lighting.md) | **❌ Zigbee lighting cannot be paired locally on fw 2.88 — live-tested 2026-08-15.** A Hue Zigbee 3.0 bulb never joined the hub's coordinator, while the same bulb joined Zigbee2MQTT in 13 s with the hub's own window still open. Rules out the §5.6 UI bug, payload shape, radio state, window length, reset state, range and coordinator competition. *Why* is unknowable from here: the local API has **no error surface at all** and `get_error_log` times out at 170 s. Also: the "accept the risk" prompt is client-side only and makes no API call, and no command anywhere changes Zigbee security mode. ⚠️ Contains the touchlink/InterPAN trap that froze the whole house's Zigbee network. |
| [`case_studies/`](case_studies/) | Complete, fully-quoted single-session walkthroughs. **For max shower duration, read [`case_studies/conclusions.md`](case_studies/conclusions.md) first** — it synthesises all seven into one place: both devices' settings and signals, the measured timing (valve **−0.08 to −0.23 s early**, controller **+0.30 to +1.25 s late**, never overlapping), the controller's **sweep** and its ⭐ **zone-1 disarm bug**, and the six distinct controller faults with the figures behind each. Then **[`case_studies/intro.md`](case_studies/intro.md)** — it carries the framing every one of them depends on: ⚠️ **MQTT is the Konnect app's UI channel, not device communication.** The real device-to-device link is the RJ wired connection, which cannot be sniffed, so an absent message means "no card change to push", never "a device was silent or broken". It also holds the command-surface table, the three classes of evidence, and the scope exclusions. **[1 — an 86-minute shower the Anthem Plus never knew about](case_studies/01_ha_driven_shower_hub_blind.md)** (2026-08-18): a `solowritesystem`-driven shower, the valve's own 3600 s pause, Home Assistant's restore, and a touchscreen stop — during which the controller published **zero** MQTT messages. Establishes that **the HUB's 60-minute ceiling does not count when Home Assistant starts the shower**, closing one row of session 9's open table. §6a rules out the obvious objection: **the connection was healthy throughout** — one unbroken MQTT session carrying both devices, valve messages arriving at the very instants the controller should have spoken, and the controller alive enough to end the shower from its own touchscreen. Every record quoted in full, plus an appendix covering the hour either side. **[2 — the controller-commanded shower and its 15-minute ceiling](case_studies/02_hub_commanded_shower_15min.md)** (2026-08-18): the mirror image — started with the HUB's `valveOnOff`, so the controller owns the session, its clock runs, it cuts at exactly its configured 15 min with a `0x00` stop, and it reports every transition including `status: ON`. **Warm-up counts toward the ceiling** and carries no pause. Read together, the two establish the command surface: which device owns a shower is fixed at the moment water starts. Also closes session 9's open item 2 — **`maxshowerduration` is readable over the local API**. **[3 — both ceilings at 15 minutes](case_studies/03_both_ceilings_at_15_minutes.md)**: the control. Both devices fired — valve `0x40` at 899.918 s, controller `0x00` at 901.004 s, 1.087 s apart, neither deferring. **That closes case study 1**: a ceiling enforced unconditionally, which did not fire across 86 minutes there, proves the controller never knew the shower existed. **[4 — the two touchscreens, and what "off" means](case_studies/04_two_touchscreens_and_what_off_means.md)**: **the first-generation screen's OFF writes `0x40`, a pause on both zones, and that pause self-terminates into `0x00` after ~2 minutes** — a fifth timer. `atTemp` is inert. And the controller acknowledged an HA-driven open in 285 ms, amending case study 1's mechanism: **why it sometimes registers a shower and sometimes does not is the open question across all four.** **[5 — three restarts and the unexplained `00/00`](case_studies/05_three_restarts_and_the_unexplained_00.md)**: restarts 1 and 3 normal, restart 2 not — an unexplained `00/00` merged the two zones' independent run-time clocks, which caused restart 3. Establishes `configWriteAllowedFlag` as the valve's idle marker and the only window into state the command word does not carry; records that **the controller pushed a zone state the valve never held**; and retracts case study 3's `00/00` attribution. **[6 — two cutoffs, and a prediction that failed](case_studies/06_two_cutoffs_and_a_prediction_that_failed.md)** (2026-08-18 evening): the first live shower on the reverted `0x40`-required code — **both zones cut at 900 s, both carried the pause flag, both were restored, flow and temperature byte-exact**, and the controller's `0x00` landed 0.323 s behind the valve's, confirming session 10's matched-durations fix on hardware. Per-zone clocks confirmed to **0.013 s**. It then records three successive theories about when a `0x40` becomes `0x00`, all wrong, all built on **58 of the corpus's 90 capture files** — ⚠️ **the corpus spans five directories and two JSON schemas; print its file count and date range before trusting any claim of the form "across the corpus".** `kohler-work/pause_resolution.py` reads both schemas and prints them on every run. **[7 — the controller sweeps](case_studies/07_the_controller_sweeps.md)** (2026-08-19): three showers with the **HUB at 15 min and the valve at 60 min**, making the controller the sole authority — and it shows the controller's max-duration cutoff is a **software sweep, not a timer per zone**: it arms timers on events, and when one fires it checks every zone and cuts each one at or over the limit (15 of 16 decisions). A zone whose timer never armed runs on unnoticed — zone 1 overran its limit by up to **13 minutes** — and is cut only as collateral. The controller's stop is `0x00`, **never** `0x40`, and always late by **+0.30 to +1.25 s**. It resolves case study 5's unexplained `00/00`, undoes session 10's retraction of case study 3, and establishes that **a shower session ends ~120 s after all water stops** — with the valve and the controller ending their sessions independently, each with its own summary screen. |
| [`mqtt/capture_runbook.md`](mqtt/capture_runbook.md) | Event-driven MQTT bridge: subscriptions, message codes, HA bridge topics. |
| `handoff/` | **Not in this repository.** Session handoffs are working notes for continuing the project — a running record of what changed, what was verified on hardware, and what is still open. They are kept locally and deliberately not published: they are of little use to anyone else and they carry personal details. A session picking this project up reads the most recently dated file in `docs/handoff/` on disk. Everything in them that is a *finding* rather than a status note belongs in the documents above, and is there. |
| `kohler-work/tests/` | Regression harnesses — at **`/homeassistant/scripts/kohler-work/tests/`**, outside this repo, so there is no link to follow. The ones needing no credentials replay captured data offline; run them with `tests/run_offline.sh`, **never** a `test_*.py` glob. |

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
