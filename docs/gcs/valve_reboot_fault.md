# Valve reboot fault — 2026-08-14

> ## ✅ ROOT CAUSE CONFIRMED — 2026-08-15 — read §3d before anything else
>
> **The Moes smart outlet in the bedroom closet was powering the Anthem gear, and it is what
> reboots both devices.** Home Assistant *can* see it, and has been recording it for ten days:
> **`switch.bedroom_closet_lower_outlet`.**
>
> **Ten deliberate off→on cycles of that socket, ten valve reboots, every one at +18 or +19
> seconds. No exceptions inside capture coverage.** The 08-11 cluster — six reboots that this
> document treated as its strongest evidence the fault was device-side — is six manual power
> cycles of that socket. Full proof in **§3d**.
>
> A negative control comes free: the sibling socket `…_tuya_motion_2_usb_a` runs a daily
> five-minute off cycle and has **never** rebooted anything. It is that one socket, not "Tuya
> events" in general.
>
> **Nothing was ever wrong with the Kohler hardware, and nothing was ever wrong with this
> integration.** That is also why two factory resets changed nothing — neither reset touched the
> power source.
>
> **The valve is already fixed:** moved off that outlet, it has been clean for 6+ hours through
> four separate controller outages. **The controller is still on it and is still rebooting** —
> four times on the evening of 08-14, the most recent while this was being written.
>
> Everything below predates this finding. Read it as the evidence trail that led here, not as
> current best understanding.

**Status: root cause confirmed 2026-08-15; the fix is to move the controller's plug.**
Device-side, never caused by this integration. **TWO factory resets did not fix it** — see §5a and §2 — which is
now explained: neither reset touched the power source. The second reset left the valve
uncalibrated, preset-free, and with a single interface attached; it still rebooted twice after
15 and 51 minutes of total silence.

This document records the evidence from both before and after that reset. §5b holds the
owner's current mitigation and the open experiment; leave it running before changing anything.

> **The integration now counts reboots.** Since 2026-08-15 `DEVICE_REBOOT_STS` is consumed:
> `sensor.anthem_valve_valve_reboots` (`TOTAL_INCREASING`, enabled by default, persisted to the
> config entry so it survives restarts), a WARNING in `home-assistant.log` on every reboot with
> the interval since the last, and a `valve_reboot` record in the cutoff debug log carrying
> `hub_reachable` at that instant. Earlier revisions of this document said the constant
> `MSG_GCS_REBOOT` existed but nothing consumed it — **that is no longer true.**
>
> A 1 Hz reachability probe against the controller's local HTTP server
> (`binary_sensor.anthem_plus_controller_local_api`,
> `sensor.anthem_plus_controller_local_outages`) is also armed, to answer whether the HUB goes
> down with the valve. It is off unless a LAN address is configured.
>
> **⭐ It has already earned its keep — see §3c.** On 2026-08-14 at 20:07 it caught the
> **controller restarting by itself while the valve stayed up**: the first single-device event
> in this whole investigation.
>
> ⚠️ **An earlier revision of this block claimed the counter undercounts. RETRACTED** — that was
> based on misreading the 20:07 event as a missed valve reboot. The valve did not reboot, no
> message was lost, and `gcs_reboot_count` was correct. The counter has no known defect. Full
> reasoning and the `configChangeIndent` test in §3c.

### Owner-side variable introduced 2026-08-14

The outlet the valve is plugged into was **moved to a different location**, and the owner
performed roughly **5–6 deliberate reboots** that day. Both must be subtracted before reading
the rate in §2: of 14 `DEVICE_REBOOT_STS` captured on 08-14, only ~8–9 are spontaneous.

Baseline for judging the outlet move — the gaps between reboots on 08-14 were
`65.8, 10.7, 91.9, 3.4, 14.1, 70.7, 14.2, 84.5, 38.2, 53.7, 81.2, 36.2, 26.9` minutes. **The
longest quiet stretch that day was 91.9 minutes**, so any clean run materially past that is the
first real evidence the outlet was the cause.

Last reboot: **2026-08-15T00:00:47Z** (17:00:47 local) — the *expected* config-completion
reboot described below, not a spontaneous one. **The last spontaneous reboot is
2026-08-14T23:33:49Z (16:33:49 local).**

> ### 🟢 Clean run in progress — four hours and counting
>
> As of 2026-08-15T03:40Z (20:40 local) the valve has not rebooted spontaneously for **over four
> hours**, against a previous best of 91.9 minutes. **This is the strongest evidence so far that
> relocating the valve's mains outlet was the fix.**
>
> Do not be misled by the 20:07 controller event — that was the **HUB restarting alone**, with
> the valve up throughout (§3c). It does not interrupt this clean run.

Cross-check against water: of 26 captured reboots, **17 occurred idle, 4 with water running,
5 indeterminate** — so flow is not the trigger.

Raw evidence archived at
`/homeassistant/scripts/kohler-work/captures/2026-08-14_valve_reboot_fault/` — the two MQTT
captures, both cutoff debug logs, and `device_state_before_factory_reset.json`.

> **File retention changed 2026-08-15.** `RAW_MQTT_LOG_KEEP_FILES` and
> `CUTOFF_DEBUG_LOG_KEEP_FILES` are now `None` — **no limit on the number of files**, at the
> owner's request, because this investigation needs a permanent record rather than a rotating
> buffer. Earlier revisions of this document said the directory prunes to the newest 20; that
> is no longer true. Per-file size caps are unchanged. The archive above is still the tidier
> copy, but it is no longer the *only* durable one.

---

> **Timezone.** Every time in this document is **local (UTC−7)**. The raw `.jsonl` captures
> store **UTC**, and several older flow documents quote bare UTC timestamps with no marker —
> so a "02:00" event in [`api.md`](api.md) is 19:00 the previous evening, local.

## 1. What happens

The valve emits `DEVICE_REBOOT_STS` and restarts, unprompted. Water stops if it was running.
The reboot recovery sequence is byte-identical every time:

```text
+0.0s   DEVICE_REBOOT_STS
+0.5s   01844500 / 1184A500     preset 1's stored word (34.5% / 82.5%)
+3.5s   GCS_WARM_STS  warmUpDisabled
+4.6s   6x READ_GCS_OUTLET_CONFIG_CFG, maximumRunTime=3600
+13s    READ_ALL_INTERFACES_FIRMWARE_VERSION_STATUS_INFO
+14s    10x GCS_PRESET_STS
+20s    experience, UI x2, firmware again
+71s    0000C800 / 1000C800     <- BOTH VALVES REPORT 0.0 C
+88s    0184C800 / 1184C800     recovered, 101.8 F
+95s    HUB snapshots, SYSTEM_STS SYSTEM_READY
+107s   01844500 / 1184A500     idle
```

Note the state at +71 s: **a minute after finishing its config dump the valve reports 0.0 °C
on both zones for 17 seconds**, then recovers. It signals readiness before it is ready.

