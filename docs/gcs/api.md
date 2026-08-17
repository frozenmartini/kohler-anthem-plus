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

**Only two things write `0x40`: the first-gen touchscreen, and the cutoff.** That is what
makes "a close is a cutoff only if its zone is paused" a usable discriminator — every stop a
user is likely to issue writes `0x00` and is ignored by construction.

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

* A preset-timer stop logs `verdict: "ignored"` with a large `off_by` (1800.3 s here). Correct.
* The learned-limit watcher (`SUSPECTED_LIMIT_MIN_SAMPLES = 3`, 2.0 s clustering) **will** cluster
  repeated 1800 s stops and eventually name 1800 s a suspected limit for that zone. That is the
  watcher doing its job, and it is **not** grounds to flip `ACT_ON_LEARNED_LIMITS` — doing so
  would make the integration act on a preset timer through the back door.
* `sensor.<valve>_zone_N_outlet_1_max_run_time` shows the hardware gate. It is not the number
  that will stop a preset-driven shower, and is not meant to be.

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
> * The run-time cutoff is unaffected: it keys off the pause flag, never the preset id.

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

**This identifies the run-time cutoff.** A cutoff produces `0x40` and clears the preset id —
the `action:"Off"` signature, not the `solowritesystem` one. The valve ends the *experience*
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

`POST /platform/api/v1/commands/gcs/warmup`
Body `AnthemWriteWarmUpRequestModel` = `{deviceId, sku:"GCS", tenantId, warmUp:"<mode>"}`.

`warmUp` mode values (from the decompile — `Si\y.java`, `p218gj\q.java`):

| `warmUp` value | Meaning |
|---|---|
| `warmUpDisabled` | Off |
| `warmUpAllOutletsWithNoStartDelay` | Enable — all outlets, **start immediately** (what the app toggle sends on ON) |
| `warmUpAllOutlets` | Enable — all outlets, with configured start delay |
| `warmUpSelectedOutletsWithNoStartDelay` | Enable — selected outlets only, start immediately |
| `warmUpSelectedOutlets` | Enable — selected outlets only, with start delay |

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

### ⚠️ Library bug — `start_warmup` sends no mode

`kohler-anthem`'s `start_warmup` sends `{tenantId, deviceId, sku}` with **no `warmUp`
field** → the device ignores it (200 but no-op). `stop_warmup` sends
`controlpresetorexperience` id `0`, which is unrelated.

Fix: `start_warmup` → `warmUp:"warmUpAllOutletsWithNoStartDelay"`; disable →
`warmUp:"warmUpDisabled"`.

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
