# Kohler Konnect — **GCS** (Anthem Wi-Fi valve) API notes

Companion to [`../hub/cloud_api.md`](../hub/cloud_api.md). Same auth, headers, and base URL
(see that doc §1). SKU string: **`GCS`**. This account's GCS device: `gcs-sio32343h7`.

Derived from the Konnect 3.0.1 decompile + the `kohler-anthem` library + the working
`kohler-konnect-ha` integration. **Not** all live-tested — marked where relevant.

> **Valve hex lives in [`valve_hex.md`](valve_hex.md), not here.** That document is
> capture-derived and authoritative; the byte tables that used to appear in this file were
> decompile-guesses and two of them were wrong. See
> [Superseded readings](valve_hex.md#superseded-readings) for what changed and why.

---

## 1. GCS is architecturally the opposite of the HUB

- **GCS** = the **digital valve body itself**, with built-in Wi-Fi (and likely Bluetooth).
  The Konnect app talks to *this valve* directly. It has **no "run my default"** — every
  start must specify the exact valve state. **There is no `gcs/valvecontrol` / bare on-off.**
- **HUB** ("Anthem Plus") = **valve + a Linux system controller** that additionally
  integrates music, lighting, and steam — hence the "Plus". The Konnect app sends commands
  to *the controller*, which drives its valves. A bare
  `valvecontrol {valveOnOff:"ON"}` runs the controller's own stored default.

The HUB also serves a **local** REST API on the LAN for reading crude state and reading or
writing configuration — but **no control** can be sent over local HTTP. See
[`../hub/local_api.md`](../hub/local_api.md).

Most Home Assistant Kohler Konnect integrations only support GCS, because the upstream
`yon/kohler-anthem` library only reverse-engineered the GCS device.

Full GCS command set (`ApiConstant.java`): `solowritesystem`, `controlpresetorexperience`,
`startpreset`, `writepreset`, `createpreset`, `writeoutletconfig`, `valvereset`, `warmup`,
`factoryreset`, `writeuiconfig`, `uiconfigsuccess`, `bathfillervolume`.

> ## ⚠️ IMPORTANT — `action:"Off"` pauses **and** clears the active preset
>
> `{preset, action:"Off"}` does **two** things, and both matter:
>
> 1. **Byte 3 → `0x40` (PAUSE)** on every zone the preset is driving. Not `0x00`. It
>    *pauses*; it does not stop. The temperature byte survives.
> 2. **`presetOrExperienceId` → `0`** — whatever preset was active is cleared.
>
> **The valve's run-time cutoff performs this same `action:"Off"`.** Verified live
> 2026-08-13 by driving a two-zone preset and firing `action:"Off"` by hand: the resulting
> words were byte-identical to a real cutoff apart from the setpoint. So a run-time limit
> does not close an outlet — **it ends the experience.**
>
> The consequences follow from that single fact:
>
> * A **preset-driven** session loses **every zone the preset drives**, because a preset is a
>   two-zone object — each carries a 6-hex word for `Valve1` *and* `Valve2`.
> * A **directly-driven** session (`presetOrExperienceId: 0`) has no preset to end, so only
>   the zone that fired is paused.
> * Anything restoring a session must replay the state captured **before** the cutoff. By the
>   time the pause is visible, the masks are already gone.
>
> Contrast `solowritesystem` with mask `0x00`, which is a genuine stop: byte 3 `0x00`, preset
> id untouched. The two are distinguishable on the wire, which is what made the
> identification possible. Details: [Stop — `action:"Off"`](#stop--actionoff-is-verified-2026-08-13-and-it-pauses-rather-than-stops).
>
> A `0x40` pause on its own does **not** imply a preset was involved — the touchscreen's own
> pause button produces `0x40` with `presetOrExperienceId` already `0`. It is the
> *combination* of `0x40` **and** a preset id changing to `0` that identifies an ended preset.

### The preset id survives outlet changes — it marks a *session*, not a *state*

**`presetOrExperienceId` says which preset was last started, not what is currently open.** It
persists across outlet additions and removals, so it goes stale the moment anyone adjusts the
shower:

```text
19:52:48  preset=1  open: 4          preset 1 activated (it defines outlet 4 alone)
20:22:15  preset=1  open: 3 4        outlet added — id still 1
20:34:23  preset=1  open: 3 4 5      id still 1
20:44:44  preset=1  open: 2 3 4 5    id still 1, state now nothing like preset 1
```

**Never restore a session by re-activating the stored preset id.** Doing that at 20:44 would
have reopened outlet 4 alone and dropped three outlets. The outlet masks are the only
trustworthy record of what was running.

#### What actually clears it: **any `40`, or `00`/`00`**

That is the whole rule. Every observed transition to `0`, across all captures:

| Trigger | Observed at |
|---|---|
| **`0x40` on *any* zone** | 19:14:38, 21:31:22 (one zone) · 20:52:46, 21:40:23 (both) |
| **`00` on *both* zones** | 21:58:29 — id drops on the next message |

The asymmetry is the point, and it is what makes the id survive ordinary use:

* **One** zone at `40` is enough. A pause ends the session however much else is running.
* **One** zone at `00` is not. Observed in 6 messages with zone 1 at `00` and the preset still
  active, because zone 2 was still open. On a 3+3 valve, opening outlet 5 alongside outlet 4
  moves *zone 2* from `01` to `03` and never touches zone 1 — so zone 1 sits at `00` for the
  whole session while the preset stays live.

That is why adding and removing outlets never disturbs the id: those writes change a mask
from one non-zero value to another, or leave a zone at `00` that was already `00`. Neither
`40` nor `00`/`00` is ever sent.

Two caveats:

* The id can lag by one message. At 21:58:28 both masks read `00` with the id still `1`; it
  cleared at 21:58:29. Anything keying on the id must tolerate that one-frame delay.
* Every observed `40` landed on a zone that had been running. A `40` on an already-idle zone
  while another zone runs has not been seen, so "any `40`" is untested in that corner.

#### ⚠️ Correction, 2026-08-15 — "one zone at `40` is enough" is wrong for a two-zone preset

The 08-13 corpus above never happened to test a preset driving *both* zones with only one of
them paused. An owner experiment on 08-14 did, on the first-gen touchscreen, preset 2
("Workout A"), and the rule as stated does not survive it —
`mqtt_raw_20260814T181113Z_71_fbcedad8.jsonl`:

```text
18:15:17.832  preset=2  Z1 outlets 1+3 @ 67.5%     Z2 outlet 4 @ 17.0%   (Z1 manually adjusted)
18:15:30.835  preset=2  Z1 unchanged  @ 67.5%      Z2 PAUSED (0x40)      <- one zone pauses
18:15:31.600  preset=2  Z1 outlet 1 @ 38.5%        Z2 still paused        <- 19s, id unchanged
18:15:50.636  preset=0  Z1 ALSO PAUSED (0x40)      Z2 still paused        <- only now clears
```

Zone 2 sat paused for **19 continuous seconds** — two more `GCS_SOLO_STS` messages, both
confirmed present, nothing between them — while zone 1 kept running under the same preset. The
id held "2" throughout and only dropped once zone 1 *also* paused.

**The corrected rule: the session ends when every zone the preset owns is paused or stopped,
not any single one.** The 08-13 finding wasn't wrong so much as untested in exactly this corner
— every `40` it saw belonged to a session where that was the only zone running, so "one zone"
and "every zone the preset owns" were indistinguishable in that data. They aren't the same rule,
and this is the case that tells them apart.

**Reactivating the preset while it is running behaves differently from pausing it.** Pressing
the preset again — even mid-session, even with manual adjustments in place — produces a
distinctive three-message pattern: both zones pause, the id flickers off and back on within
~100-200ms, then **both zones reopen at the preset's original stored configuration**, discarding
whatever had been manually changed. Observed six times in under two minutes in the same capture,
consistent every time (`presetId=2` dumps `Valve1=118421` / `Valve2=058422` → 16.5% / 17.0%,
matching what every reopening restored to, byte for byte).

**No live countdown or time-remaining field exists anywhere on the wire.** Checked directly by
dumping the complete attribute set of every `GCS_SOLO_STS` in this window — only
`presetOrExperienceId`, `configChangeIndent`, `totalFlow`/`totalVolume`, and the two valve words.
`GCS_PRESET_STS`'s `time` field is the preset's *static configured* duration, sent once as
config, never as a running countdown. Whatever a touchscreen displays as a countdown is computed
and held locally on the panel — it is not transmitted.

**None of this affects the *restore* logic.** The run-time cutoff detector never reads
`presetOrExperienceId` — it tracks per-zone mask and pause state only, and a real
`maximumRunTime` cutoff pauses every zone a preset owns in one atomic message, a different shape
from the staggered manual pattern above. See
[`valve_reboot_fault.md`](valve_reboot_fault.md#5-fixed-2026-08-15--the-restore-now-replays-the-pre-cutoff-flow)
for the full reasoning.

> ⚠️ **An earlier revision of this paragraph said "None of this affects the integration."
> That is wrong, and 2026-08-17 disproved it.** The preset's `time` is a *second, independent
> timer* that can stop a shower the detector cannot account for, because the detector only ever
> learns `maximumRunTime`. See
> [**§1a — two independent run-time limits**](#-confirmed-2026-08-17--two-independent-timers-hardware-maximumruntime-vs-software-preset-time).
> The sentence is accurate about the restore path only, which is what it was originally
> measuring.

### `presetOrExperienceId` is a **GCS** fact, and almost nothing sets it

Measured across three live experiments on 2026-08-13:

| Started by | `presetOrExperienceId` | Stop writes |
|---|---|---|
| First-gen touchscreen "Default shower" | **`0` — never set** | `0x40` **pause** |
| Anthem Plus controller, its own default | **`0` — never set** | `0x00` **stop** |
| Home Assistant `controlpresetorexperience` `action:"On"` | **`1`** | — |

**Neither panel's "Default shower" activates a GCS preset**, despite the name. Both drive the
valve directly, leaving the preset id at `0`. The controller in particular tells the valve
*which outlets to open*, not *which preset to run* — the two products keep separate favourite
sets, so a HUB favourite has no GCS preset id to name. `presetOrExperienceId` therefore marks
only a preset the **valve itself** was told to run, which in practice means one activated
through the cloud API.

#### Which surface writes which stop — measured

| Control surface | Stop writes | Notes |
|---|---|---|
| **Anthem Plus panel** (the main control) | **`00`/`00`** | confirmed twice on 2026-08-13, plus two earlier stops. No pause flag in any capture. |
| Home Assistant, since 2026-08-13 | **`00`/`00`** | `async_stop_shower()`; was `0x40` until the cutoff work made a pause ambiguous |
| `solowritesystem` mask `0x00` | `00`/`00` | the generic stop |
| **First-generation touchscreen** (side wall) | **`0x40`** | the *only* surface observed pausing. On the reference system it is a secondary panel used while seated. |
| **The valve's run-time cutoff** | **`0x40`** | internally `{preset, action:"Off"}` |

**Only two things write `0x40`: the first-gen touchscreen, and the cutoff.** That used to make
"a close is a cutoff only if its zone is paused" a usable discriminator — every stop a user is
likely to issue writes `0x00` and was ignored by construction.

> ⚠️ **Retired 2026-08-17.** The table above is still accurate about who writes what, but the
> discriminator built on it is gone: the valve's **60-minute session ceiling** ends a zone
> with `0x00`, so requiring the pause flag ignored a real cutoff. See "the 60-minute session
> ceiling" below. Duration alone now decides, and the flag is recorded rather than obeyed.

The exception worth designing around is a **GCS-only install**, which has no Anthem Plus
panel. There the touchscreen is the primary surface, so a `0x40` stop is routine rather than
rare, and only the tolerance window separates it from a cutoff. See
`CUTOFF_TOLERANCE_SECONDS`.

The two panels also stop differently, which is worth not conflating:

* Touchscreen stop → `0x40`, a pause. Resuming reopens the same outlets.
* Controller stop → `0x00`, a genuine stop.
* Controller stopping a **preset** session clears the masks with `0x00` while the preset id is
  still set, and the id drops to `0` about a second later — **two messages**. That is *not*
  `action:"Off"`, which does `0x40` and the id clear in **one**. The distinction is what keeps
  the run-time cutoff identifiable as `action:"Off"` specifically.
* A resume after any of these comes back with `presetOrExperienceId: 0` — **the preset is
  never restored**.

### Warm-up: two independent systems, and a flag you will usually miss

Analysed across the full corpus — 773 GCS status messages and 289 HUB `SHOWER_VALVE_STS`.

**There are two separate warm-up implementations and their flags never coincide.**

| | Flag | Events observed | Overlap with the other |
|---|---|---|---|
| Valve | `GCS_SOLO_STS.warmUpStatus = warmUpInProgress` | 10 | **none within 2 minutes** |
| Controller | `SHOWER_VALVE_STS.showerwarmup = 1` | 9 | **none within 2 minutes** |

Zero of the 19 events had a counterpart on the other device. Anything reporting "Warming Up"
must therefore read **both** — either one alone misses roughly half of them. That is why
`ValveStatusSensor` merges the two.

> ✅ **2026-08-21: the independence runs deeper than the flags.** The two warm-ups are
> separate *settings* on separate devices — the hub's `warmupmode`/`warmupOutlets` in its
> local config versus the valve's `GCS_WARM_STS` mode — and the hub's web UI overwrites the
> valve's setting, which the hub itself never uses. That is what §3e's "unexplained" disables
> were. Full story and fingerprint: §3h.

The valve's warm-up is gated by a mode, and the observations track it exactly:

```text
GCS_WARM_STS.warmup:  warmUpAllOutletsWithNoStartDelay      (08-07)
                      warmUpDisabled                        (08-08 onward)
                      warmUpSelectedOutletsWithNoStartDelay (08-13 19:46)
```

Valve warm-ups appear on 08-07/08-08, stop entirely while the mode reads `warmUpDisabled`,
and resume on 08-13 once it was re-enabled. Note the mode also decides the shape: the
`AllOutlets` events opened outlets **1,2,3,4,5**, while the single `SelectedOutlets` event
opened **outlet 4 alone**.

#### There is no temperature threshold in the API

Searched every captured attribute for a warm-up or threshold setting. The only warm-up
configuration that exists anywhere is `GCS_WARM_STS.warmup` — an enum of *disabled / all
outlets / selected outlets*. **No temperature gate is exposed.** If the firmware has one it
uses the inlet reading, which the valve never publishes (bytes 4-6 of the status word are
zero in every capture).

#### Why warm-up "only happens when the water is cold"

It is a **duration** effect, not a gate — and mostly a sampling artefact:

* Every observed controller warm-up was visible in **1-2 messages** and no more.
* The stream is event-driven, so a warm-up that finishes quickly can produce **no message at
  all** with the flag set. Measured directly: the Anthem Plus default on 08-13 23:37 ran a
  7-second all-outlets warm-up burst, and the controller's first status message arrived at
  23:37:24 — *after* it had finished. The event is plainly visible in the valve words and
  entirely absent from the flag.
* Idle time before the session, as a proxy for cold pipes:
  **median 1.6 h before a warm-up session vs 0.2 h before a normal one** (n=8 / n=72).

So warm-up most likely runs whenever its mode allows, and is only *observable* when cold
water makes it last long enough to survive a status message. Two of the eight warm-up
sessions began after ~0 idle, so it is not a hard cold-pipes gate either.

**Consequence for any status entity: absence of the flag is not absence of warm-up.** Do not
build logic that treats "no warm-up flag" as "definitely not warming up".

#### Warm-up can run without either warm-up flag being set

The controller's default ran a warm-up that opened outlets **1,2,3,4,5** for ~7 s before
settling to outlet 4. Throughout, GCS `warmUpStatus` read `warmUpNotInProgress` (all 44
messages in the capture) and HUB `showerwarmup` read `0`.

So a panel-initiated warm-up is **invisible to both warm-up indicators**. Anything reporting
"Warming Up" from those fields will miss it; the only signature is the brief all-outlets
burst. Consequence for the integration: `sensor.anthem_valve_status` shows *Water Running*,
not *Warming Up*, for a controller-started warm-up.

## 1a. Reads

Probed live 2026-08-12 against a HUB-attached GCS. Base `/devices/api/v1/device-management`.

| Purpose | Path | Status |
|---|---|---|
| **Live valve state** | `gcs-state/{deviceId}` | ✅ the useful one — see below |
| **Presets / experiences** | `gcs-preset/{deviceId}` | ✅ `gcsPresetExperienceDetails[]` |
| Device configuration | `gcs-configuration/{deviceId}` | ⚠️ exists, mostly **null** here — see below |
| Water usage | `gcs-usage/{deviceId}` | ❓ exists (HTTP 400 bare, so it wants parameters) |

Returning **404**, so they do not exist under these names: `gcs-outlet-config`,
`gcs-outletconfig`, `gcs-outlet-configuration`, `gcs-valve-config`,
`gcs-valve-configuration`, `gcs-diagnostics`, `gcs-about`, `gcs-settings`, `gcs-ui-config`,
`gcs-experience`, and `gcs-configuration` under `/v2/`.

### `gcs-state` — the valve's own view

```json
{ "state": {
    "warmUpState": {"warmUp": "warmUpDisabled", "state": "warmUpNotInProgress"},
    "currentSystemState": "normalOperation", "presetOrExperienceId": "0",
    "totalVolume": "536930904", "totalFlow": "413.25",
    "valve1": { "atFlow": "0", "atTemp": "0", "flowSetpoint": "50",
                "temperatureSetpoint": "38.8", "errorFlag": "0", "errorCode": "1",
                "out1": "0", "out2": "0", "out3": "0", "pauseFlag": "0",
                "outletOne": {"outletTemp": "0", "outletFlow": "0"}, … },
    "valve2": { … }, "valve3": { … } },
  "connectionState": "Connected" }
```

The per-valve fields mirror the MQTT status word exactly — `atFlow`, `atTemp`, `errorFlag`,
`errorCode`, `pauseFlag`, per-outlet booleans, and both setpoints. This is what seeds entity
state at startup, since MQTT says nothing until the shower next changes.

Note `flowSetpoint` is on the device's **0-50** scale, not percent
([`valve_hex.md`](valve_hex.md)). `totalVolume` moves erratically and does not behave like a
counter — do not build statistics on it.

### `gcs-configuration` — null on a HUB-attached valve

Every structural field comes back `null`: `zoneone`, `zonetwo`, `parts`, `valve1Settings`,
`valve2Settings`, `systemConfiguration`, `systemSettings`. Only `about.firmware` (valve
firmware, `00.74` here) and `firmwareOTADetails` carry data.

The reason is that a valve wired to an Anthem Plus controller reports its configuration
**through the controller**. Whether a GCS-only install populates these fields is **unknown
and untested** — that is exactly the case no one has been able to check.

### Outlet topology: read it from the controller

When a HUB is present, the valve's outlet layout is available in full from
`hub-configuration/{hubDeviceId}`:

```json
"zoneone": {"configuredoutlets": "3", "portsavailable": "3",
            "outletone": 62, "outlettwo": 52, "outletthree": 1, "defaultoutlets": []},
"zonetwo": {"configuredoutlets": "3", "portsavailable": "3",
            "outletone": 11, "outlettwo": 38, "outletthree": 21, "defaultoutlets": [1]}
```

`configuredoutlets` per zone gives the split directly — 3+3 above, identifying a K-28212.

The outlet **type codes** line up positionally with the MQTT `READ_GCS_OUTLET_CONFIG_CFG`
enumeration, in **5 of 6** positions:

```text
MQTT ids 0-5    62  52   1  11  39  21
zone1 + zone2   62  52   1  11  38  21
                                 ^^  disagree
```

Id 4 is type **39** to the valve and **38** to the controller — and that is **not an error**.
The two devices hold independent outlet-type assignments for the same physical fixture: on
the test system that outlet is configured as a *Real Rain* rainshower on the valve, and as a
*regular rainshower* on the controller (a deliberate choice, because flow control is buggy
on the controller's firmware).

So outlet **type** is per-device configuration, not a property of the plumbing. Do not treat
the two sources as one truth, and do not "fix" a mismatch — it may be intentional. The
*count* and *position* still agree, which is what matters for topology.

#### Outlet type does not affect the valve

The valve derives its flow limits from the **flow calibration figure alone** — outlet type
plays no part. On the GCS side it is effectively a label.

Type *does* matter on the Anthem Plus controller, which computes per-outlet flow limits from
type against calibration. That is why the two devices can legitimately disagree about the
same fixture. See [`../architecture.md`](../architecture.md#outlet-types-mean-different-things-on-the-two-devices).

### `READ_GCS_OUTLET_CONFIG_CFG` (MQTT) — right data, wrong shape for setup

The valve does enumerate its outlets, with per-outlet limits:

```json
{"outLetId": "0", "outLetType": "62", "outLetFlags": "1",
 "minimumOutletTemperature": "150", "defaultOutletTemperature": "388",
 "maximumOutletTemperature": "450",
 "minimumFlowRate": "16", "defaultFlowRate": "200", "maximumFlowRate": "200",
 "maximumRunTime": "3600"}
```

Temperatures are tenths of °C (388 = 38.8 °C) and flow rates are **byte** units
(200 = `0xC8` = 100%).

Unusable during setup, though: **one outlet per message**, arriving unprompted and
event-driven — 42 messages across 20 capture sessions, seven per outlet. A config flow cannot
wait out the ~60 s MQTT warm-up.

#### What the run-time cutoff actually does: pauses a zone and clears its mask

Measured live 2026-08-13, a four-outlet **preset-driven** shower reaching zone 2's 3600 s
limit. Both zones are cleared here because a preset was active — a directly-driven session
loses only the zone that expired, and the timer is the *zone's*; both points are established
below.

```text
19:52:48  0584c800 / 1184a501   outlet 4 opens          <- zone 2 starts flowing
20:22:15  0584c804 / 1184c801   outlet 3 added
20:34:23  0584c804 / 1184c803   outlet 5 added
20:44:44  0584c806 / 1184c803   outlet 2 added  (2,3,4,5 running)
20:52:46  0584c840 / 1184c840   CUTOFF: both zones paused, ALL masks 0
```

**It does not close one outlet.** Byte 3 goes to `0x40` — pause flag set, outlet mask zeroed
— on the primary *and* the secondary here, for a limit reached in zone 2 alone. The
temperature byte survives untouched.

#### ✅ CONFIRMED 2026-08-17 — two independent timers: hardware `maximumRunTime` vs. software preset `time`

**There is not one run-time limit on this system. There are two, from different layers, and the
more restrictive one wins.**

| | where it lives | scope | nature |
|---|---|---|---|
| **`maximumRunTime`** | per outlet, `READ_GCS_OUTLET_CONFIG_CFG` | every session, however started | **hardware gate** — the valve enforces it |
| **preset `time`** | per preset, `GCS_PRESET_STS` | only while that preset drives the session | **software gate** — a stored duration the preset carries |

**A preset's `time` cannot exceed the hardware gate.** Set a preset above `maximumRunTime` and
the valve clamps the session to `maximumRunTime` anyway. Set it below — as this install
currently is — and the preset stops the shower first, well short of a limit the valve would
happily have allowed.

##### The observation that forced this

On 2026-08-17 the install had **`maximumRunTime` 3600 s** on all six outlets and **preset 1
`time` 1800 s**. Two preset-driven runs, both stopped by the preset:

```text
14:57:24 → 15:27:24   1799.90 s   paused (0x40)
15:35:00 → 16:04:59   1799.66 s   paused (0x40)
```

0.24 s apart from each other, 1800.3 s short of the limit the cutoff detector was armed with.
The second run was a deliberate re-test — preset 1 activated again specifically to see whether
it would stop at 30 minutes a second time. It did.

##### Why preset 1 held a stale value

The preset does **not** follow later changes to `maximumRunTime`. It keeps whatever was in force
when it was written:

| UTC | `maximumRunTime` | preset 1 `time` |
|---|---|---|
| 2026-08-14 20:04:37 | → **1800** (factory reset restores the default) | |
| 2026-08-14 20:04:45 | | wiped by the reset — `name ""`, `time "0"` |
| 2026-08-15 00:00:04 | 1800 | **recreated → 1800** |
| 2026-08-15 00:21:08 | → **3600** | **still 1800** |
| 2026-08-15 → 08-17 | 900 ↔ 3600, seven more times | **never moved** |

Preset 1 was rebuilt inside the 20-minute window when the post-reset default was 1800, and froze
it.

##### Nothing re-syncs it — `time` is only ever what the last writer sent

Tested directly on 2026-08-17, in both directions:

| action | `time` after |
|---|---|
| Change the **default outlet** in the Konnect app | **unchanged at 1800** — the app rewrote the preset's outlet flags and sent the existing timer straight back |
| `writepreset` with an explicit `"time": "3600"` | **3600** — applied, confirmed by read-back and by the device's own `GCS_PRESET_STS` push |

So the field is neither derived nor protected. It is a plain stored value, and no app-side or
device-side path makes it follow `maximumRunTime`. An earlier revision of this section said
"rewriting the preset is what re-syncs it" — **wrong in both directions**: a rewrite does not
re-sync, and a deliberate `time` write does not need to rewrite anything else.

##### ⚠️ Preset 1 is invisible, so nobody can fix its timer by hand

Preset 1 is hidden from the owner in **both** the first-generation touchscreen and the Konnect
app. Its timer is whatever the setup wizard stored when the preset was created, and there is no
interface anywhere that shows or edits it.

That is why the integration normalises it — see
[**§1a — the integration sets preset 1's timer once at setup**](#the-integration-sets-preset-1s-timer-once-at-setup).
Presets 2-10 are left strictly alone: they are visible and editable in the app, their timers are
the owner's choice, and on the first-generation touchscreen that same value is the **countdown
displayed during a run** (it clears when the preset id clears). Preset 1 has no countdown to
affect, being outside that system entirely.

##### Preset-driven vs. directly-driven, on the wire

The two are distinguishable, which is what confirmed the mechanism rather than merely fitting it:

```text
15:34:59.975  GCS_RECIEVED_STS   messageRecievedAndExecuted    <- preset activation is acked
15:35:00.061  GCS_SOLO_STS       presetOrExperienceId "1"      <- preset drives the session
16:04:59.725  GCS_SOLO_STS       1184c840  id "0"              <- preset timer expires: PAUSE
16:05:02.032  GCS_SOLO_STS       1184c801  id "0"              <- resumed by solowritesystem
```

The resume 2.3 s later was a **`solowritesystem` write, not a preset activation** — no
`GCS_RECIEVED_STS` appeared for it, and `presetOrExperienceId` stayed `0`. That session was
outside the preset's timer entirely.

⚠️ **Untested:** whether a directly-driven session then runs to the full `maximumRunTime`. This
one was stopped by hand at 444.67 s (`paused: false` — a real stop, not a timer), so the
prediction that it would have run to 3600 s is inference, not measurement.

##### The integration sets preset 1's timer once at setup

`_async_sync_default_preset_timer` in `coordinator.py`, run from `async_setup`. It reads
`gcs-preset`, and **only if** preset 1's `time` differs from `DEFAULT_PRESET_TIMER_SECONDS`
(3600) does it send one `writepreset`, carrying the name, volume and both valve words straight
back unchanged. Read-then-conditionally-write, so it is idempotent — proven against this
install's real payloads: a write against the 1800 s record, a no-op against the 3600 s one.

The intent is not to *manage* the timer but to take it out of play, leaving `maximumRunTime` as
the single limit that ends a shower — one number, in one place, that the owner can actually see
and change.

Deliberate boundaries, all covered by `test_preset_timer_sync.py`:

* **Preset 1 only.** Presets 2-10 are never read for this purpose and never written.
* **An empty slot is left empty.** A factory reset with the wizard skipped leaves all ten slots
  blank; writing a timer in would half-create a preset nobody asked for.
* **Failure is non-fatal.** A Kohler outage or a rejected write is logged at debug and setup
  continues. The integration works fine against a preset with the wrong timer — this is a
  convenience, not a prerequisite, and nothing downstream reads the result.
* **A fixed constant, not the live hardware value.** `maximumRunTime` cannot be read on demand
  at all — no REST endpoint exists, and `READ_GCS_OUTLET_CONFIG_CFG` arrives unprompted over
  MQTT one outlet at a time, so at setup it is frequently unknown. 3600 s is at or above every
  observed hardware value (900/1800/3600), so the gate stays with the hardware in every case.

##### What this means for the run-time cutoff feature

**Decision, owner's call 2026-08-17: the cutoff feature tracks `maximumRunTime` only. Preset
timers are deliberately out of scope and must not be folded in.**

A preset stopping at its own configured duration is the system working as configured — the user
chose that duration. The feature exists to defeat the *hardware* gate cutting a shower short, not
to override a preset's own setting. Restarting a preset-timer stop would resume showers the user
deliberately configured to end.

Consequences to expect, none of which are faults:

* A preset-timer stop logs `verdict: "ignored"` with a large `off_by` (1800.3 s here). Correct,
  and the `reason` field still says exactly why nothing was restarted.
* `sensor.<valve>_zone_N_outlet_1_max_run_time` shows the hardware gate. It is not the number
  that will stop a preset-driven shower, and is not meant to be.

##### This finding is what removed the limit-guessing code

The integration used to infer limits the valve had never announced: `MissedCutoffWatcher`
collected declined pauses and, once three landed within 2 s of each other, offered the duration
as a "suspected limit" that `ACT_ON_LEARNED_LIMITS` could promote into a real one.

**Removed 2026-08-17.** It rested on an assumption this section disproves — that repeated
identical pause durations mean an unannounced *hardware* limit. They do not. They are the
ordinary signature of a **preset timer**, and presets 2-10 are the owner's own settings. The
machinery would have offered 1800 s here, correctly identifying a real timer, and acting on it
would have restarted showers configured to end.

With both limits now understood there is nothing left to infer, so the detector fires **only**
on announced `maximumRunTime`. `test_no_limit_guessing.py` asserts the absence, including that
six identical 1799.9 s pauses in a row produce no fire and no suspicion.

##### The rule, confirmed by a controlled two-cutoff experiment

Run 2026-08-13 with `maximumRunTime` lowered to 900 s and four outlets opened at staggered
times, on a **directly-driven** session (`presetOrExperienceId: 0`):

```text
15:16:35  outlet 4 on
15:20:16  outlet 3 added
15:24:07  outlet 2 added
15:28:03  outlet 5 added

15:31:35  0584c806 / 1184c840   outlet 4 expires (899.96 s)
                                 zone 2 -> 0x40 PAUSE, mask cleared
                                 ZONE 1 UNTOUCHED, still mask 06 (outlets 2,3)

15:35:16  0584c840 / 1184c803   outlet 3 expires (899.95 s)
                                 zone 1 -> 0x40 PAUSE, mask cleared
                                 ZONE 2 UNTOUCHED, still mask 03 (outlets 4,5)
```

**The valve sends `0x40` with a cleared mask to the zone that expired, and re-sends the
other zone's mask unchanged.** Both zones fired independently within one session, in opposite
order, so this is not an artefact of which zone happens to be primary.

Two further facts the experiment pins down:

* **Accuracy is sub-second.** 899.96 s and 899.95 s against a 900 s limit.
* Each zone runs its own clock, and they fire independently.

> #### ⚠️ CORRECTION (2026-08-14) — this experiment did **not** show a per-outlet timer
>
> An earlier reading of this run concluded "the timer is per outlet, not per zone", reasoning
> that outlet 3 expired while outlet 2, opened 3m51s later, was stopped as collateral.
>
> **The run cannot distinguish the two models.** In both cutoffs the outlet that "expired" was
> the one that *started its zone*, so "900 s since that outlet opened" and "900 s since that
> zone began flowing" name the same instant. Both hypotheses fit every line above.
>
> Captures from 2026-08-14 do distinguish them, and the timer is **per zone**:
>
> ```text
> 01:36:34  zone 1 all closed
> 01:37:00  outlet 1 on          <- zone 1 starts flowing
> 01:43:20  outlet 3 added
> 01:45:55  outlet 1 closed      <- the outlet that started the zone is now OFF
> 01:52:00  0x40, mask cleared   <- 900.0 s after 01:37:00
>                                   outlet 1 had run 189 s; outlet 3, 520 s
> ```
>
> No outlet was open for 900 s, yet the zone was cut at exactly 900 s from when it began
> flowing. Three of the four cutoffs in that session have this shape. Full statistics and the
> consequences for anything restarting the shower are in
> [`valve_hex.md`](valve_hex.md#-important--maximumruntime-is-reported-per-outlet-but-timed-per-zone).

##### …but not always both zones. A directly-driven session stops only the affected zone

The same valve behaved differently when the session was **not** preset-driven
(`presetOrExperienceId: 0`):

```text
02:46:07  0185c804 / 1185c800   zone 1 outlet 3 opens                  <- clock starts
03:39:03  0585c804 / 1185c801   zone 2 outlet 4 added, 53 min in
03:46:07  0585c840 / 1185c801   EXACTLY 3600 s later: zone 1 paused
                                and cleared — ZONE 2 UNTOUCHED, still 0x01
03:48:07  0585c800 / 1185c801   zone 2 still running two minutes on
```

So the two observed behaviours are:

| Session started by | `presetOrExperienceId` | Effect of one outlet hitting its limit |
|---|---|---|
| `solowritesystem` directly | `0` | **that zone** paused and cleared; the other zone runs on |
| preset / experience | non-zero | **both zones** paused and cleared, and the preset id clears to `0` |

**Resolved 2026-08-14 — the preset reading is correct.** Replaying the whole corpus with
zone-level timing gives 11 cutoffs, and exactly one of them paused a zone that was nowhere
near its own limit:

| Cutoff | Zone that expired | Other zone | Preset |
|---|---|---|---|
| 08-13 20:52:46 | zone 2, 3598.7 s | zone 1 paused too, at **1831 s** | **1** |
| the other 10 | one zone at its limit | untouched, still flowing | `0` |

Zone 1 had 1769 s left and was cleared anyway, so "always per-zone" is excluded: something
stopped a zone whose own timer had not run out, and a preset was active in that one case and
no other. The valve ends the *experience*, and the experience owns both zones.

Consequences for anything restoring a session:

* Replay a pre-cutoff snapshot; never rebuild from current state.
* Restore the zone that expired **and** any zone that is merely *paused* alongside it. The
  second zone's timing proves nothing — only its pause flag identifies it.

The consequence for anything trying to resume: **by the time the close is visible, the record
of what was running is already gone.** Rebuilding a command from current state can only
restore the outlet that fired. The state has to be captured *before* the cutoff message —
which is why `coordinator._remember_open_masks` keeps a snapshot and refuses to overwrite it
from a paused or all-closed word.

This session also reads as per-outlet at first glance — outlet 4 opened at 19:52:48 and the
cut landed 3598 s later, while outlets 2, 3 and 5, added 8, 30 and 18 minutes in, were
nowhere near their own limits. But outlet 4 is also what *started zone 2 flowing*, so the two
clocks coincide again. **It is the zone's timer**; see the correction above.

#### ⭐ CONFIRMED 2026-08-17 — the 60-minute session ceiling, and it stops rather than pauses

> ### ⚠️ SCOPED 2026-08-18 — this ceiling does **not** count when Home Assistant starts the shower
>
> Everything below is accurate for a session the Anthem Plus controller commanded, which is
> what was measured on 2026-08-17. A shower started through `solowritesystem` is a different
> case, and the controller's clock does not run for it at all.
>
> Measured 2026-08-18: a `solowritesystem`-started shower ran **5172.7 s wall clock** — 86
> minutes — past a 60-minute ceiling that never fired, while the controller published **zero**
> MQTT messages for the entire session. A clock anchored at the open would have expired at
> 08:52:01.179 local; the shower ran until 09:18:13.
>
> Full walkthrough, both capture files quoted in full:
> [case study 1](../case_studies/01_ha_driven_shower_hub_blind.md).
>
> **What still holds:** the mechanism, the arithmetic, the `0x00` signalling, and the ceiling
> itself for panel-started showers. **What is now scoped:** who it applies to. A GCS
> *preset*-started shower remains unmeasured.
>
> ### ✅ And the mitigation is now the fix — 2026-08-18
>
> **Set the valve's `maximumRunTime` and the controller's Max Shower Duration to the SAME
> value.** Measured across five case studies: the valve fires slightly **early** (−0.08 to
> −0.23 s against its limit) and the controller slightly **late** (+0.20 to +1.00 s), so with
> equal durations the valve's `0x40` pause always arrives first — by 1.087 s in the one
> session where both were at 900 s — and is always the actionable signal. The controller's
> `0x00` then lands on a zone Endless Shower has already restored.
>
> That is why `runtime_cutoff.py` **requires the pause flag again** as of 2026-08-18. A `0x00`
> at a matching duration is now declined and logged at WARNING naming this configuration as
> the likely cause. See [`../case_studies/03_both_ceilings_at_15_minutes.md`](../case_studies/03_both_ceilings_at_15_minutes.md).

**There is a third timer.** Beyond the per-outlet `maximumRunTime` and a preset's own `time`,
the valve ends a zone **3600 s after that zone first started flowing** — and that clock keeps
running while the water is off between restarts, so nothing that reopens the valve can
outrun it.

Measured on a directly-driven session (`presetOrExperienceId: 0`), Endless Shower on,
`maximumRunTime` `900` on all six outlets:

```text
17:43:07.255  0584c804              zone 1 opens                <- session clock starts
17:58:07.135  0584c840  899.88 s    paused -> restarted at 17:58:08.582   (1.45 s off)
18:13:08.496  0584c840  899.91 s    paused -> restarted at 18:13:10.690   (2.19 s off)
18:28:10.452  0579c840  899.76 s    paused -> restarted at 18:28:11.987   (1.54 s off)
18:43:07.462  056ec800  895.47 s    STOPPED — no 0x40, nothing restarted it
```

The arithmetic is what identifies it. Flow: 899.88 + 899.91 + 899.76 + 895.47 = **3595.02 s**.
Water-off gaps: 1.45 + 2.19 + 1.54 = **5.18 s**. Total **3600.20 s**, wall clock, from the
zone's first opening — the final leg short of its own 900 s limit by exactly the time the
restarts had the valve closed.

Two things follow, and both matter to anything restarting a shower:

* **The ceiling counts the gaps.** It is wall clock since the zone opened, not accumulated
  flow — accumulated flow would have allowed a full fourth leg and cut at 3600 s of water.
* **It signals with `0x00`, not `0x40`.** Every `maximumRunTime` expiry in the corpus pauses;
  this one stops. That is consistent with it being a session *end* rather than a hold — the
  valve reported `configWriteAllowedFlag` back to `1` at the same instant, which it does when
  the primary valve goes idle, while zone 2 kept running for another six minutes untouched.

**✅ MECHANISM CONFIRMED by the owner, 2026-08-17 — it is the HUB's own timer, not the
valve's.** The two devices each enforce a maximum shower duration, independently, and they
signal it differently:

| | where it is set | value on this install | what it writes |
|---|---|---|---|
| **GCS valve** | `maximumRunTime`, per outlet | 900 s (15 min) | **`0x40`** — pause, mask cleared |
| **Anthem Plus HUB** | its own max shower duration | **60 min** | **`0x00`** — stop |

So `0x00` was never a strange valve behaviour. It is the HUB stopping the shower, using the
same plain stop every HUB-issued stop uses — exactly what the control-surface table above
already says the Anthem Plus panel writes. The valve pauses; the controller stops. Once the
two timers are seen as belonging to two devices, every number lines up.

⚠️ **This also corrects a belief carried in earlier notes: the HUB's shower duration is NOT
ignored.** It was thought to be inert because of the firmware 2.88 bug that broke HUB flow
control. It is live, it is still 60 minutes, and it ended this shower.

**It is timed per zone, from the start of that zone's continuous run.** The stop cleared zone
1 only; zone 2 kept running for another six minutes and was never touched. Zone 1's clock
started at 17:43:07 — when zone 1 *re-opened* — not at 17:39:07 when the shower itself began,
because zone 1 had been closed from 17:39:37 to 17:43:07. Zone 2's own 60 minutes was never
reached; its last continuous run began at 18:21:25.

**A 3.5-minute gap resets the HUB's clock; a 1.5-second one does not.** That is the whole
reason the ceiling caught us: our restore closes the valve for 1.2–2.2 s, which the HUB reads
as the same session continuing, so the gaps are counted rather than resetting anything.
**Where the threshold sits between 1.5 s and 3.5 min is unmeasured.**

**Where the setting lives is unknown.** It is in **no capture on disk** — not the local
`hub_config` read, not any cloud HUB response; a search of every HUB and config capture for a
field valued 60 or 3600 returns nothing. Reading it, so the cutoff detector could use it as an
announced limit instead of inferring anything, is an open item.

> ##### ⚠️ Consequence: "a cutoff always pauses" was retired on 2026-08-17
>
> The detector required the `0x40` flag, so this cutoff was logged
> `verdict: "ignored", reason: "stopped (0x00) rather than paused (0x40)"` and the shower
> stayed off with the owner still in it. **At the owner's instruction the flag is no longer
> required** — `0x00` and `0x40` are treated alike, and duration does the whole job.
>
> Replaying all 1267 valve samples in the corpus through the changed detector fires **25**
> times, every one a genuine timer event within tolerance of a real limit, and **no false
> positives** — the 91 recorded stops never came closer than 123 s to a limit, this ceiling
> excepted at 4.53 s. What it costs is stated in `anthem_plus/runtime_cutoff.py`: a
> deliberate stop landing inside the tolerance window now gets restarted, and Home
> Assistant's own stops are protected by `note_local_write()`'s grace rather than by the flag.
>
> ⚠️ **Dropping the flag does not catch the ceiling at every Max Shower Duration.** A
> duration must still match an announced `maximumRunTime` within `CUTOFF_TOLERANCE_SECONDS`,
> and 3600 only lands near one because the limit is 900 (4 × 900 ≈ 3600, minus the gaps). At
> 20 or 25 minutes the ceiling falls mid-leg and is logged as an ordinary unexplained stop.
> Closing that needs the session clock tracked explicitly.

#### A valve reboot dumps the complete set — the only known way to force it

**Power-cycling the valve emits one `READ_GCS_OUTLET_CONFIG_CFG` per outlet, in id order,
about a second apart, a few seconds after `DEVICE_REBOOT_STS`.** Measured 2026-08-13 on the
K-28212:

```text
19:41:43.443  DEVICE_REBOOT_STS
19:41:48.614  READ_GCS_OUTLET_CONFIG_CFG   outLetId 0   maximumRunTime 3600
19:41:49.804  …                            outLetId 1
19:41:51.008  …                            outLetId 2
19:41:52.023  …                            outLetId 3
19:41:53.227  …                            outLetId 4
19:41:54.329  …                            outLetId 5   (11 s after the reboot marker)
```

All six carried identical limits: `maximumRunTime` 3600 s, flow 16–200, temperature 150–450.
Outlet types were 62, 52, 1, 11, 39, 21 — the same as the documented mapping.

Two consequences:

* **There is a way to know when the set is complete after all.** `DEVICE_REBOOT_STS` marks
  the start, and one message per outlet follows. Anything needing the full configuration can
  ask the owner to power-cycle the valve rather than waiting indefinitely.
* **Nothing can request this over the network.** Every plausible REST name 404s
  (`gcs-outlet-config`, `gcs-outletconfig`, `gcs-outlet-configuration`, `gcs-valve-config`),
  so a physical reboot is the only trigger anyone has found. That is why the integration
  **persists** what it learns — see `CONF_OUTLET_RUN_TIMES`.
Useful *after* setup as a cross-check that the selected model matches the hardware.

#### It cannot give the per-zone split on its own

There is **no zone field** — just a flat `outLetId`. On the test system the ids line up as
zone 1 then zone 2, but two readings fit that evidence equally and a 3+3 system cannot
separate them:

| | A: ids are dense | B: ids are slotted per zone |
|---|---|---|
| K-28212 (3+3) | `0 1 2 3 4 5` | `0 1 2 3 4 5` — identical |
| K-28211 (2+2) | `0 1 2 3` | `0 1 _ 3 4 _` — **gaps reveal the split** |

If **B** holds, a gap in the id sequence would give the per-zone counts directly, and the
model selection could be dropped for any account that receives these messages. Confirming it
needs a capture from a **K-28209, K-28210, or K-28211** — any valve that does not populate
all six slots.

`outLetFlags` is `1` for every outlet here, so it does not distinguish installed from absent
on this system either.

## 1c. `writeoutletconfig` — setting Max Shower Duration

**Sources:** JADX decompile of Konnect **3.0.1**, plus live verification on this account
2026-08-17. ⚠️ **The store version at the time of writing is 3.0.5**, so every statement below
that describes the *app* is pinned to 3.0.1 and may have moved. Statements about the *device*
were verified live.

```
POST /platform/api/v1/commands/gcs/writeoutletconfig
```

### ⚠️ Where the app disagrees with the hardware

This is the important framing: **what the Konnect app exposes is narrower than what the valve
holds, and in one case the app misreads the valve outright.** Do not infer device limits from
app behaviour.

| | Konnect 3.0.1 | This valve, live |
|---|---|---|
| Max Shower Duration picker | **15/20/25/30 min** (900–1800 s) — `IntRange(15,30)` filtered to multiples of 5 | holds **3600** |
| Value→index mapper `p1()` (dead code) | 15–60 min, step 5 → **900–3600** | consistent |
| Upper bound constant / clamp / validation | **none anywhere on the send path** | unknown |

`p185fj/o.java` declares `min=15, max=30, step=5`, but **only the step is ever read** — nothing
references the bounds. They document intent and enforce nothing.

So 3600 is legal in the designed domain and simply unreachable from 3.0.1's picker. 2700 has
never been observed for the same reason: no shipped picker could produce it, even though `p1()`
maps it to index 6.

> ### 🚨 3.0.1 misreads any value above 1800 — and one tap rewrites it
>
> `p185fj/o.java:24-36` snaps the device's value into 15–30 before choosing a wheel index.
> Trace `a(60)`: `60 >= 20` → `i11 = 25`; `60 < 25` false; `(60 >= 30) && (60 == 30)` false →
> **returns 25**.
>
> **On a valve set to 3600, the app displays 25 min, and tapping Save writes 1500.** Anything
> above 1800 is mis-displayed and one accidental Save from being silently cut. A vendor defect;
> nothing this integration can prevent. Worth telling any user who has a duration above 30 min.

### The envelope

Wrapper key is **`gcsOutletConfigControlModel`** — same envelope as `writepreset`, different key
and inner model. Every value is a **string**.

```json
{ "deviceId": "gcs-…", "sku": "GCS", "tenantId": "<tenant-guid>",
  "gcsOutletConfigControlModel": {
    "outLetId": "0", "outLetType": "62", "outLetFlags": "1",
    "minimumOutletTemperature": "150", "defaultOutletTemperature": "388",
    "maximumOutletTemperature": "450",
    "minimumFlowrate": "16", "defaultFlowrate": "200", "maximumFlowrate": "200",
    "maximumRuntime": "3600" } }
```

`maxVolume` exists in the model and the app sends it on its commissioning path; it is absent
from both read surfaces here, so this integration omits it. `purge` is declared but **has no
setter** — R8 stripped it as unreachable, so the app's real body is 11 keys and never 12.

### 🚨 The read and write key spellings differ

| MQTT read (`READ_GCS_OUTLET_CONFIG_CFG`) | REST write body |
|---|---|
| `maximumRunTime` | **`maximumRuntime`** |
| `maximumFlowRate` | **`maximumFlowrate`** |
| `minimumFlowRate` | **`minimumFlowrate`** |
| `defaultFlowRate` | **`defaultFlowrate`** |

Capital `T`/`R` on the read side, lowercase on the write side. The temperature keys and
`outLetId` / `outLetType` / `outLetFlags` match on both.

**Do not build a write body by copying MQTT keys.** Gson drops unmatched keys silently, the API
returns 201, and nothing is applied — four of eleven fields would vanish. That is the same
lenient-success failure that cost seven guesses on `writepreset`, and it would look exactly like
a device-side limit.

### ✅ CORRECTION — outlet config IS readable on demand

**`gcsadvancestate` carries `setting.valveSettings[].outletConfigurations[]`.** Verified live
2026-08-17. This integration has always called that endpoint — `topology.py` reads
`noOfOutlets` from the same response — and simply never looked inside the array.

This corrects a claim repeated in `const.py` and in §1a of this document: that `maximumRunTime`
is *"otherwise unobtainable on demand"* and that *"there is no REST endpoint for outlet
configuration"*. The **read-only paths** listed as 404 (`gcs-outlet-config` and friends) really
do 404 — but the data was reachable all along under `gcsadvancestate`.

### Units — the read source decides whether you convert

| Read source | Temperatures | Flow rates | Before writing |
|---|---|---|---|
| MQTT `READ_GCS_OUTLET_CONFIG_CFG` | tenths °C (`388`) | byte units (`200`) | **pass through** |
| REST `gcsadvancestate` | °C (`38.8`) | display (`50`) | **×10 and ×4** |

Verified live: REST returned `maximumOutletTemperature: "45"`, `minimumFlowrate: "4"`,
`defaultOutletTemperature: "38.8"` — display units, settling an open question the decompile
could only infer. The write body wants wire units either way (`v0()` = ×10, `t0()` = ×4).

`v0()` special-cases one value: 49.0 °C → `488`, not 490 — 488 tenths is exactly 120 °F.

> 🚨 **`maximumOutletTemperature` is the scald limit.** Whole-record replace means omitting it,
> or writing it on the wrong scale, changes it. Assert the outgoing value matches what was read
> before every write, and abort if not.

### One outlet per call, chained on success

There is **no list form**. The app writes N sequential calls, one per outlet, each carrying that
outlet's complete record with the same `maximumRuntime`, and only issues the next after a 2xx
(`p185fj/m.java:514-518`). **A failure mid-loop leaves outlets in mixed state.**

### The response proves nothing

```java
class CommandSuccessResponseModel { String correlationId; Long timestamp; }
```

No status, no error code, no echo of the applied value. The app performs **no read-back** — on
the last outlet's success it waits 5000 ms and shows a local dialog. So a 201 means *accepted for
delivery*, never *applied*. **Verify by reading the value back**, and allow time: an immediate
`gcsadvancestate` read still shows the old value, because that document only updates once the
device reports.

### ✅ Verified live — 2026-08-17, K-28212, six outlets

Eighteen writes, three values, shower off. **Every one applied exactly. Nothing was clamped,
nothing was ignored, and no other field moved.**

| value | outlets written | read back | scald limit | flow bounds |
|---|---|---|---|---|
| **900** | 6 | `900 x6` | `45` unchanged | `50` / `4` unchanged |
| **1800** | 6 | `1800 x6` | `45` unchanged | `50` / `4` unchanged |
| **3600** | 6 | `3600 x6` | `45` unchanged | `50` / `4` unchanged |

Every call returned **HTTP 201** with `{correlationId, timestamp}`.

**This is the app-vs-hardware gap made concrete.** Konnect 3.0.1's picker can only produce
900–1800, yet **3600 was written and accepted**, exactly as the dead `p1()` mapper's 900–3600
domain predicts. The picker range is a UI limitation, not a device limit.

⚠️ **Values above 3600 have deliberately not been tested.** Everything above is inside the
designed domain; the real ceiling question is still open.

#### ❌ 3600 is the ceiling — three values above it were rejected

| value | > 3600 | ×300 | ×900 | in 3.0.5 picker | result |
|---|---|---|---|---|---|
| 3601 | yes | no | no | no | **rejected** |
| 3900 | yes | yes | no | no | **rejected** |
| **4500** | yes | **yes** | **yes** | no | **rejected** |

4500 satisfies every grid hypothesis on the table — 300, 900 and 1800 — so grid rules are
eliminated as the explanation for its rejection. **3600 is the effective maximum.**

**The rejection signature is silence.** Every one returned **HTTP 201** with a `correlationId`,
then produced *nothing*: no device push, no state change, no error anywhere. Identical to a
malformed-body rejection. A 201 from this endpoint means "accepted for delivery" and nothing
more, for out-of-range values as much as for wrong shapes.

What makes that readable at all is the null test: writing 3600 **over** 3600 *did* produce a
device push. So silence means rejected, not "nothing changed so nothing was announced". Without
that control the two are indistinguishable.

> ⚠️ **Still open, and deliberately unanswered:** whether 3600 is a *ceiling* or simply the top
> of an *allowed list*. The 3.0.5 picker is curated rather than uniform — 15/20/25/30/45/60 min
> = 900/1200/1500/1800/2700/3600 — skipping 35/40/50/55. A 300-multiple absent from that list,
> **2100** (35 min), would decide it. Not tested; the owner's interest was only in whether 3600
> could be exceeded, and it cannot.
>
> It matters only for entity design: a `number` bounded 900–3600 step 300, versus a `select` of
> exactly six values.

##### Build note — the picker moved between app versions

| Konnect build | Max Shower Duration options |
|---|---|
| **3.0.1** (the decompile) | 15/20/25/30 min → 900–1800 |
| **3.0.5** (current store) | 15/20/25/30/45/60 min → 900–3600 |

So 3.0.1's narrow list really was a UI limitation, exactly as the dead `p1()` mapper implied —
and 3600 was writable all along. **The current app's own maximum now coincides with the device's.**
This is the cleanest example of the rule that app behaviour is not evidence of hardware
capability: same valve, same firmware, two different apparent limits.

#### Four practical findings from the run

1. **An immediate read-back lies.** `gcsadvancestate` is a cloud document that updates only when
   the device reports. Reading it ~1 s after a 201 still showed the *old* value; the change
   appeared within the 25 s wait. Do not conclude "ignored" from a fast read — that is exactly
   how a working write looks like a device-side limit.
2. **A no-change write still triggers a device push.** The null test — writing 3600 over 3600 —
   produced a `READ_GCS_OUTLET_CONFIG_CFG` announcement anyway. So `writeoutletconfig` is a
   reliable way to **force** an outlet-config announcement, which is otherwise unprompted and
   arrives roughly twice a session. That has obvious value for the cutoff feature's cold start.
3. **The integration picks it up with no extra work.** `_learn_run_times` sees the device push
   and persists to the config entry unaided — observed mid-sweep holding `1800` for all six, then
   `3600` after the restore. The whole loop is: write → cloud → valve → MQTT → coordinator →
   config entry.
4. **The write order is per outlet and the device echoes per outlet.** Six writes produced six
   pushes, ~0.5 s apart, matching the app's chained loop.

### The app refuses to send while water is running

`p185fj/h.java:284-303` gates Save on three conditions — offline, valve not found, and any outlet
running — the last raising *"Settings cannot be saved while any outlet is running."* Whether the
cloud or firmware enforces this too is untested; the app never gets that far. **Run any
experiment with the shower off.**

Nothing else is sent: no `uiconfigsuccess`, no state re-read, no follow-up of any kind.

## 2. Direct "turn on water" = `solowritesystem` (no preset read needed)

`POST /platform/api/v1/commands/gcs/solowritesystem`
Body `AnthemWriteSoloStatusRequestModel` = `{deviceId, sku:"GCS", tenantId, gcsValveControlModel}`.

```json
{
  "deviceId": "gcs-sio32343h7", "sku": "GCS", "tenantId": "<oid>",
  "gcsValveControlModel": {
    "primaryValve1":   "0179C801",
    "secondaryValve1": "1179C801",
    "secondaryValve2": "00000000"
  }
}
```

Word layout is `[valve index + status/temp-high][temp low][flow][outlet mask + state]` —
decoded fully in [`valve_hex.md`](valve_hex.md). For the example above: byte 0 `01` =
valve 1 with the temperature high bit, temp `79` → 37.7 °C ≈ 100 °F, flow `C8` = 100%,
mask `01` = outlet 1 open.

`secondaryValve2` … `secondaryValve7` are `00000000` on this system.

> **On a two-valve system, send a real word for BOTH valves every time.** `00000000` means
> "no valve addressed" and appears to make the device discard the *entire* command — a
> command sent as `v1=00000000 v2=11849C01` opened nothing, while `v1=0185C800 v2=1185C801`
> (an addressed but closed valve 1) opened valve 2 immediately. A valve that should stay
> shut gets mask `0x00`, not the all-zero sentinel.

**Key point:** the library reads the `default shower` preset only to reuse your configured
temp/flow/outlets — a convenience, **not required**. To just turn on water, send
`solowritesystem` with a fixed word and skip the preset read.

**`solowritesystem` is how the app drives the shower**, but it is *not* the only way to run a
preset — see §2a. An earlier revision of this document claimed
`controlpresetorexperience` merely "selects" a preset and that a `solowritesystem` follow-up
was unavoidable. That was a symptom of the library sending the wrong body: with the correct
`{preset, action}` shape, activation is a single call.

## 2a. Presets — read, activate, update, create

**Live-verified 2026-08-12** unless a row says otherwise. Bodies originate in the Konnect
3.0.1 decompile.

| Purpose | Method + path | Body | Status |
|---|---|---|---|
| Read | `GET /devices/api/v1/device-management/gcs-preset/{deviceId}` | — | ✅ verified |
| Activate | `POST …/commands/gcs/controlpresetorexperience` | `{deviceId, sku, tenantId, preset, action:"On"}` | ✅ **verified live** |
| Stop | same | same with `action:"Off"` | ✅ **verified live 2026-08-13** — pauses (0x40), clears preset id |
| Update existing | `POST …/commands/gcs/writepreset` | wrapper `gcsPresetControlModel` | ✅ **verified live** |
| Create new | `POST …/commands/gcs/createpreset` | flat, no wrapper, no `presetId` | ❓ untested |

### Activate — one call, no valve write

```json
{ "deviceId": "…", "sku": "GCS", "tenantId": "<oid>",
  "preset": "<presetId>", "action": "On" }
```

**Verified live**: preset 1 activated, water ran for 60 s, zone 2 outlet 1 opened at the
preset's stored temperature and flow. **The valve runs the stored preset itself** — no
`solowritesystem` follow-up, no select-then-open sequence.

```text
13:58:06  activate preset 1     -> {"correlationId": "03f76e3c-…"}
13:58:11  v2 out=[100] t=38.9 f=50
13:58:53  v1 atTemp=1              primary valve asserts while zone 2 runs
```

The REST response carries **only a `correlationId`** — it says the request was accepted, not
that anything happened. Judge success from `gcs-state` or MQTT, never from the response.

#### Activation applies only the zones it opens an outlet on

Preset 1's valve1 word was `0185C8` — 38.9 °C, mask `0x00`. The valve **ignored that
setpoint**: valve 1 stayed at `017cc800` (38.0 °C) before, during, and after, while valve 2
took the preset's values.

```text
preset valve1 = 0185C8 (38.9C, no outlets)  ->  device valve1 unchanged 017cc800 (38.0C)
preset valve2 = 0585C8 (38.9C, outlet 1)    ->  device valve2 became   1185c801 (38.9C)
```

So a preset **cannot** set an idle zone's temperature. Only a zone it also opens.

#### `GCS_RECIEVED_STS` — a command acknowledgement

Activation emits an MQTT message not in the documented GCS code list, ahead of the state
message (Kohler's spelling):

```json
{"status": "messageRecievedAndExecuted", "sysId": "GCS-INVE989T6Y", "code": "GCS_RECIEVED_STS"}
```

Two occurrences across all captures. Since the REST response proves nothing, this is the
cheapest signal that a command actually **executed** rather than merely being accepted.

> ### ✅ "Default shower" is created by the SETUP WIZARD, not a factory constant
>
> Established 2026-08-14 by factory resetting the valve and **skipping setup entirely**:
>
> ```text
> preset  1  name=''  time=0  V1=000000  V2=000000
> preset  2..10       same — all ten slots blank
> ```
>
> The wizard asks which outlets are the default and then requires a water-line calibration;
> preset 1 is written from those answers. Skip setup and the valve has **no presets at all**.
>
> This explains why preset 1's stored flow drifted across every capture (36.0/78.0 →
> 34.5/82.5 → 35.5/79.0) and why its `time` moved between 1800 s and 3600 s — it was never a
> fixed reference. Anything keyed to preset 1's values is keyed to *that install's* setup run.
>
> **Factory defaults, visible for the first time on an un-set-up valve:**
> `maximumRunTime` **1800 s**, `defaultOutletTemperature` **380** (38.0 °C),
> `minimumFlowRate` 16, `maximumFlowRate` 200, `outletType` null.
>
> #### Confirmed again 2026-08-15, and preset 1 is back
>
> The owner completed the default-outlet setup that had been skipped, and preset 1 reappeared:
>
> ```text
> 2026-08-15T00:00:04  preset 1  name='Default shower'  time=1800  V1=017cc8  V2=057cc8
> 2026-08-15T00:20:31  preset 1  name='Default shower'  time=1800  V1=0184c8  V2=0584c8
> ```
>
> Two results, both new:
>
> * **`time` came back as `1800`, the factory default above** — not the `3600` it held before
>   the reset. **The owner reports this 30-minutes-per-outlet value overrides the max shower
>   time set on the HUB.** The valve re-announces `maximumRunTime` for all six outlets within
>   **5–11 s of every reboot** (08-13 19:41:48 → 3600; 08-14 20:04:37 → **1800**), so a limit
>   set on the panel can silently revert. Changes *not* near a reboot are the owner's.
> * **Its stored flow is `C8` — 100% on both zones**, where every pre-reset capture held a
>   ceiling value (34.5/82.5, then 35.5/79.0). A preset fossilises whatever the valve reported
>   when it was written, so this is independent confirmation that an uncalibrated valve has **no
>   ceiling at all** — see
>   [`valve_hex.md`](valve_hex.md#an-uncalibrated-valve-has-no-ceiling--measured-2026-08-15).
>
> The `defaultOutletTemperature` 380 also shows up directly: `017cc8` decodes to 38.0 °C.

### `presetOrExperienceId` — which preset is running

Carried in **every** `GCS_SOLO_STS` and in `gcs-state`, so the device tells you which preset
is active without being asked. **It latches for the whole session**, it is not a one-shot
blip. Verified live 2026-08-12 across activation, pause, resume, stop, and manual writes:

| Event | Valve word | `presetOrExperienceId` |
|---|---|---|
| Activate preset 4 | `v2=1186c801` | **`4`** — latches |
| **Pause** (mask `0x40`) | `v2=1186c840` | **`0`** — cleared |
| Resume / re-activate | `v2=1186c801` | **`4`** — latches again |
| Setpoint changed mid-session | `v2=118ac801` | **`4`** — **survives** |
| **Stop** (mask `0x00`) | `v2=118ac800` | **`0`** — cleared |
| Outlet opened by `solowritesystem` | `v2=118ac801` | **`0`** — never set |

Four consequences:

- **Pause and stop both clear it.** The field cannot distinguish a held session from a
  finished one — read the pause bit for that.
- **It survives temperature and flow changes.** Adjusting setpoints mid-session leaves the
  preset latched, so "which preset is running" is not invalidated by the user nudging a dial.
- **Only a preset activation sets it.** Opening an outlet with `solowritesystem` leaves it at
  `0`, even with water running. It means *"a preset is driving this"*, not *"water is on"*.
- **The clear lags by one message.** On stop, the device emits the new valve state still
  carrying the old id, then a second message with `0`, both inside the same second:

  ```text
  21:47:39  presetId=4  v2=1184c800   outlets already closed
  21:47:39  presetId=0  v2=1184c800   id cleared
  ```

  Anything driven off this field will briefly show the preset after it stopped.

Presets and **experiences** share this one field, which is why it is not called `presetId`.
Resolve it against the preset list's `isExperience` flag before displaying it as a preset.

> #### ⚠️ IMPORTANT — a preset activated **during warm-up** never latches
>
> Reported by the owner and confirmed twice: start a preset while the valve is running its
> warm-up sequence and `presetOrExperienceId` **stays `0` for that whole session**, even
> though the preset's own valve word is applied.
>
> ```text
> 22:06:26  GCS_WARM_STS                                  warm-up already running
> 22:06:54  GCS_RECIEVED_STS                              owner activates preset 1
> 22:06:55  Z2=1184A501  preset=0  warmUpInProgress       word applied, id NOT set
> 22:08:03  Z2=1184C840  preset=0  warmUpNotInProgress    warm-up ends -> 0x40 pause
> ```
>
> **The effect lands, the label does not.** `1184A501` is the preset's own word — note the
> 82.5% flow, which no Home Assistant write ever produces (those are always 100%). The valve
> is doing what the preset says; it just never records *which* preset.
>
> **It does not latch retroactively when warm-up finishes.** A second activation is required,
> and the corpus contains exactly that case:
>
> ```text
> 12:51:34  GCS_RECIEVED_STS                              first activation, during warm-up
> 12:51:34  Z2=1184A501  preset=0  warmUpInProgress       id NOT set
> 12:52:39  Z2=1184A540  preset=0  warmUpNotInProgress    warm-up ends, valve pauses
> 12:52:47  GCS_RECIEVED_STS                              owner activates AGAIN
> 12:52:48  Z2=1184A501  preset=1  warmUpNotInProgress    id latches this time
> ```
>
> Across the whole corpus, **all 12 samples carrying `warmUpInProgress` have
> `presetOrExperienceId: 0`** — the field has never once been non-zero during warm-up.
>
> Note also what warm-up *ending* does: it writes `0x40` with the mask cleared, so the water
> stops and the session is over. That is why the first case above never latched even after
> warm-up finished — there was no session left to label.
>
> Consequences:
>
> * Anything answering "is a preset driving this" is **wrong during warm-up**, in the
>   direction of under-reporting. `binary_sensor.anthem_valve_preset_active` reads OFF for a
>   preset that is demonstrably in effect.
> * Do not infer "no preset" from `0` while `warmUpStatus` is `warmUpInProgress`. The honest
>   reading of that combination is *unknown*.
> * The run-time cutoff is unaffected: it keys off duration, never the preset id. (It keyed
>   off the pause flag too until 2026-08-17 — see "the 60-minute session ceiling".)

### Stop — `action:"Off"` is VERIFIED (2026-08-13), and it pauses rather than stops

Fired for the first time on 2026-08-13 against a running preset 1. It is accepted, it stops
the water, and it clears `presetOrExperienceId` to `0`:

```text
21:30:56  preset=1  0584c800 / 1184a501   preset running, outlet 4 open
21:31:22  preset=0  0584c800 / 1184a540   action:"Off" -> zone 2 byte 3 = 0x40 PAUSE
```

**The distinguishing detail is `0x40`, not `0x00`.** Stopping the same outlet through
`solowritesystem` with mask `0x00`, minutes later on the same valve, gives a plain stop with
no pause flag:

```text
21:31:58  preset=0  057cc800 / 117cc801   direct write, outlet 4 open
21:32:13  preset=0  017cc800 / 117cc800   solowritesystem mask 0x00 -> byte 3 = 0x00
```

So the two stop paths are distinguishable on the wire:

| Path | Byte 3 of the affected zone | Preset id |
|---|---|---|
| `{preset, action:"Off"}` | `0x40` — **pause** | cleared to `0` |
| `solowritesystem` mask `0x00` | `0x00` — stop | unchanged |

**This identifies a preset-driven run-time cutoff.** Such a cutoff produces `0x40` and clears
the preset id — the `action:"Off"` signature, not the `solowritesystem` one. ⚠️ It is *not* a
complete test for "was this the valve's timer": the 60-minute session ceiling ends a directly
driven zone with `0x00` and no preset was ever involved. The valve ends the *experience*
rather than closing an outlet, which is why a preset-driven session loses both zones: a
preset is definitionally a two-zone object, carrying a 6-hex word for `Valve1` **and**
`Valve2` on every stored preset.

#### Confirmed on a two-zone preset: the match is exact

Repeated with a preset that opens outlets in **both** zones — `Test twozone`, whose words
`1186c8` / `0586c8` decode to zone 1 outlet 3 and zone 2 outlet 1:

```text
21:39:53  preset=2  0586c804 / 1186c801   both zones running
21:40:23  preset=0  0586c840 / 1186c840   action:"Off" -> BOTH zones 0x40 PAUSE
```

Set beside the run-time cutoff measured an hour earlier:

```text
20:52:46  preset=0  0584c840 / 1184c840   CUTOFF, preset-driven session
```

**The same double `0x40`, the same preset-id clear, the same surviving temperature byte.**
The only difference is the setpoint itself (`86` = 39.0 °C here, `84` there), which is just
the two presets' own temperatures.

That closes the question the preset-1 run left open. `action:"Off"` pauses **every zone the
preset is driving** — one zone when the preset opens one, both when it opens both — and it
is what the valve does internally when a run-time limit is reached. The behaviour is one
mechanism, not two:

| Session | What the cutoff ends | Zones paused |
|---|---|---|
| preset / experience | the preset | every zone that preset drives |
| `solowritesystem` direct | nothing — no preset exists | only the zone that fired |

So "a preset-driven cutoff stops both zones" is not a special case. Ending a preset stops
what the preset was running, and a preset is a two-zone object by construction.

#### Original note, kept for context

`action` is documented as an `"On"` / `"Off"` toggle, but **only `"On"` has ever been
fired.** The verified stop is `solowritesystem` with mask `0x00` (`stop_pair()`), which has
run many times. Prefer it: a stop is the wrong place to exercise an unproven code path.

> **Library discrepancy.** `kohler-anthem` posts `presetOrExperienceId` to this endpoint.
> The app's model has no such field — it uses `preset` + `action`. The library's body is
> accepted with a correlationId and then ignored, which is why presets "returned success but
> nothing happened", and why a `solowritesystem` hack was bolted on to compensate.
> Confirmed live: the library's body left `presetOrExperienceId` at `'0'` and moved no valve.

### Update — `writepreset`

```json
{ "deviceId": "…", "sku": "GCS", "tenantId": "<oid>",
  "gcsPresetControlModel": {
    "presetId": "<id>",
    "name": "My Shower", "time": "1800", "volume": "",
    "valve1": "0179c8", "valve2": "1179c8",
    "valve3": "", "valve4": "", "valve5": "", "valve6": "",
    "valve7": "000000", "valve8": "000000"
  } }
```

`createpreset` takes the same fields **flat** — no wrapper, no `presetId`.

Valve values are the **3-byte preset word** ([`valve_hex.md`](valve_hex.md)), not the 4-byte
command word. Unused valves are empty strings.

**Verified live 2026-08-12** on both presets, judged by read-back:

```text
preset 2 "Test favourite"   1190c8 / 0589c8  ->  0185c8 / 0585c8   APPLIED
preset 1 "Default shower"   018448 / 05849c  ->  0185c8 / 0585c8   APPLIED
```

Preserve `name`, `time`, and `volume` from the existing preset unless you mean to change
them — the write replaces the whole record, so an omitted field is a silent edit.

#### It rewrites the derived `outlets` array too

Only `hexString`s were sent, yet the server's per-outlet `outlets` array followed byte 0:

```text
preset 2 Valve1  byte0 11 -> 01   outlets 001 -> 000
preset 2 Valve2  byte0 05 -> 05   outlets 100 -> 100  (unchanged, as sent)
```

The backend **recomputes `outlets` from byte 0 of `hexString`** — independent confirmation,
from the write direction, that preset words carry the outlet mask at `0x04`/`0x08`/`0x10`.

#### Change only the temperature by masking byte 0

Because byte 0 mixes outlet bits with the temperature's top two bits, rebuilding it from
scratch silently drops the outlet assignment. Mask instead, and copy the flow byte:

```python
new_byte0 = (old_byte0 & 0x1C) | ((tenths >> 8) & 0x03)
word = f"{new_byte0:02X}{tenths & 0xFF:02X}{old_byte2:02X}"
```

#### Prefer whole Celsius — but it is a convention, not a constraint

App-created presets mostly hold whole Celsius: `39.0`, `40.0`, `41.0`. A Fahrenheit
conversion lands between them (102 °F → 38.9 °C), which the device accepts but is not what it
usually stores. 38.0 °C is `017cc8`, matching exactly what the valve reports when idle
(`017cc800`).

**It is not a hard rule, though.** One app-created preset stored **38.3 °C** — which is
100.94 °F, i.e. a whole *Fahrenheit* 101 °F. So the app can produce tenths, and the storage
is plain tenths-of-°C either way. Treat whole Celsius as the tidy default to write, not as
something the device enforces or the app guarantees.

### Three ways this returns success and changes nothing

The backend is lenient: it accepts the request and applies nothing when the shape is wrong.

1. Posting to `createpreset` when you meant to edit — that makes a *new* preset, never edits.
2. Omitting the `gcsPresetControlModel` wrapper, or `presetId` inside it — no target.
3. Sending 4-byte command words where 3-byte preset words belong.

All three were hit in practice. The wrapper key was eventually found by probing: seven other
candidate names returned a .NET `NullReferenceException`, `gcsPresetControlModel` returned a
correlationId.

### Preset 1 "Default shower" is special — but **not** protected

It is the device's mandatory default-shower configuration and is **hidden from the app's
preset list**. The app's shower button does **not** activate it — it builds a
`solowritesystem` from the live `gcs-state` setpoints plus the selected outlet. Preset 1
*seeds* what that button actuates; it is not itself activated.

That made it reasonable to suspect preset 1 was protected. **It is not.** Both `writepreset`
and `controlpresetorexperience` work on it exactly like any other preset, verified live.

The precaution was still worth taking: preset 2 was written **first**, because
`writepreset` has three documented ways to return success and change nothing (below). Had
preset 1 alone failed, "protected" and "malformed request" would have been
indistinguishable.

### Preset ids are **fixed slots**, not list positions

There are always **ten** preset slots. A device reboot enumerates all of them, empty ones
included:

```text
2026-08-11T18:51:43  id=1   'Default shower'  v1=018448 v2=05849c
2026-08-11T18:51:45  id=2   ''                v1=000000 v2=000000
…
2026-08-11T18:51:49  id=10  ''                v1=000000 v2=000000
```

So **creating a preset fills the lowest free slot and renumbers nothing.** Captured live at
the moment of creation — a preset added from the app took **id 3**, with ids 1 and 2 keeping
both their ids and their contents:

```text
2026-08-12T06:49:51  id=3  'Flush out'  v1=1d86c8 v2=0d86c8
```

Confirmed independently by the REST read afterwards.

> **Why a new preset can *look* like id 2.** Two reasons, and both are real. The app **hides
> preset 1**, so an id-3 preset appears *second* in its list. And a **freed slot is reused**
> — if slot 2 had been emptied earlier, the next preset created genuinely does become id 2.
> App position is not `presetId`.

#### Deleting empties the slot — it does **not** renumber

**Confirmed live 2026-08-12** by creating, deleting, and re-creating while watching the push
messages:

```text
21:22:20  id=4  'Twotwentyone'      created  -> lowest free slot
21:22:59  id=5  'Twotwentythree'    created  -> next free slot
21:26:48  id=4  ''  V1=000000 V2=000000      DELETED -> slot emptied in place
21:27:21  id=4  'Twotwentyseven'    created  -> reused the freed slot 4
```

Two things settled:

- **A deletion is pushed as an empty-slot message** — same `presetId`, `name: ""`, and
  all-zero valve words. There is no separate delete event to watch for.
- **Ids of other presets do not move.** `Twotwentythree` stayed id 5 across the deletion of
  id 4.

This is the **opposite of HUB favourites**, where deleting genuinely does shift the others
([`../architecture.md`](../architecture.md#favourite-ids-are-reassigned-not-stable)). Do not
carry that intuition across: GCS presets are slots, HUB favourites are a list.

A cached id is therefore safe against *other* presets changing, but not against **its own**
slot being deleted and refilled — the id stays valid while pointing at a different scene.
Resolving by **name** is still the robust choice.

### When the preset list is pushed

`GCS_PRESET_STS` arrives over MQTT — **there is no polling to do**. Two triggers, both
observed:

| Trigger | What arrives |
|---|---|
| A preset is **created or edited** (app, or your own `writepreset`) | one message, **only the changed preset** |
| **Device reboot** (`DEVICE_REBOOT_STS`) | all ten slots, one message each, ~6 s |

The message carries the whole record, so nothing needs re-reading:

```json
{"code": "GCS_PRESET_STS", "presetId": "2", "name": "Test favourite",
 "time": "3600", "volume": "0", "Valve1": "017cc8", "Valve2": "057cc8", …}
```

Note `Valve1`…`Valve8` are **capitalised** here, where `writepreset` sends them lowercase.
Slots 3-8 carry stale junk (`0000c0`, `080020`, `18ec00`) on this system — read only as many
valves as the model has.

The practical consequence: a client that subscribes can track preset edits **live, with no
reload and no poll**. One that ignores these messages and caches an id will silently activate
the wrong scene after a delete.

### Flow: the valve obeys, the *touchscreen* is what computes limits

**Resolved 2026-08-13, decompile plus live test.** Byte 2 is
`round(setpoint₀₋₅₀ × 4)` = `round(percent₀₋₁₀₀ × 2)`, encoded against the per-outlet
`[minimumFlowRate, maximumFlowRate]` = `[16, 200]` here.

**A direct `solowritesystem` flow byte is honoured exactly.** Verified against hardware —
three values, one to three outlets open in a zone, every echo matching the command:

```text
write f=74  (37%)  outlets 100  -> echo 11844a04   held
write f=74  (37%)  outlets 101  -> echo 11844a05   held, 2 outlets
write f=74  (37%)  outlets 111  -> echo 11844a07   held, 3 outlets
write f=100 (50%)  outlets 111  -> echo 11846407   held
```

The other zone was never disturbed: zone 1 stayed at 200 throughout. **No clamping, no
recomputation, no linking.**

#### Then what produced the varying ceilings?

Captures show the same outlet set topping out at 200 in one session and 69 in another, and
the byte moving on its own when outlets change (`31 ↔ 58 ↔ 165`). **None of that is the
valve, and none of it is the app.**

There are three actors, not two:

| Actor | Flow control | Behaviour |
|---|---|---|
| **Konnect app** | **removed** | pins app-created favourites to 100 % |
| **Anthem Plus touchscreen** | present | linked zones, varying ceiling, recomputes on outlet change |
| **Valve firmware** | executes | honours whatever word it receives |

Every "messy" capture was driven from the **touchscreen**, which nobody has decompiled. It
computes the linked-zone scaling (`byte = 16 + p × (ceiling − 16)`, ratio held across both
zones) and whatever ceiling it is applying, then sends a finished word. The valve just obeys.

The app decompile correctly contains none of this — `zone1FlowRateMax` / `zone2FlowRateMax`
are assigned in exactly one place (`Li\o.java m4()`) from a static
`outletConfigurations[0].getMaximumFlowrate()` = 200, with nothing that sums flow across
outlets, consults a system budget, or scales by temperature. The app's slider *thumb* is
re-read from the echoed `flowSetpoint` on every `GCS_SOLO_STS` (observer `f4()` → `m4()`),
which is why it appears to top out at 34 % — it is mirroring a value the touchscreen chose.

#### ✅ RESOLVED 2026-08-14 — the ceiling is the zone's plumbing, as a fraction of ~13 gpm

**A zone's flow ceiling is proportional to its water-line calibration.** The byte is a
fraction of a system-wide maximum, not of each zone's own capacity — and that one fact
explains every "unpredictable ceiling" observation in this document.

> **Read the scale caveat below before quoting a gpm figure.** What the captures *determine*
> is the proportionality. The absolute value of byte 200 rests on one further assumption, and
> Kohler's published rating for this valve does not match the obvious reading.

Setup forces a **water-line calibration**, measuring each outlet's actual delivery. These are
the **Anthem Plus (HUB) figures** on the reference install:

| | outlet 1 | outlet 2 | outlet 3 | zone total |
|---|---|---|---|---|
| zone 1 | 2.11 gpm | 1.39 gpm | 1.06 gpm | **4.56 gpm** |
| zone 2 | 1.65 gpm | 1.78 gpm | **7.00 gpm** | **10.43 gpm** |

> **The GCS valve holds its own, separate calibration, and it has not been read.** Using HUB
> numbers here is deliberate and consistent: the ceiling is computed by the **touchscreen**,
> which *is* the Anthem Plus panel, and
> [`../architecture.md`](../architecture.md#outlet-types-mean-different-things-on-the-two-devices)
> already records that the HUB derives flow limits from `outlet type x flow calibration` and
> "sets the flow envelope", while the valve uses calibration alone with no type. So a
> HUB-computed ceiling explained by HUB calibration is the right pairing.
>
> It does mean the valve's own figures are an untested cross-check. If they differ materially
> from the HUB's, this derivation needs redoing against them.

Divide each zone's total by the observed ceiling and both give the same answer:

```text
zone 1    4.56 gpm / 0.355  =  12.85 gpm
zone 2   10.43 gpm / 0.790  =  13.20 gpm
```

Across all three ceiling pairs ever captured — six independent figures — the mean is
**12.99 gpm**, range 12.64–13.37, stdev 0.31. Least-squares fit: **M = 13.03 gpm**.

```text
gpm = (byte / 200) x 13.03

byte  16    8.0%    1.04 gpm    the floor — identical for both zones
byte  71   35.5%    4.63 gpm    zone 1 flat out
byte 158   79.0%   10.30 gpm    zone 2 flat out
byte 200  100.0%   13.03 gpm    unreachable by either zone alone
```

So zone 1's ceiling is 35% because `4.56 / 13.03 = 35%`, and zone 2's is 79% because
`10.43 / 13.03 = 80%`. **Zone 2 sits so much higher only because its outlet 3 calibrates at
7.00 gpm** — a tub filler — which is most of that zone's capacity on its own.

##### Independent cross-check

Against the `#43-49` sweep recorded above, which played no part in deriving the model:

| | |
|---|---|
| minimum flow (byte 16) | **1.04 gpm**, identical both zones — matches "both hit 16 together" |
| zone 1 span above minimum | 3.45 gpm |
| zone 2 span above minimum | 9.71 gpm |
| predicted span ratio | **2.81** |
| measured sweep ratio | **2.81** ✓ |

Note the raw capacity ratio is 10.43/4.56 = **2.29**, *not* 2.81. The 16-byte floor accounts
for the difference, and the model reproduces it.

##### What this explains

* **Why the ceilings differ per zone** — different plumbing, one shared denominator.
* **Why zone 1 can never reach 100%** — it physically cannot pass 13 gpm. The app slider
  "topping out at 34%" was mirroring a real hydraulic limit, not a UI defect.
* **What linked zones actually guards.** Both zones at byte 200 would be `13.03 x 2 = 26.06`
  gpm against the 22.0 gpm combined rating — **118%**. So the *top of the range* has to be
  scaled when both zones run.

  > **Correction, 2026-08-14.** An earlier revision of this section said linked zones exists
  > because "both zones flat out is 14.99 gpm against a 13.03 rating — 115%". That compared a
  > **combined** capacity against a **per-zone** limit, which is not a valid comparison. Both
  > zones at their calibrated capacities is 14.99 gpm against the **22.0 gpm combined**
  > rating — **68%**, comfortably inside. The ceilings alone do not force any scaling; only
  > the unreachable top of the byte range does.
* **Why `getMaximumFlowrate()` = 200 is not the ceiling.** 200 is the absolute byte cap; the
  effective ceiling is a hydraulic fact the app never sees, because the calculation lives in
  the touchscreen and the inputs are calibration figures.

##### What is still not exact

The best fit predicts 35.0% / 80.0%; the three observed pairs are 35.5/79.0, 34.5/82.5 and
36.0/78.0 — **±1.5 percentage points** around a fixed ratio. The residual is consistent with
the touchscreen recomputing and rounding per session.

**So the ceiling is not random. It is a fixed hydraulic ratio with recalculation noise on
top.** The earlier "same outlet set topped out at 200 in one session and 69 in another" is
the difference between *no ceiling applied yet* (200, the raw cap) and *the ceiling applied*
(69) — not two different ceilings.

##### The scale: byte 200 is the **per-zone** maximum, ~13 gpm

Kohler publishes two figures for the K-28212 and, tellingly, not the third:

| | rating |
|---|---|
| per outlet | 9.5 gpm |
| **per zone** | **not published** |
| zone 1 + zone 2 combined | 22.0 gpm |

**The flow byte is per zone** — each zone's word carries its own — so its scale has to be a
per-zone maximum. That is exactly the slot Kohler leaves empty, and 13.03 gpm fills it:

```text
per outlet    9.50 gpm    published
PER ZONE     13.03 gpm    unpublished  <- what byte 200 represents
combined     22.00 gpm    published
```

Sanity check in both directions:

* `13.03 x 2 = 26.06 gpm` exceeds the 22.0 combined rating, so **both zones cannot reach
  byte 200 together.** That is what the touchscreen's linked scaling guards against.
* Both zones at their *ceilings* is 14.99 gpm — **68% of the combined rating**, comfortably
  inside. Normal use never approaches the limit.

This also **eliminates the rival reading.** "Byte 200 = 22.0 gpm" would put both zones at
44.0 gpm — double the combined rating — which is incoherent for a per-zone field. Only a
per-zone figure works, and the data fixes it at ~13.

> **Still fitted, not transmitted.** No message carries 13.03; it is derived from this
> install's calibration and its observed ceilings. The clean fit into the unpublished
> per-zone slot is corroboration, not proof.
>
> Remaining caveats:
> 1. The calibration figures are **HUB-side**, one reading per outlet, one install. The GCS
>    valve's own calibration has never been read.
>    **⚠️ And the numbers used may be the wrong set.** The owner has confirmed (2026-08-14)
>    that when flow is driven from the **first-gen touchscreen**, it is the **valve** that
>    applies the ceiling, using **its own** calibration — the screen is only a peripheral
>    relaying touches. The fit above used **HUB** figures. It works, which implies the two
>    calibrations are close (both measure the same pipes), but **the derivation should be
>    redone against the valve's own calibration** once those numbers are read off the
>    first-gen screen. If they differ materially, the fit is coincidence.
> 3. The model assumes a zone's ceiling equals its full calibrated total. Natural, but not
>    independently confirmed.
> 4. A second install with different calibration would test it properly — and if 13.03 is a
>    product figure rather than plumbing, it should reappear there.

#### The touchscreen hijacks both zones the moment it is touched

This is the finding that makes flow impractical to expose, and it is worth stating precisely.

**Merely opening the touchscreen's flow control rewrites the valve**, before any adjustment
is made. Captured live while Home Assistant held zone 2 at a deliberate 100 % and zone 1
untouched at 200 — **times below are UTC; locally this is 2026-08-12 at 19:00**, inside the
owner's worst hour of flow thrashing (34 distinct flow values that hour, full 8–100 % sweeps):

```text
#7   01:59:49Z   Z2 f=200  out=111      our state, stable        (local 08-12 18:59:49)
#8   02:00:07Z   Z1 f=200 -> 69         <- flow control opened   (local 08-12 19:00:07)
#9   02:00:07Z   Z2 f=200 -> 165        0.2 s later
```

Note what appears the instant the panel is touched: **69 and 165** — byte-for-byte the
calibration-derived ceilings established above (34.5 % and 82.5 %). The panel is not choosing
arbitrary numbers; it is applying the hydraulic limit.

Nobody dragged anything. Opening the panel re-seeded **both** zones to values of its own
choosing, and everything after that scaled from the new pair.

Three properties make this impossible to model or defend against:

* **It rewrites zones you never touched.** Zone 1 had no outlet open and no involvement; it
  was rewritten anyway.
* **The re-seed values depend on prior state**, so they are not a fixed signature. Had HA set
  zone 2 to 50 % first, the panel would have re-seeded to different numbers.
* **The ceiling it applies is not exposed by any field**, though it is no longer a mystery —
  it is the zone's calibrated capacity over a ~13 gpm system maximum, derived above. The
  "200 in one session, 69 in another" pair is *ceiling not yet applied* versus *applied*.
  What remains unpredictable in practice is **when** the panel decides to apply or recompute
  it, which is enough to make a Home Assistant setpoint unreliable.

Afterwards it holds both zones in a fixed ratio above the floor of 16 — the sweep at
`#10-#26` keeps `span₂/span₁ ≈ 2.8` across every step — so a per-zone setpoint written by
anyone else simply cannot survive contact with it.

#### Consequences for a third-party client

* **Write what you want; the valve keeps it.** Per-zone, at any outlet count.
* **You are not subject to the touchscreen's linking** — until somebody touches the panel,
  at which point both zones are overwritten regardless of what you set.
* **Treat the echo as truth**, always.

> **Not proven:** that the valve *never* clamps. We did not reproduce the state in which a 69
> ceiling appeared, so the honest claim is "every write we made was honoured", not "no write
> can be reduced".

#### Why the Home Assistant integration exposes no flow control

Given the above, flow entities were **removed** from the integration on 2026-08-13:
`number.*_flow_zone_1`, `number.*_flow_zone_2`, and `binary_sensor.*_at_flow`.

The reasoning is not that flow cannot be written — it demonstrably can, exactly and per zone.
It is that a setpoint the wall panel silently overwrites, to values that depend on hidden
state, is worse than no control at all: the user sets 37 %, someone opens the panel, and the
number changes on its own with no explanation. `atFlow` went with it, having never once been
observed set in any capture.

**The protocol layer is untouched** — `valve_hex.py` still encodes and decodes byte 2 in
full, `GcsState` still exposes flow and the per-outlet limits, and `async_apply_valve()`
still accepts `zone1_flow` / `zone2_flow`. Re-adding the entities is a UI change only, and
would become worthwhile if Kohler fixes the 2.88 flow calculation or if the touchscreen's
ceiling rule is ever recovered from its firmware.

Context: this system has flow control disabled system-wide (the **2.88** workaround) and the
Konnect app has removed flow control altogether — every app-created favourite stores flow
`50` (100 %), while the factory "Default shower" still holds real per-zone values (18 / 39).

#### …and why every Home Assistant write now forces 100 %

Removing the entities was only half the fix, and the other half was missed until 2026-08-13
(session 5). `async_apply_valve()` still resolved an unspecified flow as *the value already in
the valve* — so with no flow UI left to specify one, **every** command Home Assistant sent
carried whatever the touchscreen had last written.

Measured over **1,346 captured valve words**: 927 at 100 % (`0xC8`), and **419 — 31 % — below
it**, the lowest `0x10` = **8 %**. About a third of the time, opening an outlet from Home
Assistant produced a reduced flow, with nothing in the UI to explain or correct it.

So flow is now the **one field that does not carry forward**: omitting it writes
`DEFAULT_FLOW_PERCENT` (100 %), while every other field is still preserved. The reasoning is
the same as for removing the entities — with no way to express a flow, no caller can *mean*
one, and inheriting merely relays the panel's intent under Home Assistant's name.

Explicit `zone1_flow` / `zone2_flow` still work and are still honoured exactly. The side
effect to remember is that a temperature change from Home Assistant mid-shower now also
restores full flow.

### Preset flow is real, despite the UI

The create-preset **UI** hardcodes flow to 50 (max), so app-made presets show 100%. The data
model and controller support per-valve variable flow — proven by the factory "Default
shower", which stored flow 18 / 39. Via `createpreset` / `writepreset` any flow byte can be
set.

**The device does honour a stored flow on activation** — confirmed by the live run above,
where the valve came up at the preset's flow 50 (`0xC8`, 100%) rather than a default.

## 3. Warmup is a **setting/mode toggle**, NOT a "run now" command

*Re-confirmed 2026-08-20 against Konnect Android 3.0.1, with the enable path exercised live.*

`POST /platform/api/v1/commands/gcs/warmup`
Body `AnthemWriteWarmUpRequestModel` = `{deviceId, sku:"GCS", tenantId, warmUp:"<mode>"}`.

**Exactly four fields exist.** No duration, no delay, no outlet list, no temperature — the
request model has four `@SerializedName` fields and nothing else. Path is templated in the APK
as `/platform/api/{version}/commands/gcs/warmup`; the app substitutes `v1`.

`warmUp` mode values (from the decompile — `Si\y.java`, `p218gj\q.java`):

| `warmUp` value | Meaning | Current app offers it? | Status |
|---|---|---|---|
| `warmUpDisabled` | Off | **yes** | decompile |
| `warmUpAllOutletsWithNoStartDelay` | Enable — all outlets, start immediately | **yes** | ✅ **live 2026-08-20** |
| `warmUpSelectedOutletsWithNoStartDelay` | Enable — selected outlets only, start immediately | **yes** | ✅ **held by this valve right now** — live GET, 2026-08-20 |
| `warmUpAllOutlets` | Enable — all outlets. ✅ **Written and exercised live 2026-08-21**: accepted by current firmware (200 + echo), and the warm-up runs **`0x8` (8) tenths = 0.8 °C ≈ 1.4 °F below setpoint** — `0x17C` (380) = 100.4 °F against a `0x184` (388) = 101.8 °F default — then restores setpoint when the pause ends. Pause behaviour is **identical** to `…WithNoStartDelay` (2 min at `0x40`/`0x40`, then `00`/`00`). The reduced target is the only measured difference; `delayStart` read `"Disabled"` on both panels throughout | no — legacy | ✅ **live 2026-08-21** |
| `warmUpSelectedOutlets` | Enable — selected outlets only, presumed to mirror the above | no — legacy | ⚠️ unverified |

> ⚠️ **The 2026-08-20 decompile undercounts this — and it was NOT an older build.** Corrected
> 2026-08-21: the decompiled APK was 3.0.1, the same build currently shipping (no newer arm64
> exists — owner-verified), so the undercount was an **analysis gap in that dig, not a build
> difference** — treat that dig's negative findings ("never branched on", "not a warmup
> field") as unproven, not as facts about the app. It reported only
> two modes as app-writable and filed `warmUpSelectedOutletsWithNoStartDelay` as unverified.
> **The current Konnect app offers three** — off, all outlets, selected outlets, all with no
> start delay — established by the owner against the app in their hands, 2026-08-20. Our own
> captures agree: this valve *held* `warmUpSelectedOutletsWithNoStartDelay` three separate
> times on 2026-08-13 with no other client in play, which no two-value app could have produced.
>
> **Write three, decode five.** The two delayed-start variants stay decodable because a valve
> could be holding one, but nothing establishes what their delay is — the app has no control
> that sets one, and "delay" appears nowhere in its 3,278 string resources.
>
> ✅ **Settled deliberately, 2026-08-20.** The owner set each mode from the current Konnect
> app to confirm the names, and `gcs-state` read back
> `warmUpSelectedOutletsWithNoStartDelay` — the value the decompile called unverified and
> never-sent. It is in the app, and it is writable.
>
> ✅ **And the write path is proven from this integration.** `GcsDevice.async_set_warmup()`
> posted `warmUpAllOutletsWithNoStartDelay` to a live valve on 2026-08-20; the cloud returned
> a `correlationId`, the field changed, and the valve pushed the matching `GCS_WARM_STS`. See
> `tests/probe_warmup_write.py`.
>
> ⚠️ **`warmUpEnabled` does not exist.** It appears in some older Python projects. It is not in
> the APK. Do not send it. `tests/test_warmup_select.py` fails if that string — or either of
> the removed `set_warmup` service constants — reappears in this integration's source.

State is separate, on two axes (`AnthemWarmupStateModel`):

- `warmUpState.warmUp` = the mode above (which mode / disabled)
- `warmUpState.state` = `warmUpInProgress` / `warmUpNotInProgress` (running now?)
- also: MQTT `MqttAnthemSoloStatus.warmUpStatus`; settings `AnthemSettingsModel.warmUpMode`

**Consequences:**

- **No separate "run warmup"** — the command *is* the enable/disable + mode toggle.
- **Independently settable** via `/commands/gcs/warmup`, but the app **blocks the toggle
  while the system is active** (`q.V(boolean)` → `V0(state)` guard reverts it), so set it
  when idle.
- **Runs automatically** once enabled, per the chosen mode; `state` tells you when it is in
  progress.
- When warmup is *disabled on the fixture*, Kohler's cloud still returns HTTP 200 for a
  warmup command but the device silently ignores it. The HA integration reads
  `warmUpState.warmUp` to surface this rather than appearing to no-op.

### 3a. ⚠️ Four ways this call fails while returning success

Established by decompile 2026-08-20. Every one of these gets a success code back, so **a 200
means accepted, never applied** — the only confirmation is the valve's own `GCS_WARM_STS` echo.

| # | The trap | What we do about it |
|---|---|---|
| 1 | **Omitting `warmUp` gives a 200 that does nothing.** The most common bug in existing implementations, because published curl examples show the three-field body — `kohler-anthem` has it. | `GcsDevice.async_set_warmup()` raises `ValueError` on an empty or blank mode, so a caller that cannot name one never reaches the API. |
| 2 | **`presetOrExperienceId: "0"` does not stop warmup.** Posting id `0` to `controlpresetorexperience` clears a running preset and leaves the mode enabled — a different field on a different endpoint. `kohler-anthem`'s `stop_warmup` does this. | `async_disable_warmup()` writes `warmUp: "warmUpDisabled"`. A test asserts nothing warmup-related ever posts to `controlpresetorexperience`. |
| 3 | **The mode is not "warming up right now".** `warmUpState.warmUp` is the mode; `warmUpState.state` is `warmUpInProgress` / `warmUpNotInProgress`. A control bound to the wrong axis reads off almost always, since a warm-up is over in seconds. | The `Warmup` dropdown *is* the mode, with `Off` as one of its choices. In-progress stays on the Status sensor, and both appear as attributes on the dropdown. |
| 4 | **The app refuses the toggle while water is running** — it checks whether any outlet on either valve is on and reverts its own toggle rather than calling the API. Whether the *device* enforces this is untested; the guard is client-side. | `KohlerAnthemPlusCoordinator.async_set_warmup()` raises if `is_running`, saying so rather than reverting silently. |

### 3b. Reading it back

`GET /devices/api/v1/device-management/gcs-state/gcsadvancestate/{deviceId}` — captured live
2026-08-20 from a valve with warmup on:

```json
{"state": {
  "warmUpState": {"warmUp": "warmUpAllOutletsWithNoStartDelay",
                  "state": "warmUpNotInProgress"},
  "currentSystemState": "normalOperation",
  "presetOrExperienceId": "0"}}
```

✅ **Read live 2026-08-20**, both `gcs-state/{deviceId}` and
`gcs-state/gcsadvancestate/{deviceId}` returning byte-identical `warmUpState`:

```json
{"warmUp": "warmUpSelectedOutletsWithNoStartDelay", "state": "warmUpNotInProgress"}
```

**The plain `gcs-state` read is enough** — it carries the same `warmUpState` as
`gcsadvancestate`, and it is the read this integration already makes at setup, on every MQTT
reconnect, and after every warmup write. No second endpoint is needed for this field.

Two fields not to use: **`setting.warmUpMode` returns `null`** — confirmed live 2026-08-20; the
field exists on the model, nothing populates it, and the app never reads it — and
`setting.uiConfig[].delayStart` is a control-panel setting, not a warmup field.

### The settle window — measured 2026-08-20

**A write is not visible to the next read.** Timed against this valve:

```text
08:01:34.815  POST .../commands/gcs/warmup   accepted, correlationId returned
08:01:34      GET gcs-state  -> still warmUpSelectedOutletsWithNoStartDelay   ← the OLD mode
08:01:38.2    GCS_WARM_STS   -> warmUpAllOutletsWithNoStartDelay   (+3.42 s, MQTT)
08:01:3x      GET gcs-state  -> warmUpAllOutletsWithNoStartDelay   (by t+3 s)
```

So **an immediate read-back reports a false mismatch every time.** Anything confirming a write
has to allow a few seconds first — `WARMUP_READBACK_DELAYS` in `const.py` spans 6 s over three
attempts, and only the last disagreement is treated as a failure.

**Both channels are reliable and they agree.** Two mode changes on 2026-08-20 — one from the
Konnect app at 07:47:12, one from this integration's own POST at 08:01:34 — each produced a
`GCS_WARM_STS` push *and* an updated REST field. ⚠️ *An earlier draft of this section claimed
the app's change was never pushed over MQTT. That was wrong: it compared a fresh REST read
against a capture analysed before the change landed.*

Over MQTT the same mode arrives as `GCS_WARM_STS.warmup`, spelled **all lowercase**, where REST
spells it `warmUp`. `GcsState` matches both.

### 3c. In Home Assistant

**`select.anthem_valve_warmup`** — a CONFIG-category dropdown on the valve device. Its state
*is* the mode, shown under the app's own names:

| dropdown | writes |
|---|---|
| `Off` | `warmUpDisabled` |
| `All outlets` | `warmUpAllOutletsWithNoStartDelay` |
| `Selected outlets` | `warmUpSelectedOutletsWithNoStartDelay` |

Attributes carry `warmup_mode` (the raw string) and `warmup_in_progress` (the other axis).

**A valve holding a legacy delayed-start mode is shown, not hidden**: that mode is appended to
the options for as long as it is in force, because Home Assistant logs an error on every update
when the current option is missing from the list. It is refused as a write target and drops off
the list once the mode moves on.

⚠️ Which outlets count as "selected" is **not** exposed by any cloud API — it is per-zone
`warmupOutlets` on the controller's local API. So the dropdown picks the mode; the selection
itself is configured on the device.

*Superseded 2026-08-20: this was briefly `switch.anthem_valve_warmup`, and before that the
read-only `binary_sensor.anthem_valve_warmup_enabled`. Both are gone — a two-state control
cannot express three modes, and the binary sensor duplicated what the dropdown now shows.*

### 3f. `switch.anthem_valve_warmup_auto_restore` — putting the mode back

A **diagnostic switch, off by default**, that answers the hub's warmup-disable writes (once
§3e's open question, solved in §3h) by undoing
them. When the valve announces `warmUpDisabled` over MQTT and this integration did not cause
it, the mode is set back **60 s later** to the last enabled mode seen on the valve.

| | |
|---|---|
| **Restores to** | the last enabled mode observed — never a default. Remembered from both the MQTT announcement and our own confirmed writes, and persisted in the entry options so it survives a restart. With no remembered mode it does nothing and logs why. |
| **Ignores our own `Off`** | choosing `Off` on the dropdown is a write we made; the echo that follows it is recognised for 30 s and not undone. Otherwise `Off` could never be selected. Scoped to the *mode written*: a write that enabled warmup does not excuse a disable arriving after it. |
| **Ignores restatements** | the valve re-announces its mode ~4 s after every boot, and it rebooted 25 times in a week here. Only a transition out of a *known enabled* mode counts, so the first mode seen after a restart is never treated as something being taken away. |
| **Stops fighting** | five consecutive restores that fail to stick and it gives up with a WARNING. A retry loop against something actively rewriting the field is traffic, not a fix. Seeing the mode enabled again resets the count. |
| **Never during a shower** | the write is refused while water is running, mirroring the app. The next disable schedules another attempt. |

The decision — *is this a disable we should undo?* — is
[`anthem_plus/warmup.py`](../../anthem_plus/warmup.py)'s `should_restore_warmup()`, kept out of
the Home Assistant layer so `tests/test_warmup_auto_restore.py` can test the real function
rather than a copy of it.

⚠️ **It treats a symptom.** It does not identify what rewrites the field, and left to itself
it would make the fault *less* visible by papering over it. §3g is the answer to that.

### 3g. The warmup journal — the evidence that settled §3e

*(Built to hunt §3e's unexplained disables; on 2026-08-21 it caught four of them live and the
question closed — §3h. It stays on as the watchdog that proves each restore and would catch
the hub's behaviour changing.)*

`/config/kohler_anthem_plus_raw/warmup_*.jsonl`, beside the raw MQTT capture and the cutoff
journal, on the same UTC clock so all three interleave. **On by default** and independent of
the auto-restore switch: the event fires a few times a week, so a log that had to be switched
on first would miss it, and an *unrestored* disable is the cleaner observation of the two.
`README-warmup.txt` is written alongside and carries the analysis notes.

| record | when | what it carries |
|---|---|---|
| `baseline` | first line of every file | `mode` as read over REST at setup, plus `auto_restore` and `restores_to` — what the file started from |
| `mode` | the mode moved | `before`, `after`, `ours`, and `source`: `mqtt` if the valve announced it, `rest` if a reseed found it already changed |
| `announced` | the valve restated a mode it was already in | `mode`, `ours`. ⚠️ **A dropdown change lands here, not on `mode`** — the write reads itself back over REST at once, so our state has moved before the valve's ~3.4 s echo. `ours: true` is how you tell those from the valve volunteering |
| `disabled` | the mode went to `warmUpDisabled` | `ours`, `restoring`, `water_running`, and **`before_window`**: every MQTT message in the preceding 120 s |
| `context` | 60 s after a disable | **`after_window`** — what followed |
| `restore`, `restore_done`, `restore_skipped`, `restore_failed`, `restore_gave_up` | auto-restore acting | target, attempt number, and the reason for every decline |

⚠️ **`baseline` and `announced` were added 2026-08-21, and the journals before that date are
thinner than this table implies.** Until then only *transitions* were recorded: the `mode` row
above used to read "every warmup announcement", and that was never true. Two consequences for
anything already captured — **a file with no records means "no transitions", not "nothing
happened"**, and the valve's restatements are missing entirely, including the ~4 s post-boot
`GCS_WARM_STS`. **28 of the 43 announcements in the raw corpus are restatements**, so on the
pre-08-21 journals the raw capture is the only complete record of them.

⚠️ **A `mode` record with `source: rest` is not restored.** It means the mode moved while the
MQTT stream was down and the reseed found it already changed, so there is no `before_window`
behind it and auto-restore is deliberately not wired to it. Before 2026-08-21 this case was
not recorded at all — it is the one way a disable can happen and leave no trace in the journal.

**Why both windows.** The four known disables sit inside a burst of configuration re-sync
traffic, but the most distinctive marker — `SYSTEM_STS: SYSTEM_READY` — landed **7 to 9 s
after** the disable in the two clearest cases, along with `configChangeIndent` stepping on
`GCS_SOLO_STS`. A record written at the moment of the event cannot contain its own strongest
evidence, so the after-window is a separate record written a minute later.

Each windowed message keeps only `ts`, `sku`, `code`, and for `GCS_SOLO_STS` the four fields
that distinguish a configuration write from an ordinary status — `configChangeIndent`,
`configWriteAllowedFlag`, `currentSystemState`, `warmUpStatus`. The raw capture beside it holds
every payload in full; duplicating that here would bury the one thing this file is for.

#### What a *known-cause* warmup change looks like on the wire — 2026-08-21

The method below asks what an unexplained change has that a quiet hour does not. That comparison
needs the third case too: a change whose cause is known. Two clean samples, both the owner
setting the mode from the Home Assistant dropdown:

| | change 1 | change 2 |
|---|---|---|
| `GCS_WARM_STS` carrying the new mode | 07:52:44.970Z | 07:53:12.710Z |
| `READ_GCS_EXPERIENCE_STS` | 07:52:49.679Z (**+4.71 s**) | 07:53:17.468Z (**+4.76 s**) |

So a deliberate write produces **a small, consistent two-message burst**: the echo, then an
experience catalogue about 4.7 s behind it. Nothing else on either channel.

Worth having for three reasons. It is a re-sync burst with a known cause, so "sat inside a burst
of config traffic" is **not on its own evidence of an external writer**. It is *small* — two
messages — where the unexplained disables sit in something larger, so burst size may discriminate.
And `READ_GCS_EXPERIENCE_STS` following a warmup write at a fixed offset is a signature to
subtract before reading any window.

⚠️ Both were journalled as **`announced`, not `mode`** — the REST readback moves our state before
the echo lands (§3g). Both carry `ours: true`, which is the only thing separating them from the
valve volunteering; check that field before treating an `announced` as unexplained.

**The method:** collect several `disabled` records, then look for what their windows share and
a quiet hour does not. ⚠️ Absence of a message means "nothing was pushed", never "nothing
happened" — MQTT here is the Konnect app's UI channel, not device-to-device traffic.

#### Does auto-restore spoil the evidence?

**For one disable, no.** Both windows close before a restore could fire — the forward window is
45 s against a 60 s restore delay, and `test_warmup_journal.py` fails if that ordering is ever
reversed. It was not always so: both were 60 s when first written, which put the close of the
evidence window at the same instant as the write, leaving it to coroutine scheduling whether
our own traffic landed inside the evidence.

**For a repeat, yes, mildly.** A restore is a write — a POST plus the valve's echo ~3.4 s later
— so if the mode is disabled again within a couple of minutes, our traffic sits inside that
second event's `before_window`. It is identifiable (`restore` records are timestamped and the
`mode` record after one carries `ours: true`), but it is noise in the middle of the evidence,
and a restore may itself provoke whatever is doing this.

**Widening the windows is not the answer.** The marker being hunted lands within 10 s; a longer
window collects noise, not signal. The trade is simply: **off** for the cleanest series,
**on** for a shower that warms up reliably while the question stays open.

✅ **What disables this setting is SOLVED — 2026-08-21: the Anthem Plus hub's web UI.** Any
signed-in UI action writes the valve's warmup mode from the hub's own (stale) copy. The full
evidence — a controlled live reproduction plus the fingerprint that matches every historical
disable — is in §3h. The old framing ("the writer is unidentified; leading candidate the
controller over the RJ wired link") was close: it is the controller, but firing on UI events,
not spontaneously.

### 3d. ⚠️ Library bug — `start_warmup` sends no mode

*This is §3a traps 1 and 2 as they appear in real code — kept because it is the specific
implementation most likely to be copied from.*

`kohler-anthem`'s `start_warmup` sends `{tenantId, deviceId, sku}` with **no `warmUp`
field** → the device ignores it (200 but no-op). `stop_warmup` sends
`controlpresetorexperience` id `0`, which is unrelated.

Fix: `start_warmup` → `warmUp:"warmUpAllOutletsWithNoStartDelay"`; disable →
`warmUp:"warmUpDisabled"`.

### 3e. Still open

| question | what is known | how to settle it |
|---|---|---|
| What *is* the "start delay"? | ⚠️ **Partially measured 2026-08-21 — and the obvious readings are wrong.** The proposed experiment was run (owner shower under `warmUpAllOutlets`): the 2-min `0x40`/`0x40` pause happens under **both** suffixes, so the suffix does not control the pause — which also kills the earlier hub-mapping lead ("Water Stays ON"/"Water Pauses" is the hub's own option, unrelated). The one measured difference: the delayed variant warms to **setpoint − `0x8` (8) tenths (0.8 °C)** — `0x17C` (380) vs `0x184` (388) — restoring setpoint at pause end. What "start delay" *names* is still unknown; `delayStart` read `"Disabled"` throughout, so a delay feature may simply have been off. Leading idea for the next dig: a remote-/scheduled-start flow (warm up before the user arrives), which would explain holding slightly under temperature. | APK dig (same 3.0.1 build — see §4 note) for the enum branches, the `0x8` offset, and `delayStart` semantics; or flip `delayStart` via `writeuiconfig` (**whole-record replace**). |
| Is `delayStart` the referent? | A real per-panel UI-config field, observed `"Disabled"`. In the APK it is only ever copied through — never branched on, never bound to a control. It is the only start-delay concept in the system. | Flip it via `writeuiconfig`, re-read `gcsadvancestate`, see whether the mode suffix changes. ⚠️ That write is a **whole-record replace**. |
| Which outlets are "selected"? | Not exposed by the cloud API. The per-outlet `warmup` flag exists only on the MQTT **read** model; the writable outlet-config model has no such field. The local hub has per-zone `warmupOutlets` arrays. | The local hub API — [`../hub/local_api.md`](../hub/local_api.md), not the cloud one. |
| ~~What keeps disabling it?~~ | ✅ **SOLVED 2026-08-21 — the hub's web UI. See §3h.** The experiment this row proposed was run by the owner: PIN sign-in alone disabled the mode within seconds, twice more for other UI actions, with the journal recording empty 120 s before-windows. | — |

### 3h. ✅ SOLVED 2026-08-21 — what disables warmup: the hub's web UI

**The writer behind the "unexplained" disables is the Anthem Plus controller, and the trigger
is ordinary, signed-in use of its web UI.** Established live on 2026-08-21 by the owner
driving the UI step by step while the journal (§3g) and the raw capture recorded — four
disables in one day, three of them inside a single web UI session with deliberately empty
120 s before-windows, so nothing else was in flight:

| local time (UTC−7) | UI action | mode disabled? |
|---|---|---|
| 07:39:40 | config edit, experiences removed (the hub first stopped the running shower — its stated UI behaviour, not part of the bug) | ✅ |
| 11:37:01 | **signing in with the PIN — nothing else** | ✅ |
| 11:43:58 | scanning the SD card for music | ✅ |
| 11:47:20 | changing a valve setting | ✅ |
| ~11:49:30 | logging out | ❌ — two *same-value* `warmUpAllOutletsWithNoStartDelay` announcements, no change |

The SD-card scan is the telling one: it has nothing to do with water, so the write is not
tied to valve-related actions. The hub runs one fixed routine on (seemingly) every UI action:

1. **write `warmUpDisabled` to the valve.** ⚠️ *Corrected later the same day:* an earlier
   version of this section said the value was "the hub's stale record of the valve settings".
   **It is not — no readable hub config holds it** (see the probe below). It behaves as a
   constant in the routine itself, hardcoded or defaulted — the §3d bug shape, in the hub's
   own firmware.
2. **+2.6–3.2 s:** publish its snapshots — `SHOWER_EXP_SNAPSHOT`, `STEAM_EXP_SNAPSHOT`,
   `ICE_SHOWER_EXP_SNAPSHOT`, `LUMIWAVE_EXP_SNAPSHOT`, `FAVORITES_SNAPSHOT`.
3. **+4.7–5.0 s:** read back the valve's experience slots (`READ_GCS_EXPERIENCE_STS`).

The write itself is invisible on our MQTT channel (wired RJ link or cloud-direct to the
valve); the first observable is the valve's `GCS_WARM_STS` echo, then the burst. The offsets
are constant to the tenth of a second across eight days — one program, not coincidence:

| disable (UTC) | snapshot burst after | experience read after |
|---|---|---|
| 08-13 21:13:39 | +2.7 s | +4.8 s |
| 08-20 20:36:28 (the 7 h disable) | +2.7 s | +4.8 s |
| 08-21 14:39:40 | +2.6 s | +4.7 s |
| 08-21 18:37:01 | +2.8 s | +5.0 s |
| 08-21 18:43:58 | +2.7 s | +4.9 s |
| 08-21 18:47:20 | +3.2 s | +4.9 s |

Every `warmUpDisabled` in the corpus either matches this signature or is a post-reboot
restatement from the 08-14/08-15 Moes-outlet storm (`DEVICE_REBOOT_STS` ~4 s before, the mode
not actually changing). The 08-19 06:34:31Z disable — 62 s after the mode had been enabled —
sits between two such bursts: "it always gets reverted" is this routine firing while a UI
session was open.

#### Probed with the PIN, same day: the value is in no readable hub config

Two local-API logins (19:20:30Z, 19:23:05Z — `request_user_login` alone triggers the routine,
so each probe was also the experiment) read **all 13 useful GET endpoints** while the push
landed. Results:

* `get_valve_settings.warmupmode` read **`"on"`** ("Water Stays ON") in the same seconds that
  both logins pushed `warmUpDisabled`. A field reading `on` cannot be the source of a
  `disabled` write. It has never tracked the valve either — on 08-18 it read `on` while the
  valve's mode had been disabled for four days.
* **No other endpoint carries any warmup field at all.** The literal string `warmUpDisabled`
  exists on *no* hub surface, local or cloud — hub MQTT carries only the live flags
  `showerwarmup`/`steamwarmup`, cloud `hub-state` only `showerWarmUp`. The enum lives solely
  on valve surfaces (`GCS_WARM_STS`, `gcs-state`, `gcsadvancestate`) — the *result* of the
  push, never its source.
* So `warmupmode` is the hub's **own** warmup setting (it and `warmupOutlets` predict the
  hub-run session warmup in case study 2 field by field), not a copy of the valve's mode —
  and the disable is not read from anywhere observable.

**Logout is client-side only.** The hub UI bundle's sign-out is
`logout(){localStorage.removeItem("currentUser")}` — no HTTP call exists (there is no logout
`req_command`). "Warmup survives logout" means *no trigger fires*, not that a correcting value
is pushed. The two same-value `warmUpAllOutletsWithNoStartDelay` announcements observed once
at 18:49Z on 08-21, ~1–2 min after a restore, did **not** recur after the probe cycles;
their trigger is unidentified and they changed nothing.

**Owner-supplied semantics for `warmupmode`** (2026-08-21): "Water Stays ON" / "Water
Pauses" / off describe what the hub does after *its* warm-up. ⚠️ An earlier version of this
paragraph proposed mapping these onto the valve enum's `…WithNoStartDelay` suffix — **that
mapping was tested the same day and is dead**: the valve's 2-min post-warm-up pause happens
under both suffixes (owner shower under `warmUpAllOutlets`, wire-verified), so the hub option
and the valve suffix are unrelated — one more instance of the two warmups being independent.
What the suffix *does* change is the warm-up target temperature — see §3's mode table and
§3e's start-delay row.

#### Why the hub can afford this bug: the two warmups are independent settings

The hub never *uses* the valve's warmup mode. It has its own, entirely separate warmup:

| | setting lives in | "active" flag on MQTT |
|---|---|---|
| **Hub warmup** | hub local config — `warmupmode: "on"`, per-zone `warmupOutlets` ([`../hub/local_api.md`](../hub/local_api.md)) | `SHOWER_VALVE_STS.showerwarmup = "1"` (a sibling `steamwarmup` exists and has never been seen set) |
| **Valve warmup** | the valve's own mode — `GCS_WARM_STS` / REST `warmUpState.warmUp` | `GCS_SOLO_STS.warmUpStatus = warmUpInProgress` |

A hub-started session warms up under the *hub's* setting, driving the valves itself — during
which the valve reports `warmUpStatus: warmUpNotInProgress` even with the valve mode enabled
(measured 2026-08-21 14:36Z). The valve's mode only governs valve-started water. Across the
corpus, 19 hub warm-up runs produced zero mode changes within ±10 minutes — starting hub
warmup does **not** write the valve's mode; only UI sessions do. So the field this routine
tramples is one no Kohler flow ever reads back: on the owner's own hardware the hub's warmup
stays permanently on while the valve's kept "mysteriously" turning off. Flag-level
independence was already measured in §1's "Warm-up: two independent systems"; this is the
settings-level counterpart, and the disable bug is where the two worlds touch.

**Also ruled out by the same data:** reboots (the mode survives them), Home Assistant (the
journal's `ours` flags), any MQTT-visible command (empty before-windows), and hub-warmup
starts (19 clean trials).

**Consequence:** with auto-restore (§3f) ON, every hub web UI session knocks the valve's
warmup off and the integration puts it back — six for six on 2026-08-21 (four owner-driven,
two probe logins), 63–69 s each, end to end. Without it, one PIN entry silently costs the setting until someone notices: that is
exactly what the 08-20 seven-hour disable was.

## 4. Where to look in the decompile

GCS is product package `anthem`, **not** `anthemhub`.

- **Endpoints:** `com\utils\network\retrofit\proxy\ApiConstant.java` (grep `gcs`, `ANTHEM_`).
- **Interface:** `com\kohler\hermoth\data\network\PlatformApiCall.java` (grep `Anthem…RequestModel`).
- **Command bodies:** `com\utils\network\retrofit\proxy\platform\model\anthem\` —
  `AnthemWriteSoloStatusRequestModel`, `AnthemWriteWarmUpRequestModel`,
  `AnthemWritePresetStartRequestModel`, `AnthemPresetStartStopRequestModel`,
  `AnthemWritePresetControlRequestModel`, `AnthemValveResetRequestModel`,
  `AnthemWriteCreatePresetRequestModel`, `AnthemWriteOutletConfigurationRequestModel`,
  `AnthemWriteUIConfigurationRequestModel`.
- **Valve model:** `com\kohler\hermoth\products\anthem\data\model\AnthemValveControlModel`
  (`gcsValveControlModel`).
- **State / warmup:** `com\kohler\hermoth\products\anthem\data\model\` —
  `AnthemWarmupStateModel`, `State`, `AnthemValveStateModel`, `AnthemSettingsModel`,
  `mqtt\MqttAnthemSoloStatus`.
- **Warmup / valve logic** (obfuscated GCS ViewModels): `p218gj\q.java`, `Si\y.java`,
  `Si\u.java`, `Di\r.java`, `Ei\r.java`, `Fi\z.java`
  (grep `warmUp` / `AnthemWriteSoloStatusRequestModel`).