> **The `+0.5 s` and `+107 s` frames may be the flow *ceiling*, not preset 1.** Both carry
> `45`/`A5` in byte 2 — 34.5% / 82.5% — which is exactly this install's calibrated ceiling pair
> for that era, and the valve is now known to broadcast its ceiling in byte 2 while stopped or
> paused, reverting to `0xC8` afterwards. See
> [`valve_hex.md`](valve_hex.md#how-the-ceiling-is-observed-the-byte-2-dip). The two readings
> cannot be told apart from these captures because preset 1's stored flow and the ceiling
> happened to be the same numbers.
>
> Post-second-reset the valve is **both** preset-free and uncalibrated and these frames no
> longer appear at all — byte 2 is now `0xC8` permanently — so that test does not separate them
> either. Recorded 2026-08-15 so a future session does not assume the preset reading is settled.
>
> **The clean experiment, for whoever gets there first:** preset 1 was recreated on
> 2026-08-15 storing `0184c8`/`0584c8` — flow **100%**, not a ceiling. **Calibrate the valve
> without touching preset 1.** Preset 1 then holds `C8` while the ceiling is something else, and
> the next reboot's `+0.5 s` / `+107 s` frames say which one they are. Until then both readings
> remain live.

### Preset 1 exists again — 2026-08-15

The owner finished the default-outlet setup, which recreated preset 1 "Default shower" at
`00:00:04Z`.

> **The reboot 43 s later at `00:00:47Z` is EXPECTED, not a fault instance.** Per the owner:
> the system reboots itself on purpose once it has finished writing a configuration. **Exclude
> it from any reboot-rate calculation** — it belongs with the deliberate power-cycles in §2, not
> with the spontaneous reboots this document is about. A config-completion reboot is a normal
> device behaviour and is the expected tail of any setup wizard run.

Its stored values differ from every pre-reset capture and are themselves evidence:

| When | `time` | Valve1 | Valve2 |
|---|---|---|---|
| pre-reset (08-13/08-14) | `3600` | `018445` / `018447` — **34.5% / 35.5%** | `0584a5` / `05849e` — **82.5% / 79.0%** |
| wiped (08-14 20:04) | `0` | `000000` | `000000` |
| recreated (08-15 00:20) | **`1800`** | `0184c8` — **100%** | `0584c8` — **100%** |

Two things follow. The preset now stores **100%** rather than a ceiling, matching the
uncalibrated-valve finding in
[`valve_hex.md`](valve_hex.md#an-uncalibrated-valve-has-no-ceiling--measured-2026-08-15). And
its `time` is **1800 — 30 minutes**, the valve's own default, which the owner reports
**overrides the max shower time set on the HUB**. The valve re-announces `maximumRunTime` for
all six outlets within **5–11 seconds of every reboot**, so a run-time limit set on the panel
can silently revert after any reboot — a direct interaction between this fault and the "keep
shower on" feature. Detail in
[`../handoff/2026-08-14_session6_current.md`](../handoff/2026-08-14_session6_current.md).

No error is ever reported. `errorCode: null`, `errorstate: 0`, `currentSystemState:
normalOperation` throughout, and the HUB reports `SYSTEM_READY`.

## 2. Rate — and it started a week before it was noticed

> **CORRECTED 2026-08-14.** An earlier revision of this section listed 15 reboots and said the
> fault "began 2026-08-13". Both were wrong: that count came from the integration's own
> capture directory only. Including the **older bridge corpus** in
> `scripts/kohler_konnect_custom/log/` gives **25 reboots, the first on 2026-08-07** — and a
> cluster of six on 08-11, before most of the work in this project existed.

| Reboot (local) | Gap | Attribution |
|---|---|---|
| 08-07 22:44:41 | — | unattributed |
| 08-11 10:52:12 | 5047.5 min | unattributed |
| 08-11 10:53:48 | **1.6 min** | unattributed |
| 08-11 10:54:40 | **0.9 min** | unattributed |
| 08-11 10:56:06 | **1.4 min** | unattributed |
| 08-11 11:51:30 | 55.4 min | unattributed |
| 08-11 11:53:09 | **1.7 min** | unattributed |
| 08-13 12:41:43 | 2928.6 min | **owner — deliberate power-cycle** to force the outlet-config dump (recorded in [`api.md`](api.md#a-valve-reboot-dumps-the-complete-set--the-only-known-way-to-force-it)) |
| 08-13 17:15:07 | 273.4 min | unattributed |
| 08-13 17:16:10 | **1.0 min** | unattributed |
| 08-14 06:00:20 | 764.2 min | unattributed |
| 08-14 06:26:41 | 26.4 min | **owner confirms NOT theirs** |
| 08-14 06:30:24 | 3.7 min | owner was intervening this morning; individual attribution unknown |
| 08-14 06:41:46 | 11.4 min | ditto |
| 08-14 06:49:05 | 7.3 min | ditto |
| 08-14 06:49:38 | **0.5 min** | ditto |
| 08-14 06:53:58 | 4.3 min | ditto |
| 08-14 06:59:57 | 6.0 min | ditto |
| 08-14 07:00:33 | **0.6 min** | ditto |
| 08-14 07:08:59 | 8.4 min | ditto |
| 08-14 08:14:48 | 65.8 min | **not owner** — idle, no command for 1 h 23 min |
| 08-14 08:25:31 | 10.7 min | **not owner** — idle, no command for 1 h 34 min |
| 08-14 09:57:27 | 91.9 min | after the **first** factory reset |
| 08-14 10:00:53 | **3.4 min** | after the first factory reset |
| 08-14 10:15:01 | 14.1 min | after the first factory reset |
| 08-14 11:25:45 | 70.7 min | idle — **368 s of total silence**, no command for 4.5 h |
| 08-14 13:04:31 | 98.8 min | after the **second** factory reset; owner may have power-cycled |
| 08-14 13:42:43 | 38.2 min | **924 s of silence** — single interface, uncalibrated valve |
| 08-14 14:36:27 | 53.7 min | **3079 s (51 min) of silence** — single interface, uncalibrated valve |

**1 on 08-07, 6 on 08-11, 3 on 08-13, 19 on 08-14.** Seven of them arrive within two minutes
of the preceding one — the valve rebooting again before it has finished recovering.

Only **one** reboot in the whole record is known to be deliberate (08-13 12:41:43). One is
positively confirmed as *not* the owner, and two more happened while the system had been idle
and uncommanded for over an hour.

### The second factory reset, with the first-gen screen removed

**2026-08-14 ~13:00.** Both devices factory reset again. GCS setup **skipped entirely** (so
the valve was never calibrated, and has **no presets at all**), HUB calibrated with flow
control on, and the **first-gen K-28214 touchscreen left disconnected** — confirmed by
`UserInterface1` firmware dropping from `2.2` to `0.0`.

**It rebooted twice more**, after 15 minutes and 51 minutes of complete silence:

```text
13:42:43   924 s since the previous message of any kind
14:36:27  3079 s since the previous message of any kind
```

**That is a factory-clean, uncalibrated valve with a single interface attached, no presets,
and nothing being sent to it — still rebooting.** It substantially weakens the two-interface
hypothesis in §3b, which is left standing only because nothing positively excludes it either.

Evidence: `captures/2026-08-14_uncalibrated_valve_test/`.

### Why the 08-11 cluster matters

Four reboots inside four minutes on 2026-08-11, then two more an hour later. That is **before
the run-time cutoff feature existed**, before any automatic restore had ever fired, and before
the integration had written a flow byte in any cutoff context. The same rapid-repeat signature
as 2026-08-14. Whatever this is, it predates essentially all of the work listed in §3a.

## 3. Why it is not the integration

The decisive sample is **08-14 08:25:31**:

* No water running — the valve had been idle since 06:53.
* **No command of any kind for 1 h 34 min** (last `GCS_RECIEVED_STS` 06:51:31).
* **No Home Assistant write for 2 h 01 min** (last write 06:24:32, the cutoff restore).

A valve that reboots while completely untouched is not reacting to anything sent. Supporting
points:

* Home Assistant wrote to the valve **once** on 08-14 — the restore at 06:24:32. The HA log
  contains no other write.
* This integration has **no reboot capability**. `MSG_GCS_REBOOT` exists in
  `anthem_plus/const.py` as a message code to *recognise*; nothing sends one.
* Of the 15 reboots on 08-14, **9 occurred with the valve idle**.
* **6 reboots occurred on 2026-08-11**, before the run-time cutoff feature existed at all
  (§2). Four of those inside four minutes.

### The over-ceiling write hypothesis — investigated and not supported

The owner proposed a specific mechanism, and it deserved the test it got: preset 1 stores a
per-zone flow *ceiling* (see [`api.md`](api.md#flow-the-valve-obeys-the-touchscreen-is-what-computes-limits));
the cutoff pauses and clears the preset but the ceiling does not reset; the restore then
writes 200 (100%) to both zones, which is **2.90x** zone 1's stored 69 and **1.21x** zone 2's
165. That exact combination had never occurred before, and the live tests behind "the valve
honours what you write" only ever wrote *downward* (37%, 50%) — so nothing in the prior
evidence excluded it.

What decided it:

| Evidence | Effect on the hypothesis |
|---|---|
| Restore at 06:24:32 → reboot 128.6 s later | consistent with it |
| Session 06:51:31–06:53:58 ran at **82.5%**, inside the ceiling, no HA write — ended at a reboot | over-ceiling write is **not necessary** |
| 9 of 15 reboots on 08-14 with the valve idle and nothing written | not necessary |
| **6 reboots on 08-11**, before the cutoff feature existed | not necessary |
| The single worst day of flow thrashing (08-12) produced **zero** reboots | not sufficient either |
| **08:25:31 reboot, 2 h after any write** | **decisive** |

Base rates also matter: on the morning of 08-14 the valve rebooted every ~7 minutes, so *any*
event was ~128 s from a reboot. The 128.6 s figure is unremarkable inside the observed spread
(130, 588, 369, 150, 175, 266, 67, 412, 213 s).

**The hypothesis is not supported, but it was well-formed and the reasoning was sound.** It is
recorded here so nobody re-derives it from scratch, and because it remains the correct read of
the *flow* defect in §5 even though it does not explain the reboots.

## 3a. Everything done to the integration since 2026-08-13

Listed so a reader can see exactly what changed on **our** side while the valve was
degrading — and satisfy themselves that none of it can reboot a valve.

**The integration's only write to the valve is `solowritesystem`**: a per-zone hex word
carrying temperature, flow, and an outlet mask. It has never written outlet configuration,
calibration, presets, or firmware, and it has **no reboot capability at all** —
`MSG_GCS_REBOOT` in `anthem_plus/const.py` exists only to *recognise* the message.

### Session 5 — 2026-08-13

| Change | Touches the valve? |
|---|---|
| Reauth on a rejected credential (`AuthUnavailable`, `async_start_reauth`) | no |
| Confirmed the MQTT identity is persisted, not re-registered per connect | no |
| Raw MQTT capture rebuilt inside the integration (`raw_log.py`) + roll button | no — read only |
| Controller diagnostics: MQTT connection, Last Update, Controller Status sensor | no |
| Warm-up merged into the valve Status sensor | no |
| **Flow no longer inherits** — every write forces `DEFAULT_FLOW_PERCENT` (100%) | **yes**, on writes the user initiates |
| `kohler_anthem_plus.send_valve_hex` action | **yes**, when called |
| **Run-time cutoff restart** option + Keep water running switch (per-outlet detection at this point) | **yes**, on a detected cutoff |
| Shower switch OFF changed from `0x40` pause to `0x00` stop | **yes**, when switched off |
| Temperature sliders bounded 80–113 °F; `HEAT` device class | no — UI gate only |
| `tests/run_offline.sh` allowlist runner, after a test accidentally ran water | no |

### Session 6 — 2026-08-14

| Change | Touches the valve? |
|---|---|
| Cutoff detector rewritten **zone-based** (`ZoneCutoffDetector`) | detection only |
| **Cutoff debug log** (`cutoff_log.py`) | no — read only |
| Restore also covers the preset case (`also_paused`) | **yes**, on a detected cutoff |
| Readiness reported per zone (`armed_zones`) | no |
| `MissedCutoffWatcher` — limit inference, **diagnostic only**, gated by `ACT_ON_LEARNED_LIMITS = False` | no |
| Local-write grace fixed — per-zone, and only *closing* writes earn it | detection only |
| New entities: Zone 1 Active, Zone 2 Active, Preset Active | no |
| `flow_is_live` attribute on the Zone Hex sensors | no |
| Flow % and °F captured into the cutoff log (`ZoneReading`) | no |

**Total writes the integration made to the valve on 2026-08-14: one.** The cutoff restore at
06:24:32. The Home Assistant log contains no other write that day.

### Owner-side actions over the same period

| When | What |
|---|---|
| 08-12 ~16:00–19:00 | **Flow control enabled on the GCS touchscreen.** Flow thrashing: 34 distinct flow values in one hour, full 8–100% sweeps, both zones rewritten by the panel |
| 08-13 12:41:43 | Deliberate power-cycle to force the outlet-config dump |
| 08-13 | `maximumRunTime` changed **3600 → 900 s** for cutoff testing; presets created/edited ("Test twozone") |
| 08-14 06:46:03 | `maximumRunTime` changed back **900 → 3600 s** |
| 08-14 ~06:26–07:09 | Repeated interventions during the failing showers |
| 08-14 ~09:40 | **Factory reset of both devices**, integration re-added |
| 08-14 ~10:00 | **Flow control disabled on both GCS and HUB**; Keep water running left off |

### The flow-control timeline argues against flow as the trigger

The owner's hypothesis was that over-driving a zone past its flow ceiling stresses the valve.
The dates do not support it:

```text
08-11    6 reboots     flow control NOT yet enabled on the GCS screen
08-12    0 reboots     flow control enabled; the single worst day of flow thrashing
                       (34 distinct values, 8-100% sweeps, panel rewriting both zones)
08-13    3 reboots
08-14   15 reboots     flow control disabled ~10:00 — reboots continued after
```

**The day of maximum flow abuse produced zero reboots**, and six reboots preceded flow control
being enabled at all. Combined with the 613 captured samples of a zone flowing at byte 200
(above its ceiling) across days with no reboots, and with the reboots that occur while idle
and uncommanded, flow is not the trigger.

## 3b. Open candidate: two interface ports in use at once

**Proposed by the owner 2026-08-14. Not contradicted by anything, and — unlike the flow
hypothesis — not testable from these captures.** It is currently the strongest surviving
explanation.

The valve has **two interface ports**, and this install uses both:

| Port | What is on it |
|---|---|
| 1 | **First-gen K-28214 touchscreen** — an input/display *peripheral*. Reports touches, renders state, and can tell the valve to open its setup AP. No control logic. |
| 2 | **Anthem Plus (HUB)** — a separate Linux system controller with its own screen, its own cloud identity, and its own calibration |

Kohler ships these as **separate systems**; the manual does not document connecting both to
one valve. The owner wired it that way during installation without it being called out as
unusual. See
[`../architecture.md`](../architecture.md#the-first-gen-touchscreen-is-a-peripheral-not-a-controller).

### Why the captures cannot settle it

**This capture sees cloud MQTT only. The HUB↔valve connection is a wire, and everything on
it is invisible to us** — no capture, no log, no entity. A disagreement between the HUB and
the valve over that link would produce exactly what is observed: a valve that reboots in
apparent silence.

The two cleanest samples had no cloud traffic at all from either device:

```text
reboot 10:15:01    5 min before:  0 GCS msgs,  0 HUB msgs
reboot 11:25:45    5 min before:  0 GCS msgs,  0 HUB msgs   (368 s of total silence)
```

### Supporting observations, none conclusive

* The valve reports **one** user interface, not two. `UserInterface1` firmware `2.2`;
  `UserInterface2` firmware **`0.0`** with a config block otherwise identical to UI1 —
  matching `SecondaryValve2`–`7`, which report `0` and are known absent. **The HUB is not one
  of the valve's UI slots**; it is a separate device on the second port.
* The reboots survived a **full factory reset of both devices** (§5a) — consistent with a
  wiring/topology cause rather than a configuration one.
* They predate essentially all integration work, including the 08-11 cluster (§2).
* No error is ever reported on the cloud side, which fits a fault on a channel the cloud
  never sees.

### ⚠️ The flow bug is NOT evidence for this — retracted 2026-08-14

An earlier revision of this section argued that the "2.88 flow bug" shared this root cause,
and treated that as raising the prior on the topology hypothesis. **A direct test disproved
the shared cause**, and the argument is withdrawn.

The owner ran HUB flow control **with the first-gen touchscreen disconnected**, and the
double-scaling still occurred — measured, linear, factor 0.20 on zone 2 and 0.10 on zone 1
([`../architecture.md`](../architecture.md#why-hub-flow-control-is-broken-double-calibration--measured-2026-08-14)).
So the flow bug is unconditional whenever a HUB drives a calibrated valve; it has nothing to
do with both interface ports being occupied.

That leaves the topology hypothesis standing on its own evidence, which is weaker: it is
*consistent* with reboots that have no visible cause, and it remains the only channel never
observed, but nothing positively supports it.

<details>
<summary>The retracted argument</summary>

### The same topology may also explain the "2.88 flow bug"

Worth noting because it raises the prior on this hypothesis: the owner has proposed that
**HUB flow control is broken for the same reason** — both devices hold their own calibration,
so a HUB-driven flow command gets scaled twice, landing zone 1 at ~12.6% of what was asked
for. That is the "flow is so weak" symptom which led to flow control being disabled
system-wide as the recommended workaround.

If that is right, the long-standing "firmware 2.88 flow bug" is not a firmware defect at all
— it is two calibration stages in series, appearing **only** on installs wired like this one.
Mechanism and the one-shower test in
[`../architecture.md`](../architecture.md#why-hub-flow-control-may-be-broken-double-calibration).

Two unexplained faults on one system, both with a plausible single cause in the topology, is
a stronger position than either on its own.

</details>

### How to actually test it

**Physically remove one master.** Disconnect the HUB from the valve's second port, *or*
disconnect the first-gen screen, and leave it for a day. At the current rate — roughly one
reboot per hour — a clean day would be strong evidence, and a continued fault would clear the
topology entirely.

This is also the first thing a Kohler support conversation is likely to raise, so it is worth
having the answer before being asked.

## 3c. ⭐ FIRST HUB-ONLY RESTART — the valve did NOT reboot (2026-08-14 20:07)

**The controller restarted by itself and the valve stayed up throughout.** This is the first
observation of either device restarting alone; every prior event in this document had both
going down together. It is a *new failure mode*, and it points at the controller rather than at
a shared cause.

```text
20:07        controller stops answering its local HTTP server   (probe + owner-confirmed)
20:09        controller answering again
20:09:35.9   valve emits a frame with temperature ZEROED — but its state otherwise unchanged
20:09:52.9   valve configChangeIndent 6 -> 1: a config RELOAD begins, after the HUB is back
20:09:57+    HUB snapshot burst
20:10:00.1   HUB SYSTEM_STS SYSTEM_READY
```

### How we know the valve did not reboot — two independent proofs

**1. The MQTT link never dropped.** `binary_sensor.anthem_plus_mqtt_connection` reads `on`
continuously from 13:02:20 through the entire event. **No message could have been lost**, so the
absence of `DEVICE_REBOOT_STS` means it was never sent. `sensor.anthem_valve_valve_reboots`
correctly reads 2 (16:33:49 and the 17:00:47 config reboot) and did not increment.

**2. `configChangeIndent` never reset.** A valve reboot drives it to `1` within a second of
`DEVICE_REBOOT_STS`, and it is still `1` when the 0.0 °C frame arrives — **17 out of 17**.

| | indent at the 0.0 °C frame |
|---|---|
| 17 confirmed valve reboots | **1** |
| this event | **6** |

The whole state carried across the gap unchanged:

```text
18:16:24  last message before the silence   indent=6  totalFlow=477  totalVolume=536929728
20:09:35  the 0.0 C frame                   indent=6  totalFlow=477  totalVolume=536929728
```

Identical in every state field except the zeroed temperature. A rebooted valve cannot present
its pre-gap `configChangeIndent` and counters. The **ordering** confirms it: in a valve reboot
`indent -> 1` precedes the 0.0 °C frame by ~90 s; here it *followed* by 17 s — a config reload
provoked by the controller returning, not a boot sequence.

### The outage, timed to the second

From the recorder — **these are durable**, HA keeps entity state history even though the
sensor's own outage list is in memory:

```text
binary_sensor.anthem_plus_controller_local_api   on -> off 20:07:51 -> on 20:09:41
sensor.anthem_plus_controller_local_outages      0 -> 1
```

First failed poll ~**20:07:49** (declared after three, back-dated); recovered **20:09:41**.
**Duration ~110 s.**

**110 s is a boot time, not a network blip** — and the controller published `SYSTEM_STS:
SYSTEM_READY` with its full 11-snapshot set on the way back, which is a startup sequence.
**The controller power-cycled.**

Note the valve saw the wired link return *before* the web server did: 0.0 °C frame at 20:09:35,
config reload at 20:09:52, HTTP answering at 20:09:41.

### ⭐ Leading hypothesis: the controller's smart outlet

**Owner-reported 2026-08-15, and it explains the entire fault history:**

> **The valve and the controller were both plugged into the same Moes smart Wi-Fi outlet.** The
> valve has since been moved to a plain outlet on a different circuit. **The controller is still
> on that smart outlet.**

| | before | after the valve was moved |
|---|---|---|
| **Valve** — was on the smart outlet | rebooting roughly hourly | **4+ hours clean** vs 91.9 min best |
| **Controller** — still on the smart outlet | went down with the valve every time | **restarted alone at 20:07** |

**This retires §3b.** The reason both devices always went down together — the observation that
drove the two-interface hypothesis through two sessions and two factory resets — is that **one
smart plug was powering both of them**. There was never a shared *Kohler* cause. The first event
after they were separated behaved exactly as that model predicts: the controller alone
power-cycled for ~110 s while the valve stayed up, verified two independent ways above.

A smart plug that glitches its relay, browns out, or reboots its own firmware produces precisely
a ~110 s power-cycle of whatever is plugged into it.

⚠️ **`switch.bathroom_countdown_switch` is NOT this outlet.** It is on a different circuit
entirely, and it read `on` continuously from 18:14:42 to 20:13:58. An earlier revision of this
section treated its history as evidence; that was wrong. Discard it.

### ⭐ 3c-bis. The Moes blip is NOT a coincidence — 2 for 2 (session 7, 2026-08-15)

> **RETRACTION.** The paragraph above said the Bedroom Closet Tuya blip at 20:07:47 was
> "unrelated" and that there was "no network-wide event". **Both statements are withdrawn.** The
> owner has since confirmed **those entities are the same Moes Tuya smart outlets** as the plug
> the controller is on. It was dismissed on a sample of one; a second controller outage arrived
> 73 minutes later with the same signature.

A second outage at **04:20:52Z (21:20 local)**, `110.6 s` — **identical to the first to the
tenth of a second**. Both are preceded by a Moes blip ~2 s earlier:

| | Moes blip | controller down | duration |
|---|---|---|---|
| #1 | `03:07:47.0Z` for **1.9 s** | `03:07:51Z` → `03:09:41Z` | **110.6 s** |
| #2 | `04:20:48.4Z` for **2.1 s** | `04:20:52Z` → `04:22:42Z` | **110.6 s** |

**Blip duration is the discriminator.** Across the whole window in which the probe has existed:

| Moes blip length | count | controller outage followed |
|---|---|---|
| ≤ 1.3 s | 7 | **none** |
| ≥ 1.9 s | 2 | **both** |

No outage occurred without a blip, and no long blip occurred without an outage. The short blips
cluster around Home Assistant restarts and integration reloads — ordinary Tuya reconnects.

⚠️ **Coverage caveat, and it matters.** The probe only exists from `2026-08-14 23:53:02Z`.
Nine earlier blips in the same day — including ones of **4.0 s, 2.4 s and 2.1 s** — fall
*before* any controller instrumentation existed, so they are neither evidence for nor against.
The first run of the correlation script reported them as counterexamples; that was a bug in the
script, since fixed. Do not quote them either way.

### The controller genuinely reboots — it is not just unreachable

The probe measures HTTP reachability, so an outage could in principle be a network gap rather
than a restart. **It is a restart.** Both outages end with the controller announcing itself on
MQTT and re-emitting its entire snapshot set:

```text
04:22:42Z   local HTTP server answering again
04:22:58Z   HUB-SYSSTS       SYSTEM_STS -> SYSTEM_READY      <- boot announcement
04:23:00Z   HUB-GDTXLLDD     STATUS_SNAPSHOT
04:23:00Z   HUB-INRB916T7R   FAVORITES_SNAPSHOT
04:23:00Z   HUB-SH8EXPSNP    SHOWER_EXP_SNAPSHOT
04:23:01Z   HUB-STM8EXPSNP   STEAM_EXP_SNAPSHOT
04:23:03Z   HUB-ISHEXPSNP    ICE_SHOWER_EXP_SNAPSHOT
```

The same sequence, in the same order, follows outage #1 (`SYSTEM_READY` at `03:10:00Z`). Note
the HTTP server answers **~16 s before** `SYSTEM_READY` reaches the cloud — normal boot
ordering, and worth knowing when timing these against MQTT.

**A full boot announcement twice, with identical downtime, is a power-cycle** — not a Wi-Fi
drop, which would neither reboot the device nor take the same 110.6 s twice.

### What this does and does not settle

**Strengthened:** the valve and controller are now genuinely decoupled. Both outages left the
valve untouched — `gcs_reboot_count` stayed at 2 and its MQTT session never dropped.

**Changed:** the cause is no longer necessarily *that individual plug*. The Moes fleet loses its
link in the same instant, so the shared factor is whatever the Moes outlets have in common — the
Tuya cloud/LAN link, their Wi-Fi, or a mains event affecting several of them. A brief loss of
that link cutting the relay would produce exactly this.

**Not yet run:** the confirming test below. The controller was still on the smart outlet for
both of these.

## 3d. ✅ PROOF — `switch.bedroom_closet_lower_outlet` reboots the valve, 10 for 10

**2026-08-15, from the owner's own switch history plus the whole MQTT corpus.** This section
supersedes the "inferred, not measured" caveats above.

### The method

Session 7 established that the HUB announces `SYSTEM_READY` when it boots (§3c-bis). That
signature, plus the valve's own `DEVICE_REBOOT_STS`, can be recovered from **every capture ever
taken** — 50 files spanning 2026-08-07 → 08-15 — rather than from the 4.5 hours the local probe
has existed. Cross-referencing those against the recorder's switch history is what settled it.

```sh
/homeassistant/scripts/kohler-work/venv/bin/python3 \
    /homeassistant/scripts/kohler-work/reboot_vs_moes.py
```

### The decisive evidence: deliberate power cycles

`switch.bedroom_closet_lower_outlet` was switched **off and back on** 16 times over ten days.
Ten of those fall inside MQTT capture coverage. **All ten are followed by a valve reboot, at
+18 or +19 seconds:**

```text
08-08 05:42:41Z  off 101.9s  ->  VALVE +19s,  HUB +165s
08-11 17:51:38Z  off  14.8s  ->  VALVE +19s
08-11 17:53:18Z  off  10.6s  ->  VALVE +19s
08-11 17:54:16Z  off   6.3s  ->  VALVE +18s
08-11 17:55:45Z  off   3.1s  ->  VALVE +18s
08-11 18:51:04Z  off   7.7s  ->  VALVE +18s,  HUB +295s
08-11 18:52:45Z  off   5.6s  ->  VALVE +18s,  HUB +196s
08-13 19:41:04Z  off  20.1s  ->  VALVE +19s
08-14 16:56:49Z  off  18.9s  ->  VALVE +19s
08-14 20:03:58Z  off  14.3s  ->  VALVE +19s,  HUB +159s
```

The remaining six cycles fall in capture gaps, so they show nothing either way. **There is no
counterexample** — not one covered cycle without a reboot.

**The 08-11 cluster is fully explained.** §2 and §3a treat those six reboots as the strongest
evidence the fault predates the integration and is device-side. They are six manual power
cycles of this socket, and on 08-11 *only this socket was switched* — `upper_outlet`, `usb_c`
and `usb_a` have no off→on cycle that day. Single variable, six repetitions.

### The negative control

`switch.bedroom_closet_tuya_motion_2_usb_a` — a sibling socket on the same Moes device, same
Tuya link — runs an automation that switches it off at `13:00:00Z` for exactly five minutes,
every day. **Fourteen instances, and not one reboot of anything.**

So it is not "a Tuya event", not "the Tuya cloud dropping", and not "the Moes device rebooting".
It is *that socket losing power*, which is what a socket the Anthem is plugged into would do.

### The timing signature is deterministic

Across both the deliberate cycles and the spontaneous blips:

| | delay after power returns |
|---|---|
| Valve `DEVICE_REBOOT_STS` | **+18 to +19 s** (spontaneous: +9 to +24 s) |
| HUB `SYSTEM_READY` | **+120 to +165 s** (typically +130 s) |

A valve booting in ~18 s and a Linux controller in ~130 s is exactly the expected ordering, and
the tightness of the valve figure is what a hardware boot looks like. A network or cloud
disruption would produce neither a fixed delay nor a `DEVICE_REBOOT_STS`.

### Two corrections this forces

1. **"Home Assistant cannot see this outlet" — wrong.** §3c inferred that because no switch
   changed state at 20:07. HA has been recording it for ten days; the events are `unavailable`
   blips (the outlet dropping its own link as it glitches) and explicit `off`/`on` cycles.
2. **The Bedroom Closet outlets are not "unrelated".** They are the outlet. An earlier revision
   dismissed them twice — first as a coincidence, then as a different circuit.

⚠️ **Open question for the owner, and it is a physical one:** the entity is named for a
*bedroom closet* while the shower is in a bathroom. Either the naming is stale, the closet backs
onto the bathroom, or the socket feeds a run that reaches it. The electrical fact is not in
doubt — that socket's power state controls the valve — but **confirm which physical outlet
`switch.bedroom_closet_lower_outlet` is before rewiring anything.**

### Current state, and the remaining action

**Valve — fixed.** Moved off that outlet, it has not rebooted since `2026-08-15T00:00:47Z`
(itself the expected post-config reboot; last spontaneous `2026-08-14T23:33:49Z`). It has now
ridden out **four** controller outages untouched, against a previous best gap of 91.9 minutes.

**Controller — still on it, still rebooting.** Four outages on the evening of 08-14:

| | ended | down |
|---|---|---|
| 1 | `03:09:41Z` | 110.6 s |
| 2 | `04:22:42Z` | 110.6 s |
| 3 | `~06:16Z` | (spanned a Home Assistant restart) |
| 4 | `06:21:24Z` | **135.0 s** |

They are getting more frequent, and the Moes socket is now blipping in bursts —
`06:17:26`, `06:19:08`, `06:19:30`.

**The action is no longer a test, it is the fix: move the controller off
`switch.bedroom_closet_lower_outlet` onto a plain outlet, as was already done for the valve.**
Then read `sensor.anthem_plus_controller_local_outages`, which now persists across restarts.

### The old confirming test (superseded, kept for the record)

**Move the controller off the smart outlet onto a plain one**, then read
`sensor.anthem_plus_controller_local_outages`: no further outages means the plug was the cause;
outages continuing means the controller itself is suspect.

⚠️ **Read the count, not the delta from memory** — session 6 said "staying at 1 means the plug
was the cause", which was unsafe: the counter was in-memory and reset to zero on every Home
Assistant restart, so two real outages read as "1". **Fixed in session 7** — it now persists to
the config entry like the valve reboot count, and `outages_before_restart` on the sensor says
how much of the total predates the current process.

Re-run the correlation at any time:

```sh
/homeassistant/scripts/kohler-work/venv/bin/python3 \
    /homeassistant/scripts/kohler-work/moes_correlation.py 24
```

This is still the highest-value action in this document.

### ⚠️ Three retractions — an earlier revision of this file got this wrong

1. **There was no "missed `DEVICE_REBOOT_STS`".** The message was never sent because the valve
   never rebooted. `gcs_reboot_count` reading 2 across this event was **correct**.
2. **The reboot counter does NOT undercount.** That claim was built on the false premise above.
   It has no known defect.
3. **The 0.0 °C frame is NOT a valve-reboot signature.** It was 17-for-18 only because until
   this event the controller had never restarted alone. It means *something* restarted — it
   does not identify which device. Use `DEVICE_REBOOT_STS` for the valve and
   `configChangeIndent` to confirm.

### What the valve emitting 0.0 °C actually means

The valve reports a zeroed temperature while its link to the controller is down, then reloads
config once the controller returns. It appears in both cases — valve reboot *and* controller
reboot — because in both the link is broken. Treat it as a **link-loss** marker.

### Consequence for the reboot rate

**The valve has not rebooted since 2026-08-14 16:33:49 local** (the 17:00:47 event being the
expected config-completion reboot). As of 2026-08-14 22:00 local that is a clean run of
**5 h 27 min**, against a previous best of **91.9 minutes** — the strongest evidence yet that
relocating the valve's mains outlet helped. See §2 for the baseline gaps.

It survived both controller outages in §3c-bis without flinching, which is the sharpest version
of this evidence: the same event that reboots the controller no longer touches the valve.

The controller's own stability is now a separate open question, with exactly one data point.

## 3e. ✅ Diagnosis closed — hardware fault on the Moes outlet, not electrical/Wi-Fi/HA — 2026-08-15

**Supersedes the "Current state" note at the end of §3d.** Later the same day, the owner asked
directly: is this electrical, hardware, Wi-Fi, or a Home Assistant problem? The question is now
answered from the recorder, not inference.

### The rate got much worse

In one hour on the evening of 08-15, `binary_sensor.anthem_plus_controller_local_api` recorded
**13 outages** — roughly one every **2.5–4.5 minutes**, each lasting **~110 s** (one ran **250 s**).
That is a large jump from the four outages §3d described for the whole previous evening. The
owner watched it happen live, twice within five minutes, while this was being investigated.

### A second device on the same outlet confirms it is that outlet, not the network

A Raspberry Pi (MQTT device "Pi Bluetooth", entities `sensor.pi_bluetooth_*` /
`sensor.pi_wireplumber_*`) turned out to be plugged into the **same Moes outlet** as the
controller. It rebooted **17 times** in the same hour, on the same cadence, **2–3 seconds before**
each Moes blip, with **25–60 s** recovery times. That duration is a real Linux boot after a power
interruption, not a Wi-Fi reconnect (which would be single-digit seconds) — a second, independent
device confirming an actual power event, not a reporting gap.

### Whole-house and whole-circuit are ruled out

Every entity in the recorder (2,046 of them) was checked against all 23 Moes-blip moments in that
hour. **Only one** — the Home Assistant Core restart at 23:16 — dragged in the wider house
(1,022 other entities: the full Zigbee2MQTT fleet, Hue, every other Tuya-family outlet in the
house). That is the known mass-restart signature, not a new finding. **The other 21 blips stayed
completely contained**: zero Zigbee devices, zero Hue lights, zero ESPHome sensors, and — the
important negative — **zero of the other Tuya-brand outlets elsewhere in the house** (shoe
closet, network closet, space heater, bathroom countdown switch) went down with them. A whole-house
or whole-circuit electrical event would drag in devices with no relation to this one outlet. None
of that happened, 21 times running.

### Why it points at the outlet's own hardware, not the Tuya cloud or the integration

Two things it is **not**:

* **Not the Tuya cloud/local integration.** A cloud or integration hiccup leaves the relay closed
  and the powered device running — Home Assistant would show a stale `unavailable` state while the
  controller and the Pi kept operating. Instead both devices **actually reboot**, with recovery
  times that match a real power-loss boot, not a reporting gap. An integration bug cannot cut power
  to what is plugged into the relay.
* **Not a whole-house Wi-Fi/router event.** Already ruled out above — nothing else in the house
  correlates.

What is left: **all four of that one Moes strip's virtual switches** (`upper_outlet`,
`lower_outlet`, `usb_c`, `usb_a`) blip `unavailable` in the same instant, every time, even though
each is an independently switched relay. That only makes sense if they share one WiFi/control
board, and that board is momentarily browning out or resetting — taking the relay(s) feeding the
controller and the Pi down with it. **The fault is most likely hardware in that physical Moes
unit**, or possibly a loose/intermittent wall receptacle feeding it (both would produce this exact
signature). The confirming test, not yet run: move the whole Moes strip to a different wall
outlet — blips stopping means the receptacle; blips continuing means the unit itself.

⚠️ **`binary_sensor.tuya_motion_1/2/3_presence` do not track this pattern**, even though the
owner believes one of them is physically plugged into this same strip (its USB-A port, named
`…_tuya_motion_2_usb_a` — the §3d negative control). All three only went unavailable once this
hour, during the Core restart. Worth double-checking which port that sensor is actually in.

### ✅ The controller's plug was moved — 2026-08-15, later the same session

The owner moved the controller off that Moes outlet. Both the valve and the controller took one
final reboot from the physical unplug/replug — expected, matching the established +18/+19s and
~130s boot signatures, not a spontaneous fault instance.

**Not yet confirmed clean.** The valve's fix was confirmed by a multi-hour reboot-free run, not
by the act of moving it — the controller's fix needs the same treatment: check
`sensor.anthem_plus_controller_local_outages` after several hours have passed. Whether the
Raspberry Pi's plug was also moved is unconfirmed; check before assuming it is clear too, since
§3e found it on the same outlet and rebooting in lockstep with the controller.

---

## 4. What was true at the time

Firmware, from `READ_ALL_INTERFACES_FIRMWARE_VERSION_STATUS_INFO`:

| Interface | Version |
|---|---|
| IoT | `0.74` |
| Primary valve | `10` |
| Secondary valve 1 | `10` |
| User interface 1 — application / assets | `2.2` / `2.0` |

Anthem Plus controller firmware is **2.88** (the release with the known-broken per-outlet flow
calculation; flow control is disabled system-wide on this install as the recommended
workaround).

Configuration at the time: `maximumRunTime` **3600 s** on all six outlets (changed from 900 s
at 06:46:03 that morning), `minimumFlowRate` 16, `maximumFlowRate` 200, warm-up
`warmUpDisabled`.

Full detail — all ten preset slots with decoded valve words, all six outlet configs, both UI
configs — in `device_state_before_factory_reset.json` in the archive directory.

### What the factory reset will change, and what to re-check afterwards

* **Preset 1 "Default shower"** currently stores `018445` / `0584A5` = 34.5% / 82.5%. This is
  the factory preset and the only one holding real per-zone flow; every app-created preset is
  pinned to 100%. If the reset restores different values, several observations in
  [`valve_hex.md`](valve_hex.md) and [`api.md`](api.md) are keyed to this pair.
* **The idle-frame explanation.** `01844500` / `1184A500` on an idle valve is preset 1's word
  with the mask cleared — established by byte-exact match. Re-verify after the reset; if
  preset 1 changes, the idle frame should change with it.
* **`maximumRunTime`** will presumably return to a factory default. The integration persists
  the learned value in `CONF_OUTLET_RUN_TIMES` and only overwrites it when the valve announces
  a new one, so it will pick up the change on the post-reset config dump — but confirm the
  `arm` record in `cutoff_*.jsonl` shows the new figure.
* **Whether the reboots stop.** That is the point of the exercise.

## 5. ✅ FIXED 2026-08-15 — the restore now replays the pre-cutoff flow

Independent of the reboots. Was open from 08-14 to 08-15; fixed the same session the reboot
outlet was moved.

> ⚠️ **Not yet confirmed on live hardware, for any account with a calibrated valve.** Everything
> in this section is verified by code reading and offline tests (29/29, including two
> purpose-built adversarial cases below) against the reference install, which is currently
> **uncalibrated**. It has not fired against a real cutoff since landing, on this or any other
> account, and specifically not on a calibrated valve where the ceiling mechanics in the next
> subsection actually apply. Update this note once a real cutoff on a calibrated valve has been
> observed to restore correctly.

```text
06:09:31  Z2=1184A501   preset 1, outlet 4    flow A5 = 82.5%
06:24:31  Z2=1184A540   CUTOFF at 899.90 s — detected correctly
06:24:32  Z2=1184C801   restored outlet 4     flow C8 = 100%   <- the bug, as originally found
```

Right outlet, right temperature, 0.88 s to act — but ~21% more water than the shower was
running at, and 2.9x on zone 1, which had no outlet open at all.

`_async_restart_after_cutoff` called `async_apply_valve(zone_masks=masks)` with no flow, so it
fell through to `DEFAULT_FLOW_PERCENT`. That was session 5's deliberate "flow does not inherit"
rule — right for ordinary writes (nothing should silently adopt whatever the touchscreen last
set), wrong for a restore, whose whole job is to reinstate what this code itself watched
running a moment before it force-closed the zone.

**The fix:** `_async_restart_after_cutoff` now builds `zone1_flow`/`zone2_flow` from each
`ZoneCutoff.reading.flow_percent` and passes them to `async_apply_valve` explicitly, instead of
omitting them. `writing_flow_percent` and `flow_preserved` on the `restore` journal record now
reflect what was actually sent, so the log stays a truthful before/after rather than a permanent
gap marker. `test_cutoff_readings.py`'s closing block now asserts the fix's shape instead of the
old one's absence.

### Does this work with a GCS preset driving the shower? Yes — tracking never looks at presets

Asked directly by the owner. Short answer: **the algorithm doesn't change at all for a
preset-driven session, because it was never tracking presets in the first place** — it tracks
per-zone flowing state (mask + pause flag) from the wire, the same way regardless of what
commanded it. A preset closing on its run-time limit sends `{preset, action:"Off"}`, which
**pauses every zone the preset owns in one message** — both zones close together even though
only one hit its own timer — but that is not new handling; it is exactly the `also_paused` case
this document already covered for masks (§3d predates this fix; the 2026-08-13 20:52:46 preset
cutoff — zone 2 expired at 3600 s, zone 1 paused at 1831 s — is what the mask-restore logic was
built against).

**What *was* still a gap until this session: the `also_paused` zone's flow.** `ZoneCutoff.reading`
only ever covers the zone whose own duration matched a limit — the detector never classifies the
co-paused zone as a cutoff at all (its duration matches nothing), so it had no reading to hand
back, and silently fell to `DEFAULT_FLOW_PERCENT` even after the fix above. For a preset running
two zones at different flows, the zone that *didn't* time out would still have come back at 100%.

**Fixed the same session, following the exact pattern `_last_open_masks` already uses for this
zone's mask.** A parallel `_last_open_flows` snapshot is kept alongside it — same gating (only
updated while something is open **and** nothing is paused), same reasoning (the detector's own
record is destroyed by the time the close is visible, so a coordinator-level snapshot is the only
survivor). `_async_restart_after_cutoff` now draws the `also_paused` zone's flow from it, with the
same precedence rule as the mask: the detector's own `ZoneCutoff.reading` wins when present,
`_last_open_flows` is the fallback, `DEFAULT_FLOW_PERCENT` only when neither has a value.

**Proven with an adversarial two-zone test**, not just reasoned about — `test_cutoff_restore.py`,
"a preset closing BOTH zones": zone 1 and zone 2 run at different flows (34.5% / 82.5%, the real
08-13 measured pair) with zone 1 starting 100 s after zone 2, so only zone 2's duration matches
its limit at the cut. The pause message itself carries decoy flow bytes (100% / 8%) on *both*
zones, standing in for the byte-2 dip. Both zones restore their real pre-cutoff flow, neither
picks up its decoy. 29/29 offline tests pass, including this one and the single-zone dip test in
`test_cutoff_readings.py`.

### Why "replay the exact value" is correct with or without a calibrated ceiling

This mattered enough to check rather than assume, because the reference valve is currently
**uncalibrated** (post factory-reset) and has no ceiling at all right now (`valve_hex.md`,
"An uncalibrated valve has NO ceiling"). A fix that only worked by accident on an uncalibrated
valve would break again the moment this valve — or anyone else's — gets calibrated.

It doesn't, because of what the decompile-verified live test in `api.md`'s "Flow: the valve
obeys, the touchscreen is what computes limits" section established on hardware: **a direct
API write is honoured exactly, on the raw 0–200 scale, with no clamping or rescaling.** "Write
what you want; the valve keeps it." Two things are true at once and must not be conflated:

* **The ceiling *number* is sourced from the valve's own calibration**, not computed by the
  touchscreen from scratch — `valve_hex.md`'s "An uncalibrated valve has NO ceiling" test
  showed the byte-2 dip vanishes when only the valve is left uncalibrated, HUB calibration
  notwithstanding. `api.md`'s 08-14 derivation used HUB figures as a stand-in because they
  matched well, and flagged that as untested at the time; the 08-15 result refines it.
* **Whether anything *enforces* that ceiling against a write is a separate question, and the
  answer there is no** — the touchscreen, when touched, actively writes a value at the
  ceiling (indistinguishable from any other writer, at the protocol level), and the valve
  separately *reports* its own ceiling passively in byte 2 for a couple of seconds after a
  stop or pause (`valve_hex.md`'s "the byte-2 dip"). Neither is the valve rejecting or
  rescaling a command it receives. Every direct write ever tested — this integration's own
  path — was honoured exactly, uncapped.

So a restore that replays the literal flow byte the shower was running at is correct
**regardless of calibration state**, because there is no ceiling arithmetic to get right or
wrong — the write is honoured exactly either way. This is also why fixing it this way is right
for other installs, not just this one: it never has to know or compute a ceiling, so it can't be
wrong about one.

**What produced the "dip right after pause/stop" observation.** That dip is the byte-2 ceiling
report described above — the valve briefly shows its calibrated per-zone capacity in place of
the running setpoint the instant a zone stops or pauses, then reverts to the commanded value.
It is a **reporting** artefact of a calibrated valve, not a flow change the restore (or anything
else) causes, and it does not currently occur on this valve at all, since there is no ceiling to
report while it is uncalibrated.

**Open, and worth another look once the valve is recalibrated:** every flow write ever tested on
hardware was at or below a zone's ceiling (37%, 50%, and the 08-14 restore's 100% against zones
whose ceilings were unknown at the time). Nothing has deliberately written a value between a
zone's known ceiling and 200 on a valve confirmed calibrated, to watch what the delivered water
actually does — `api.md` flags this itself: "Not proven: that the valve *never* clamps." The
theory that predicts it doesn't (touchscreen-only enforcement) fits everything observed so far,
but the direct test hasn't been run.

### ✅ Checked 2026-08-15: the byte-2 dip cannot contaminate a GCS-only user's restore

The owner asked specifically about a **GCS-only account with flow control enabled on the
touchscreen** — the case this fix has to be right for, not just this install's GCS+HUB,
flow-disabled configuration. Two questions, both settled:

* **Before the flow button is ever touched**, Home Assistant has always written 100%
  (`DEFAULT_FLOW_PERCENT`) on every command, and the valve honours it exactly, so the captured
  reading is 100% and a restore replaying it is correct — nothing has changed for that user
  yet.
* **After the touchscreen sets a reduced flow** (say the zone's ceiling, 34.5%), that is a
  genuine write, not a passive report — the shower really is running at 34.5%, and the
  detector's `_last_reading` tracks it live (`setting_change` in the journal). A restore
  replaying 34.5% is exactly the intended behaviour: it puts back what the user's own panel
  setting was, not a jump to 100%.

**The real risk was whether a cutoff could pick up the byte-2 dip instead of the true running
value** — the cutoff pauses the zone in the *same message* that clears its mask, and a pause is
one of the two conditions that trigger the dip. If the detector used that message's own reading,
a calibrated GCS-only user could have their real flow silently replaced by a ceiling artefact.

**It cannot happen, by construction — confirmed by both reading the code and an adversarial
test.** `ZoneCutoffDetector._last_reading` is only ever updated while a zone is *flowing*
(non-empty mask, not paused) — see `update()`. The pause/cutoff message is by definition not
flowing, so whatever reading arrives alongside it is never written into `_last_reading`, and
`ZoneCutoff.reading` is built from `_last_reading` alone, with no fallback to the current
message. Proven with a test that feeds the pause message a deliberately wrong decoy reading (99%
alongside the pause, standing in for a dip) while the zone had genuinely been flowing at 34.5%:
`fired[0].reading.flow_percent` is still exactly 34.5%. Added as a permanent regression case in
`test_cutoff_readings.py` ("the pause message's own reading can never contaminate the restore").
29/29 offline tests pass.

### Q&A log — questions the owner asked while verifying this fix, 2026-08-15

Kept verbatim-in-spirit so the answers don't have to be re-derived later.

**Q: Is the restore fix tested on live hardware, for a calibrated valve?**
No. Verified by code reading and offline tests only (29/29, including two adversarial cases).
The reference valve is currently uncalibrated. See the "Not yet confirmed" callout at the top of
this section — update it once a real cutoff on a calibrated valve has been observed.

**Q: Does "keep shower on" work with a GCS preset driving the shower? Does the tracking
algorithm change, since a preset hitting its limit sends `{preset, action:"Off"}` and closes
both zones?**
Yes, and no. The detector tracks per-zone mask + pause only — it never reads
`presetOrExperienceId` — so a preset-driven session is handled identically to a directly-driven
one. The only real gap was the co-paused zone's *flow* (the zone that didn't time out itself but
got closed alongside the one that did): `ZoneCutoff.reading` never covered it, so it fell back to
`DEFAULT_FLOW_PERCENT`. Fixed the same session with `_last_open_flows`, mirroring the
`_last_open_masks` pattern already used for that zone's mask. Proven with an adversarial two-zone
test (different flows per zone, decoy dip values on both) — see above.

**Q: Does the valve honour a written flow byte proportionally to a calibrated ceiling, or over
the raw 0-200 range — and does this change what the restore should write?**
Over the raw range, always — a direct API write is honoured exactly, uncapped, decompile- and
hardware-verified. The ceiling *number* comes from the valve's own calibration (refines an
earlier assumption that credited the touchscreen with computing it), but nothing enforces it
against a write; the touchscreen only *actively writes* a ceiling-conforming value when touched,
same mechanism as any other writer. So replaying the exact captured flow is correct with or
without calibration — there's no ceiling arithmetic to get right or wrong.

**Q: Does a GCS-only account with flow control enabled hit any problem here — specifically,
could the restore pick up the byte-2 "ceiling dip" instead of the real running flow?**
No, architecturally impossible: `_last_reading` only updates while a zone is genuinely flowing,
never from a paused/stopped message, so the dip (which only appears while paused/stopped) can
never be read into it. Proven with a decoy-reading adversarial test.

**Q: [Separately] Does a GCS preset have a "timer," and what makes it latch or clear? What
clears it, does reactivating reset it, does pausing reset it?**
Full writeup: [`api.md`](api.md#-correction-2026-08-15--one-zone-at-40-is-enough-is-wrong-for-a-two-zone-preset).
Short version: no live countdown is transmitted; `presetOrExperienceId` only clears once *every*
zone the preset owns is paused/stopped (corrects the earlier "any one zone" rule); reactivating
resets both outlets and flow to the preset's stored values, discarding manual mid-session
changes; whether a same-zone pause-and-resume (not a full reactivation) resets anything is still
open — not tested by the capture that answered the rest of this.

**Q: Does that preset-latching behaviour affect "keep shower on"?**
No. The detector never reads `presetOrExperienceId`, so the latching quirk is invisible to it by
construction. A real cutoff pauses every zone the preset owns in one atomic message; the
manual-reactivation pattern is staggered over several seconds and involves durations of
seconds-to-minutes, which can never fall within `CUTOFF_TOLERANCE_SECONDS` (10 s) of a real
900s/3600s limit — so it's never misread as a cutoff.

**Q: What about a GCS preset started *from Home Assistant* rather than the touchscreen — any
difference?**
None. `coordinator.async_activate_preset()` only POSTs `{preset, action:"On"}` to the cloud API;
everything downstream (state updates, cutoff detection, restore) runs through the same pipeline
regardless of what activated the preset. The restore path never re-activates a preset id from
any source — `api.md` documents why that would be wrong (masks are the only trustworthy record)
— so activation source was never going to matter.

## 5a. A factory reset did NOT fix it

Both devices were factory reset and the integration re-added on 2026-08-14 ~09:40 local.
**The valve rebooted twice within twenty minutes of coming back:**

```text
09:40:19   integration set up, new MQTT identity, ~60s provisioning
09:57:27   *** DEVICE_REBOOT_STS ***
10:00:53   *** DEVICE_REBOOT_STS ***     3 min 26 s later
```

Same signature as before the reset: reboot → preset-1 idle word → six outlet configs → preset
dump. The second came 16 s after a command was received.

**This is the finding that matters for a warranty conversation.** The valve fails identically
with factory-clean settings, so it is not configuration, not the presets, and not anything
this integration stores.

### What the reset did and did not change

| | Before | After |
|---|---|---|
| Device IDs | `gcs-sio32343h7` / `gcs-sious0103D` | **unchanged** — all 37 HA entities reattached, no duplicates |
| Preset 1 `Default shower` | `018445` / `0584A5` = 34.5% / 82.5% | `018447` / `05849E` = **35.5% / 79.0%** |
| Preset 1 `time` | 3600 s | 3600 s (**not** the 1800 s in the 2026-07-30 backup) |
| Presets 2-5 | Test twozone, Twotwentysix/seven/three | **gone** — only slot 1 populated |
| HUB favourites | "Soap Pause" etc. | **gone** — `hub-experience/…/favorites` returns HTTP 404 |
| Outlet config | 3600 s / flow 16-200 | identical |
| `outlet_run_times` (HA) | all six at 3600 s | cleared, re-learned at 09:57 |
| `mobile_device_id` (HA) | `eebb04c65e54441b` | regenerated — one-off MQTT provisioning delay |

**Preset 1 is not a fixed factory constant.** Its stored flow has now been observed at four
different values (36.0/78.0 → 34.5/82.5 → 35.5/79.0 on zone1/zone2), and its `time` at both
1800 s and 3600 s. It drifts because the touchscreen recomputes and writes it back — the same
mechanism behind the unpredictable ceiling in
[`api.md`](api.md#flow-the-valve-obeys-the-touchscreen-is-what-computes-limits).

## 5b. Owner's mitigation and the open experiment

Set up 2026-08-14 by the owner, and worth leaving alone until it produces an answer:

* **Flow control disabled on both GCS and HUB.** Reasoning: preset 1 is the only preset that
  carries a non-200 flow, so it is the only one that can put a *ceiling* on the valve, and
  both flow subsystems were already buggy before this integration existed (HUB flow control
  is essentially broken on 2.88).
* **`restart_on_runtime_cutoff` left OFF** (`options: {}` on the new config entry).

**This makes the next reboot a clean data point.** With the cutoff option off, the integration
writes to the valve only when somebody presses a switch — so an unattended reboot cannot be
attributed to it at all.

Two observations already recorded against it:

* **Disabling flow control did not clear preset 1's stored flow.** The idle frame still cycles
  `01844700` / `11849E00` (35.5% / 79.0%) against `0184C800` / `1184C800`. Whatever the
  touchscreen wrote survives the flow-control switch, so the ceiling is still present.
* **Both post-reset reboots happened with `presetOrExperienceId: 0`** — no preset driving the
  valve. That does not clear preset 1 (its stored ceiling persists whether or not it is
  active, which is exactly the owner's point) but it does mean an *active* preset is not
  required to trigger a reboot.

The cutoff debug log keeps recording regardless of the option — `flow_start` / `flow_end` with
`flow_percent` and `temperature_f` — so the experiment costs no visibility.

## 6. If this goes to Kohler

The useful facts, in one place:

* Valve reboots unprompted with **no water running and no commands for over 90 minutes**.
* **25 reboots between 2026-08-07 and 08-14**, 15 of them on 08-14 alone. Seven arrive
  within two minutes of the preceding one — including four inside four minutes on 08-11.
* **No error is ever reported** — `errorCode` null, `errorstate` 0, `SYSTEM_READY`.
* Mid-boot the valve reports **0.0 °C on both zones for 17 s**, ~71 s after signalling ready.
* First captured 2026-08-07; a cluster of six on 08-11; by 2026-08-14 running roughly every
  10 minutes.
* No mid-shower reboot had **ever** occurred before 2026-08-14; three occurred that morning.
* Firmware IoT `0.74`, valve `10`, UI `2.2`; controller 2.88.
* **A full factory reset of both devices did not fix it** — two reboots within twenty minutes
  of the rebuilt system coming online, on factory-clean settings (§5a).

Timestamped MQTT captures are in the archive directory and can be handed over as-is.
