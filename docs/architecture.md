# Anthem Plus — system architecture

What the physical boxes are, which one the app is actually talking to, and which paths can
carry a control command. Read this before the endpoint references — most confusion about
this system comes from assuming there is one device and one API.

## The two products

Kohler sells two things under the Anthem name, and they are **not** a base model and an
upgrade of the same device. They have different hardware, different cloud endpoints, and
different control models.

### Anthem (SKU `GCS`) — the digital valve

A digital valve body with **built-in Wi-Fi** (and likely Bluetooth). It is a complete,
self-contained product: the valve *is* the network device. The Konnect app talks to this
valve directly through the cloud.

Because the valve holds no notion of "my default scene", **every start must specify the
entire valve state** — temperature, flow, and which outlets to open — packed into a 4-byte
command word per valve. There is no bare on/off command.

### Anthem Plus (SKU `HUB`) — valve plus system controller

A **Linux-based system controller** that drives the valves *and* integrates music, lighting,
and steam. That integration is the "Plus". The controller is the network device; the valves
hang off it.

The Konnect app sends commands to **the controller**, not to a valve. The controller stores
its own configuration, so it *does* have a default — a bare
`valvecontrol {valveOnOff:"ON"}` runs it.

> **Naming, because the SKU strings mislead.** The Anthem Plus controller's device ID on
> this account is `gcs-sious0103D` — it begins with `gcs` despite being a HUB. Device IDs
> are **not** a reliable way to tell the products apart. Use the `sku` field.

## Valve models and outlet topology

Four Anthem digital valve models, differing in outlet count **and in how those outlets are
split across the two valves** inside the command word:

| Model | Outlets | valve1 | valve2 | `secondaryValve1` |
|---|---|---|---|---|
| K-28209 | 2 | 2 | — | `00000000` (ignore) |
| K-28210 | 3 | 3 | — | `00000000` (ignore) |
| K-28211 | 4 | 2 | 2 | used |
| K-28212 | 6 | 3 | 3 | used |

**The split is not always 3+3.** On a 4-outlet K-28211 the outlets divide 2+2, so:

```text
K-28211:  Outlet 1,2 → valve1 bits 0,1      Outlet 3,4 → valve2 bits 0,1
K-28212:  Outlet 1,2,3 → valve1 bits 0,1,2  Outlet 4,5,6 → valve2 bits 0,1,2
```

Outlet 3 is therefore valve2's *first* outlet on a K-28211 but valve1's *third* on a
K-28212. Code that hardcodes "valve1 carries outlets 1-3" commands the wrong outlet on a
4-outlet system. Each valve always exposes three outlet bits; a model simply uses fewer.

On the HUB side the same model governs how many outlets appear in a favourite's
`water.zone1`.

> **Unverified:** that a 2-outlet valve uses mask bits 0 and 1, the same low bits a
> 3-outlet valve uses for its first two outlets. Only 3-outlet valves have been tested.

### Zone 1 / outlet 1 is meant to be the main shower

Kohler's documentation expects the main shower on **zone 1, outlet 1**, and the hardware
reflects that: system-level status such as `atTemp` is carried on the **primary valve word
only**, whatever the plumbing actually feeds.

Installs do deviate — the test system has its main shower on **zone 2, outlet 1** because of
a plumbing restriction, and it works normally. But it means the zone doing the work and the
zone reporting system status can be different ones. Anything reading a system-level flag
should take it from the primary valve rather than "whichever zone is running".

### "Valve" means different things on the two APIs

This is the single most confusing naming in the whole system, and it is a deliberate — but
incomplete — attempt to fix a first-generation mistake.

A physical Anthem valve is **one unit containing two zones**, each with up to three outlets.
The original GCS API named those two zones `valve1` and `valve2`, which was wrong: they are
not two valves, they are two halves of one body. The Anthem Plus API corrected the
vocabulary, and the two now disagree:

| | What `valve1`, `valve2`… count |
|---|---|
| **GCS** (`primaryValve1`, `secondaryValve1`…, `valveSettings[]`) | **Zones** — 8 slots = up to 4 physical units |
| **HUB** (`parts.valve1`, `parts.valve2`) | **Physical valve units** |

So they line up like this:

```text
HUB valve1  =  GCS valve1 + valve2   =  primaryValve1   + secondaryValve1
HUB valve2  =  GCS valve3 + valve4   =  secondaryValve2 + secondaryValve3
```

#### Consequence: `parts.valve2: NotConnected` is correct, not a bug

On a single-unit install the controller reports:

```text
parts.valve1              Connected
parts.valve2              NotConnected     ← no SECOND physical valve unit
zonetwo.configuredoutlets 3                ← but zone 2 of the first unit has 3 outlets
```

Both are true. `parts.valve2` is saying "there is no second valve body", not "zone 2 is
absent". **Never gate zone-2 entities on `parts.valve2`** — on a normal 6-outlet install
that would hide half the outlets.

For topology, use **`zoneone.configuredoutlets + zonetwo.configuredoutlets`**, which
describes the zones of the first unit and is what a 6-outlet system actually has.

> This integration follows the **GCS** field names internally, because they are what the
> wire format uses (`primaryValve1` / `secondaryValve1`), but presents **zones** to the user.
> The internal `outlets_valve1` / `outlets_valve2` are therefore zone counts, despite the
> name.

### Outlet types mean different things on the two devices

Both devices store an **outlet type** per outlet (codes like 62, 52, 1, 11, 39, 21 —
handshower, rainshower, tub filler, and so on). What the type *does* differs:

| Device | How flow limits are derived | Does outlet type matter? |
|---|---|---|
| **Anthem** (GCS valve) | From the **flow calibration figure alone** | **No** — the type is a label |
| **Anthem Plus** (HUB) | From **outlet type × flow calibration** | **Yes** — it sets the flow envelope |

On the controller, higher-demand types permit more flow: *multiple showerheads*, *multiple
body sprays*, and *tub filler* all allow a higher maximum than a single showerhead or
handshower. The valve applies no such logic — it honours whatever flow byte it is given,
within its calibrated range.

### HUB flow control is throttled — effect MEASURED, mechanism UNKNOWN

> **⚠️ Corrected later the same day (2026-08-14).** This section first appeared as
> *"double calibration — MEASURED"*, asserting that both devices scale in series and that the
> second stage was the valve applying its own calibration. **A later test disproved the
> mechanism**: the throttling persists on a valve that has **never been calibrated**. The
> *effect* below is solid and reproduced; the *explanation* is withdrawn. See "What the
> uncalibrated-valve test showed" at the end of this section.

**The HUB's flow command is scaled down by a large, repeatable factor before it reaches the
water.** Measured directly, linear in the HUB's slider position.

The owner ran the test that had never been possible before — **HUB flow control enabled**, on
a calibrated valve, with the **first-gen touchscreen disconnected**. Capture:
`captures/2026-08-14_hub_flow_double_scaling/mqtt_raw_20260814T185418Z_*.jsonl`.

Dialling the HUB's flow slider with all three zone-2 outlets open:

| HUB asks | valve byte | valve % | ratio | gpm @ 13.03 |
|---|---|---|---|---|
| 60% | 24 | 12.0% | **0.200** | 1.56 |
| 80% | 32 | 16.0% | **0.200** | 2.08 |
| 100% | 41 | 20.5% | **0.205** | 2.67 |

**Perfectly linear, factor 0.20.** The HUB's slider is not broken — its *full scale arrives at
the valve as one fifth*. Zone 1 is worse still:

```text
11:59:47  HUB  zone=1 status=ON  FLOWRATE=100  outlets=[1,1,1,0,0,0]
          GCS  Z1 05841407  flow byte 20 = 10.0%   out[1,2,3]
```

All three zone-1 outlets open, HUB commanding **100%**, valve delivering **10%** — a **10x**
reduction. The owner independently reported "about 2.5 gpm per zone" from inside the shower;
zone 2 at byte 41 is **2.67 gpm**, and all three of that zone's outlets share it.

This is almost certainly the **"firmware 2.88 flow bug"** — the symptom that made disabling
flow control the recommended workaround. What produces it is still open.

#### What the uncalibrated-valve test showed — and what it ruled out

A second factory reset the same day, with the **GCS setup skipped entirely so the valve was
never calibrated**, the HUB calibrated with flow control on, and **no first-gen touchscreen
connected**. Capture: `captures/2026-08-14_uncalibrated_valve_test/`.

**The throttling persisted.** HUB reporting `FLOWRATE=100` throughout:

```text
zone 2, 1 outlet open   ->  byte 20 = 10.0%
zone 2, 2 outlets open  ->  byte 33 = 16.5%
zone 2, 3 outlets open  ->  byte 40 = 20.0%
zone 1, any outlet count ->  byte 20 = 10.0%   (never moved)
```

That kills two explanations at once:

* **Not the first-gen touchscreen.** Disconnected for this test, and for the sweep above.
* **Not the valve applying its own calibration.** *The valve has no calibration here.* The
  "two stages in series" reading — recorded earlier the same day, and retracted at the top of
  this section — cannot be right.

What remains, neither confirmed:

1. **The HUB alone emits the low byte.** Its own scaling is simply wrong, and the valve is
   faithfully executing what it is told.
2. **The valve has an internal default envelope** that applies even uncalibrated, and still
   scales what it receives.

Distinguishing them needs a HUB-driven flow command observed *before* the valve echoes it,
which the cloud MQTT stream cannot provide — it reports valve state, not the HUB's outbound
command.

#### New in that test: the byte tracks the outlet count

Zone 2 moved 20 → 33 → 40 as one, two, then three outlets opened, with the HUB's slider
untouched at 100% the whole time. That is a **shared per-zone budget being divided among open
outlets**, and it matches what the owner reported from inside the shower — roughly 2.5 gpm per
zone, split three ways. Zone 1 never moved off byte 20 in the same session, which is
unexplained.

#### Loose ends

* **Zone 1 scales by 0.10, zone 2 by 0.20.** The per-zone difference is unexplained; it is
  presumably the ratio of the two devices' calibrations for that zone, but the valve's own
  calibration **cannot be read** — the owner has tried the app, the touchscreen, and the cloud
  API. Only the HUB exposes its figures.
* **The two calibrations genuinely differ**, and the HUB's are not even stable: repeated
  calibrations on the HUB produce slightly different numbers each time.
* **The idle resting byte changed to 20 (10%)** on both zones once HUB flow control was
  enabled — previously 200, or the stored preset ceilings. Unexplained.
* The HUB reports `zone=1` on every `SHOWER_VALVE_STS` while zone 2's byte is what moves,
  consistent with HUB `valve1` = GCS `valve1 + valve2` (see above), but worth care when
  correlating.

<details>
<summary>The original hypothesis, before it was measured</summary>

**Owner hypothesis, 2026-08-14. Untestable from the captures at the time.**

Confirmed by the owner: when flow is driven from the **first-gen touchscreen**, the **valve**
applies the ceiling, using **its own** calibration. The screen is a peripheral relaying
touches (see above), so the scaling is valve-side.

**Both devices hold their own calibration.** So on an install with both interfaces wired in,
a HUB-driven flow command may be scaled *twice*:

```text
user asks for 100% on the Anthem Plus panel
  -> HUB scales to ITS calibrated ceiling      100%  ->  byte 158  (79.0%, zone 2)
  -> valve scales AGAIN to ITS own ceiling     158   ->  byte 125  (62.4%)
```

Compounding, per zone:

| | ceiling | HUB sends | valve re-scales to | net vs "100%" |
|---|---|---|---|---|
| zone 1 | 35.5% | byte 71 | **byte 25** | **12.6%** |
| zone 2 | 79.0% | byte 158 | **byte 125** | 62.4% |

**Zone 1 would deliver 12.6% of what was asked for** — which is exactly the "flow is so weak"
symptom that led to flow control being disabled system-wide as the recommended 2.88
workaround.

> **And the valve is arguably not supposed to be scaling at all here.** On a HUB-only install
> — what Kohler ships — the controller owns the flow envelope and there is one pass. The
> valve applies its own only because a **first-gen screen is also plugged in**, which is the
> configuration Kohler does not document. If that is right, the "2.88 flow bug" is not a
> firmware defect at all; it is two calibration stages in series, and it would only appear on
> installs wired like this one.

**Status at the time: unproven.** HUB flow control had been disabled throughout — all **366**
`SHOWER_VALVE_STS` samples with `status: ON` reported `flowrate: 100` and nothing else — so
the HUB had never been observed writing a non-maximum flow.

**The proposed test — "enable HUB flow control, ask for a mid-range flow, read the byte" —
was run, and confirmed the mechanism.** The predicted per-zone squaring (byte 25 / 125) was
not what appeared; the measured factors are 0.10 and 0.20, which is the same *shape* of
error from a different pair of constants. See the measured section above.

</details>

### The calibration figures are what set the flow ceiling

**A zone's flow ceiling is proportional to its water-line calibration**, against a maximum
that is **system-wide, shared by both zones**. Using the **Anthem Plus (HUB)** calibration
figures — the right ones here, since the HUB is what "sets the flow envelope" per the table
above, and the touchscreen that computes the ceiling *is* the HUB panel:

| | zone total, from the setup wizard's water-line calibration | ceiling |
|---|---|---|
| zone 1 | 2.11 + 1.39 + 1.06 = **4.56 gpm** | 4.56 / 13.03 = **35%** |
| zone 2 | 1.65 + 1.78 + 7.00 = **10.43 gpm** | 10.43 / 13.03 = **80%** |

**Byte 200 is the PER-ZONE maximum.** Kohler publishes 9.5 gpm per outlet and 22.0 gpm for
zone 1 + zone 2 combined, but **no per-zone figure** — and since the flow byte is per zone,
its scale has to be exactly that missing number. 13.03 gpm fills the gap:

| | rating |
|---|---|
| per outlet | 9.5 gpm — published |
| **per zone** | **~13.03 gpm — unpublished, what byte 200 represents** |
| combined | 22.0 gpm — published |

`13.03 x 2 = 26.06` exceeds the 22.0 combined rating, so both zones cannot reach byte 200
together — that is what the touchscreen's linked scaling guards. Both zones at their
*ceilings* is 14.99 gpm, only **68%** of the combined rating, so normal use never approaches
it.

> **Still fitted, never transmitted.** 13.03 is derived from this install's calibration and
> observed ceilings; the clean fit into the unpublished per-zone slot is corroboration, not
> proof. The calibration figures are **HUB-side** — correct, since the HUB computes the
> ceiling — but the GCS valve holds its own, never read. See
> [`gcs/api.md`](gcs/api.md#the-scale-byte-200-is-the-per-zone-maximum-13-gpm).

Two consequences that shape everything about flow on this system:

* **Neither zone can reach 100% alone.** Zone 1 physically tops out around 35%. A UI that
  presents 0–100% per zone is therefore describing a range that does not exist.
* **The top of the byte range is unreachable for both zones at once.** `13.03 x 2 = 26.06`
  gpm against a 22.0 combined rating, so the touchscreen's linked scaling has something real
  to protect. Their *calibrated* totals, 14.99 gpm, sit at 68% of the rating and need no
  scaling at all.

The valve is calibrated at setup: the wizard asks which outlets are default, then requires a
water-line calibration measuring each outlet's real delivery. Those numbers are what the
ceiling is computed from — so **two installs with identical hardware can have different
ceilings**, and nothing in the API exposes the figure.

Full derivation, the independent cross-check against a captured slider sweep, and the caveats
(13.03 gpm is fitted, not transmitted) are in
[`gcs/api.md`](gcs/api.md#-resolved-2026-08-14--the-ceiling-is-the-zones-plumbing-as-a-fraction-of-13-gpm).

**So the same physical outlet can legitimately carry different types on each device, and
that is not a mismatch to fix.** On the test system one outlet is a *Real Rain rainshower*
to the valve and a *regular rainshower* to the controller — deliberately, because the type
changes what the controller will permit.

> **Firmware 2.88 caveat.** The controller's per-type flow calculation is buggy on 2.88, and
> the recommended workaround is to **disable flow control on the Anthem Plus system
> entirely**. The test system runs that way, which is why every outlet reports identical
> limits (`minimumFlowRate: 16`, `maximumFlowRate: 200`) rather than per-type ones, and why
> `atFlow` and the measured-flow byte never populate. Those fields are **untested, not
> broken** — see [`gcs/valve_hex.md`](gcs/valve_hex.md).
>
> With flow control off, flow *setpoints* still work — the valve honours the flow byte — but
> nothing reports reaching a flow target and no per-type limits are applied.

### The HUB reports outlets per zone, padded to six slots

The MQTT `SHOWER_VALVE_STS` message (and the REST `hub-state`) reports each zone's outlets
as a **6-slot array**, e.g. `[1,0,0,0,0,0]` meaning *that zone's* outlet 1 is on. A zone
maps to a valve: **zone1 is valve1, zone2 is valve2**.

Every array is padded to six slots regardless of the hardware. Only the leading slots
belonging to that zone's valve carry meaning:

| Model | Meaningful slots per zone |
|---|---|
| K-28209 | zone1: first **2** |
| K-28210 | zone1: first **3** |
| K-28211 | zone1: first **2**, zone2: first **2** |
| K-28212 | zone1: first **3**, zone2: first **3** |

The trailing slots are always zero and must be **ignored, not read as extra outlets** —
otherwise a 2-outlet valve appears to have six.

Combining the two zones into a single Home Assistant numbering is what produces the global
outlet list: zone1's outlets first, then zone2's. So on a K-28211, `zone2 = [1,0,0,0,0,0]`
is **Outlet 3**, not Outlet 1 and not Outlet 4.

Because the HUB's zone arrays need this same split, **the valve model must be known even on
a HUB-only account** — it cannot be skipped just because there is no GCS device to command.

## Touchscreen interfaces decide what reaches the Konnect app

Not documented by Kohler, and it explains why an account shows what it shows:

| Interface | Plugs into | Adds to Konnect |
|---|---|---|
| **K-28214** (first-gen Anthem) | the digital valve directly | the **GCS valve** |
| **K-28214-ACS** (Anthem Plus) | the **HUB** system controller | the **HUB** only |

The Anthem Plus screen offers **no option to add the GCS valve** to the app. So an Anthem
Plus owner with only the `-ACS` screen sees a HUB on their account and no GCS, even though
a digital valve is physically installed — and therefore cannot use any GCS-only
integration.

**A digital valve has two interface ports.** The manual does not mention it, but a
first-gen K-28214 *and* a HUB controller can be connected to the **same valve**
simultaneously. Both interfaces stay consistent because they share the **wired link** to the
valve.

> ⚠️ **Corrected 2026-08-18.** This sentence previously said the interfaces "take state from
> MQTT and the wired link". They do not take state from MQTT at all. **MQTT is the Konnect
> app's UI channel** — Kohler's cloud invoking direct methods on registered *app clients*, of
> which this integration is one. Device-to-device traffic runs over the RJ wired connection,
> which cannot be sniffed. Getting this backwards produces wrong readings of every capture;
> see [`case_studies/intro.md`](case_studies/intro.md) §1. That is how one physical shower ends up as both a GCS and a HUB entry on the
same account — and it is what makes full GCS control available to an Anthem Plus owner.

### The first-gen touchscreen is a peripheral, not a controller

**Corrected 2026-08-14 by the owner, who installed it.** Easy to get backwards, and this
document previously implied otherwise in the flow sections.

| | |
|---|---|
| **The valve** | **The brain and the network device.** The Wi-Fi radio is *inside the valve*; the cloud API talks to it directly. |
| **First-gen K-28214 screen** | An **input and display peripheral** wired to the valve. It reports what the user touched and renders what the valve reports. Its one privileged action is telling the valve to open its **setup AP** for Wi-Fi onboarding. |
| **Anthem Plus (HUB)** | A separate Linux **system controller** with its own screen, wired to the valve's second port and holding its own cloud identity. |

So the two ports are **not** symmetrical. One carries a dumb peripheral; the other carries a
full computer that considers itself in charge of the valve.

> **How to tell whether a UI is physically present:** its firmware version. The valve always
> reports two slots in `READ_GCS_UI_CFG`, both with a full config block, so the config alone
> proves nothing. **`0.0` means absent.** Confirmed 2026-08-14: `UserInterface1` read `2.2`
> with the first-gen screen connected and dropped to **`0.0`** once it was unplugged, matching
> `UserInterface2` — and matching `SecondaryValve2`–`7`, which report `0` and are known absent.
>
> **This casts doubt on an attribution made elsewhere in these docs.** Several places say
> "the touchscreen computes the flow ceiling and the linked-zone scaling". If the *first-gen*
> screen is a peripheral, it cannot compute anything — meaning either the Anthem Plus panel
> did it, or the **valve itself** does. That matters because the ceiling derivation used
> **HUB** calibration figures, and a valve-side computation would use the valve's own. Flagged
> in [`gcs/api.md`](gcs/api.md#the-scale-byte-200-is-the-per-zone-maximum-13-gpm); unresolved.

## Account shapes to support

An integration cannot assume both devices are present:

| Account has | Means |
|---|---|
| GCS only | First-gen screen. Full valve control; no music, light, or steam. |
| HUB only | Anthem Plus screen alone. Favourites and experiences; **no direct outlet/temperature/flow control**. |
| Both | Both screens on one valve. Full control plus the HUB's accessories. |

Konnect also carries unrelated Kohler product lines (DTV, Numi, Blade, faucets). They share
the account and must be ignored rather than mistaken for Anthem hardware.

## Control paths

Three surfaces exist. Only one of them can actuate anything without extra hardware.

| Path | Reaches | Can control? | Notes |
|---|---|---|---|
| **Kohler cloud REST** | GCS and HUB | ✅ **yes** | The only usable control path. Requires a `B2C_1A_signin` token. |
| **Azure IoT Hub MQTT** | GCS and HUB | ❌ status only | Event-driven state. The app receives here; it does not publish control. |
| **HUB local LAN REST** | HUB only | ❌ **no** | Setup, config, and diagnostics. Cannot turn anything on or off. |

### The local API cannot control the shower

This is the single most surprising finding, and it is easy to waste time on. The Anthem Plus
controller serves a REST API on port 80 over plain HTTP, with its own PIN→JWT auth. It
exposes ~53 read endpoints and a large `req_update_command` surface — and **none of it
actuates the system** on firmware 2.88.

- `water_test_start` runs a **fixed** plumbing self-test (zone 1, outlet 1, ~5 seconds) and
  ignores any temperature, flow, or outlet fields you send.
- `update_*_settings` writes **stored presets and configuration**, not live state.
- The local favourite and experience commands edit the *list*; the "run this now" trigger
  goes through the **cloud**.

So the local API is genuinely useful for reading crude state and for reading and writing
configuration, and useless for control. Full detail in [`hub/local_api.md`](hub/local_api.md).

There is a fourth path — **Control4**, over a certificate-authenticated channel on `:8080`
— which *does* provide local real-time control. Reaching it requires Kohler-issued client
certificates. Parked; see `hub/local_api.md` §7.

## How control differs between the two

The two products are close to opposites in how you drive them.

| | **GCS** | **HUB** |
|---|---|---|
| Unit of control | A **valve command word** (hex) | A **favourite** (a named scene) |
| Direct "set temp/flow/outlets now" | ✅ `solowritesystem` | ❌ does not exist |
| To change settings | Send a new word | Edit a favourite, then activate it |
| Bare on/off | ❌ | ✅ `valvecontrol` |
| Scope | Water only | Water, steam, music, lighting |

On the HUB, "set outlet 1 to 104 °F" is not a command — you create a favourite holding that
configuration and activate it. And **editing a favourite is blocked while the system is
running** (HTTP 400, `statusCode 902`), so the practical pattern is to pre-create one
favourite per state you want and switch between them by activation.

### Favourite ids are reassigned, not stable

Deleting a favourite shifts the ids of the others. Confirmed by a deletion between the
2026-08-10 and 2026-08-11 reads: `AllOff-omit` moved from id 6 to id 5. **Never hardcode a
favourite id** — read the favourites list and resolve by title.

### Which favourite fields exist depends on the accessories

A favourite bundles `water`, `steam`, `music`, and `light`, but only components whose
hardware is attached are meaningful. Read `hub-configuration.parts`, where each component
reports `Connected` / `NotConnected` / `null`:

| Favourite field | Requires |
|---|---|
| `water` | `valve1` / `valve2` connected |
| `music` | `amplifier` connected |
| `light` | `light` connected |
| `steam` | `steam` connected |

The test system has an amplifier only, so `music` is the sole accessory field exercised
live; `light` and `steam` are mapped from the decompile but untested.

None of this affects **activating** a favourite — that is always just an id and a name,
whatever the favourite contains. So accessory support is a question of what you can
*build*, not what you can *run*.

⚠️ **It does affect what you can *read*, and this is a trap.** Because the components are
optional, `MUSIC_STS` / `STEAM_STS` / `LIGHT_STS` and their `favoriteid` are attribution for
one component — "the music playing now was started by favourite 2" — and **not** an answer to
"is favourite 2 running". Four of this account's six favourites carry no music at all, so
activating one of those produces no music-side evidence whatever. `FAVORITE_STS` is the only
message that speaks for the favourite. Full reasoning, the component table and the three
different ways an absent component is spelled: [`hub/cloud_api.md`](hub/cloud_api.md) §5.5.

Note `parts.valve1` / `valve2` count valve **bodies** wired to the controller, not the two
valve halves inside one multi-outlet GCS valve: a 6-outlet K-28212 still shows a single
connected valve here.

## Where state comes from

**MQTT is the state source; REST is for configuration and on-demand snapshots.**

The cloud REST reads are poll-only and partly cached — `amplifierSettings.monoVolume`, for
instance, did not follow a live volume change made on the touchscreen. Both devices push
status over Azure IoT Hub as direct-method messages on
`$iothub/methods/POST/ExecuteControlCommand`.

One subscription is account-level, so a session opened for either device receives messages
for **both**. Filter on `payload.deviceid` and `payload.sku`.

### What this integration reads over REST, and when

`SCAN_INTERVAL = None` — there is no polling loop. REST is read on two events only: **setup**,
and **every MQTT (re)connect**. A manual `homeassistant.update_entity` is the only other way in.

| Call | Taken from it |
|---|---|
| `GET /customer-device/{tenant}` | Device list (nested under `customerHome[].devices[]` — singular key), `temperatureUnit`, `waterUnits`. The unit is load-bearing: **HUB favourite temperatures are written in it** |
| `GET /gcs-state/{id}` | Both valve words — temperature, flow, outlet mask, pause flag; `warmUpState.warmUp` → mode and `warmUpState.state` → in-progress; `totalVolume`; `presetOrExperienceId` |
| `GET /gcs-state/gcsadvancestate/{id}` | Per-outlet `minimumFlowrate` / `maximumFlowrate` / `maximumRuntime` → `OutletLimits`. This is what arms Endless Shower |
| `GET /gcs-preset/{id}` | Preset id, title, `isExperience`. The raw payload is also handed to the preset-1 timer sync, which needs fields `apply_preset_list` discards |
| `GET /hub-state/{id}` | Per-zone status/outlets/temperature/flowRate, `musicStateModel.status`, `hubSteamState.status`, `light[].status`, top-level `showerWarmUp` |
| `GET /hub-configuration/{id}` | `parts` → which accessories are connected. **First seed only** — `hub_capabilities.known` latches it |
| `GET /hub-experience/{id}/favorites` | The controller's favourite list — ids and titles |
| `POST /platform/api/v1/mobile/settings` | IoT Hub host, device id and SAS credentials. Not state: this is what brings the stream up, and it runs on **every connect attempt** because the password is short-lived |

**A cold start is 14 calls; a reconnect is 6** — the mobile-settings POST plus the five reseed
GETs, with `hub-configuration` skipped once known.

⚠️ **Setup used to read the whole account three times.** `async_setup` seeds, then
`async_config_entry_first_refresh()` made the base class seed again milliseconds later, and the
preset timer sync re-read `gcs-preset` on top. Both were folded on 2026-08-21 (20 calls → 14).
The remaining duplication is deliberate: the post-connect reseed repeats the setup read because
the broker replays nothing, so it is the only thing that closes the gap between the setup read
and the stream existing.

⚠️ **Nothing logs a successful seed.** Every debug line in `_async_seed_state` sits inside an
`except` block, so this inventory is derived from the call sites, not measured on the wire. What
*was* measured is the fold: the first refresh logs
`Finished fetching kohler_anthem_plus data in 0.000 seconds`.

**Auth failures cannot escape setup.** Both reads `async_setup` awaits — the customer read and
the seed — map `AuthUnavailable` → `ConfigEntryNotReady` (retry: Kohler was unreachable, the
credential was not rejected) and every other `AuthError` → `ConfigEntryAuthFailed` (reauth
prompt). The seed needs its own mapping because its internal handlers catch only `KohlerError`
per read — deliberately, so one device's failure does not blank the other — while the token
layer under every read raises `AuthError`, which is not a `KohlerError`. Until 2026-08-22 the
seed call was bare, and a token rejection there escaped `async_setup_entry` unhandled: no reauth
prompt, no retry (found 2026-08-21 while proving the startup-read fold).

| Device | Message codes |
|---|---|
| GCS | `GCS_SOLO_STS`, `GCS_WARM_STS`, `READ_GCS_EXPERIENCE_STS` |
| HUB | `SHOWER_VALVE_STS`, `STEAM_STS`, `MUSIC_STS`, `LIGHT_STS`, `FAVORITE_STS` |

### ⚠️ `sysid` names the message, not the device — never filter on it

**Measured 2026-08-20.** `payload.sysid` looks like a device serial and is not one. Across every
live capture, each message `code` carries exactly **one** `sysid`, and each `sysid` belongs to
exactly one `code` — a fixed token per message type, which is what
[`case_studies/intro.md`](case_studies/intro.md) means when it says the `sku` / `sysid` "names
the card, not a sender":

| `data.code` | `sysid` |
|---|---|
| `GCS_SOLO_STS` | `GCS-INJK966T6G` |
| `GCS_WARM_STS` | `GCS-INCB786T2CZ` |
| `READ_GCS_EXPERIENCE_STS` | `GCS-INXR739U7S` |
| `READ_GCS_OUTLET_CONFIG_CFG` | `GCS-INSN096T8W` |
| `READ_GCS_UI_CFG` | `GCS-INBL458T7I` |
| `GCS_PRESET_STS` | `GCS-INRB916T7R` |
| `GCS_RECIEVED_STS` | `GCS-HJNJ78U97P` |
| `DEVICE_REBOOT_STS` | `GCS-INKR097T9K` |

So **several different `sysid` values arrive from one device in one connection**, and two
captures showing different `sysid`s may be the same device seen through different message
types.

**The mapping is identical before and after the 2026-08-14 factory reset, on the same
`deviceid` (`gcs-sio32343h7` for the valve, `gcs-sious0103D` for the HUB)** — checked against
`captures/2026-08-14_valve_reboot_fault/`. A factory reset changed neither. `deviceid` and
`sku` are the identity fields; `sysid` is not.

**When both report the same fact, trust the GCS word.** The HUB's `SHOWER_VALVE_STS` lags
the GCS valve word by 0.3–2 seconds and briefly reports pre-transition outlets, temperature,
and flow. Verified across 315 correlated messages — every mismatch was HUB lag, never a
decode error.

### ⚠️ Silence is not state — a restored zone went 176.77 s without a valve message

**Measured 2026-08-19, confirmed with the owner 2026-08-20.** Across the 18 restores in the
clean corpus, 17 drew a `GCS_SOLO_STS` within **0.06–1.08 s**. One drew none for **176.77 s**:

```text
23:48:34.109  GCS  primaryValve1 0584c840   zone 1 cut at 900.01 s, byte 3 = 0x40
23:48:35      journal: restore_done, mask 0x04 (outlet 3), write_seconds 1.0
23:48:40.518  HUB  SHOWER_VALVE_STS  zone 1 ON, outlets [0,0,1,0,0,0]
              ... 176.77 s, no valve message ...
23:51:31.888  GCS  primaryValve1 0584c804  secondaryValve1 1184c801
```

**The water never stopped.** Owner-established 2026-08-20: outlet 3 came back a few seconds
after the cutoff and ran throughout, and the 23:51:31 message is the owner opening other
outlets from the Anthem Plus screen — which republished zone 1's *unchanged* state alongside
the new ones. Temperature `0x184` (388) = 101.8 °F and flow `0xC8` (200) = 100 % are identical
either side of the gap. This is the app-channel framing in
[`case_studies/intro.md`](case_studies/intro.md) behaving exactly as described: no card change,
no push. **Do not read valve silence as the valve being idle, stuck, or offline.**

**The consequence is ours, not Kohler's.** `ZoneCutoffDetector` anchors a zone's clock in
`update()`, on the first message that shows the zone flowing; the restore path calls only
`note_local_write()`, which never sets that anchor. So the detector logged `flow_start` for
zone 1 at **23:51:31**, water having run since **23:48:35** — an anchor 176.77 s late. Had the
shower continued to the valve's next cutoff, the detector would have measured ~723 s against a
900 s limit and, at `CUTOFF_TOLERANCE_SECONDS = 2`, ignored a real cutoff: no restore, water
off, nothing in the log saying why. **Not observed** — that shower ended at 23:55:38 — and it
is **1 case in 18**. Recorded as a risk, not a rule.

### The HUB does not reflect a valve driven directly

When the shower is driven by POSTing `solowritesystem` to the GCS endpoint, and the Anthem
Plus touchscreen is never touched, **the HUB's reported state does not follow the valve.**

**Verified live 2026-08-11.** `solowritesystem` opened outlet 4 (valve2, outlet 1) at
102 °F / 100% flow. Polled `gcs-state` and `hub-state` every 4 s for 21 s:

```text
              GCS valve2          HUB
t+4s   …21s   out=[100]           z1:OFF z2:OFF  outlets [0,0,0,0,0,0]
```

The GCS reported the open outlet immediately and held it. `hub-state` reported an idle
system for the entire session. The account owner corroborates that the HUB's **Alexa and
Google Home** states also stay OFF throughout such a session — so this is not a quirk of one
read path, it is the HUB genuinely not tracking the valve.

The same run confirmed two things against hardware rather than inference:

* **Outlet 4 is valve2's first outlet** — `v2: out=[100]`, matching the K-28212 topology.
* **The flow scale is byte ÷ 4** — a 50% command produced `flowSetpoint 25`, and 100%
  produced `flowSetpoint 50`.

### Settled: the HUB reports only OFF states, never a GCS-driven open outlet

Measured 2026-08-12 with outlet 4 held open for **five minutes** via `solowritesystem`,
captured simultaneously by two independent MQTT clients (a fresh one and the long-running
bridge, both well past the warm-up window):

```text
01:38:34  GCS  GCS_SOLO_STS      v1=0184c800 → v1=0185c800 v2=1185c801   outlet 4 ON
01:38:36  GCS  GCS_SOLO_STS      v1=0585c800 v2=1185c801                 prefix 01→05
          ──────────  5 MINUTES, ZERO HUB MESSAGES  ──────────
01:43:35  GCS  GCS_SOLO_STS      v1=017cc800 v2=117cc800                 stop
01:43:35  HUB  SHOWER_VALVE_STS  zone1/zone2 status=OFF outlets=[0,0,0,0,0,0]
                                 temperature=null flowrate=null
```

So, precisely, **for `solowritesystem`**:

* The HUB **does** emit `SHOWER_VALVE_STS` in response to a GCS command — but only when the
  resulting state is **OFF**.
* It emits **nothing at all** while a GCS-driven outlet is open.
* Its messages carry `status=OFF`, an all-zero `outlets` array, and **null** `temperature`
  and `flowrate`.

The HUB therefore never reflects a `solowritesystem`-driven open outlet on any surface —
MQTT, `hub-state`, Alexa, or Google Home. Prefer the valve word whenever a GCS device exists.

#### Scope: this is about `solowritesystem`, not every GCS command

The finding above was measured with `solowritesystem` only, and it holds exactly as written:
the one transition the HUB does not report is **off → any state with an outlet on**, sent as
a raw valve write.

**Preset activation is a different trigger, and the HUB does respond to it.** First tested
2026-08-12, and consistent with the rule above rather than a counter-example to it:

```text
20:58:06  GCS  outlet 4 (zone 2 / outlet 1) OPEN via {preset, action:"On"}
20:58:07  HUB  SHOWER_VALVE_STS  zone1 OFF, zone2 OFF, outlets [0,0,0,0,0,0],
                                 temperature null, flowrate null
```

So the HUB emitted — but the **content is still wrong**, reporting the shower off one second
after water started. Emitting and reporting accurately are separate questions, and only the
first varies by trigger.

The state-source policy is unchanged: never take outlet, temperature, or flow state from the
HUB when a GCS device exists. Whether the HUB stays silent or answers with a false `OFF`, it
is not a usable source for a GCS-driven session.

> **Two earlier claims in this document were wrong and are recorded here so the same
> mistakes are not repeated.**
>
> 1. "The HUB emits no `SHOWER_VALVE_STS`" — the right conclusion from a broken
>    measurement. The client used to verify it was receiving nothing at all, including
>    `GCS_SOLO_STS`, so it could not have detected anything. See the warm-up section of
>    [the MQTT runbook](mqtt/capture_runbook.md).
> 2. "The HUB does emit `SHOWER_VALVE_STS`" — an over-correction. That test fired
>    stop-words, which are themselves OFF transitions, and OFF is exactly the case the HUB
>    does report. Testing an "is it silent?" hypothesis with a command that produces the
>    one state it is not silent about proved nothing.
>
> The lesson for future work here: a trigger that cannot distinguish the hypotheses is not
> a test. Use an **open outlet** when asking what the HUB reports about open outlets.

That fixes the state-source policy:

| Account | Outlet / temperature / flow source | Why |
|---|---|---|
| GCS + HUB | **GCS valve word** | The HUB is silent during GCS-driven sessions |
| GCS only | **GCS valve word** | The only source |
| HUB only | **HUB `SHOWER_VALVE_STS`** | No valve word available; driven by favourites, which the HUB does report |

Implemented as `resolve_outlet_source()` in `anthem_plus/models.py`, so it is a single
decision rather than a convention each entity has to remember.

### ⚠️ That policy applies to the VALVE's entities — not the controller's — 2026-08-18

The table above answers "where does the physical water state come from". It was also, until
2026-08-18, feeding the **Anthem Plus device's own switches**, and there it produced a false
positive: `switch.anthem_plus_shower` and `switch.anthem_plus_system` reported showers the
controller had never been told about.

The measurement that settled it, written up in full as
[case study 1](case_studies/01_ha_driven_shower_hub_blind.md). An 86-minute shower on
2026-08-18 — zone 2 outlet 4 open 07:52:01 local, the valve's 3600 s pause and our restore at 08:52, stopped by hand at
09:18 — driven entirely through `solowritesystem`. The capture
(`mqtt_raw_20260818T052055Z_71_0b22dd90.jsonl`) holds **five `GCS_SOLO_STS` messages and
nothing else**: no `SHOWER_VALVE_STS`, no HUB message of any code, for the whole shower.
The controller's last word of any kind had been 18:51:31 the previous evening. Both
controller switches tracked the shower faithfully throughout, which read as health and was
in fact the valve wearing the controller's name.

So the two devices answer two different questions, and both answers are true at once:

| Device | Question its entities answer | Source |
|---|---|---|
| **Anthem Valve** | Is water physically running? | GCS valve word — authoritative, always |
| **Anthem Plus** | Does the controller know about it? | HUB `SHOWER_VALVE_STS` outlet arrays only |

The second is not a lesser version of the first. It decides whether the controller's
`stopall` and `valvecontrol OFF` have anything to stop, and whether its 60-minute session
ceiling is counting — see [the 60-minute session ceiling](gcs/api.md). A controller
reporting "off" during a running shower is giving a correct and useful answer to its own
question.

Implemented as `coordinator.hub_water_is_running`, which backs both Anthem Plus switches and
is the any-of over exactly the `ControllerOutletSensor` rows, so a switch can never disagree
with the sensors beneath it. `EXPOSE_CONTROLLER_WATER_STATE` in `const.py` publishes those
rows on a both-devices account and is **no longer the temporary debugging flag its name
suggests**. Pinned by `tests/test_hub_switch_source.py`.

### Two devices, not one merged device

A GCS and a HUB on one account are usually the same physical shower reached through two
touchscreens — but they are presented as **separate Home Assistant devices**. They behave
differently, their state arrives on different schedules, and merging them would imply a
consistency that does not exist. The GCS device owns outlets, temperature, and flow; the
HUB device owns favourites, experiences, music, and its accessories.

## Why most integrations only support GCS

The upstream `yon/kohler-anthem` library reverse-engineered the GCS valve only, so the
Home Assistant integrations built on it inherit that limit. The HUB's favourite-centric
command surface, its local API, and its music/light/steam models are documented here for the
first time — that is what makes this project **Anthem Plus** rather than Anthem.

## Reading order

1. This document.
2. [`gcs/valve_hex.md`](gcs/valve_hex.md) — the valve command word, if you touch GCS at all.
3. [`gcs/api.md`](gcs/api.md) or [`hub/cloud_api.md`](hub/cloud_api.md) — the endpoints.
4. [`mqtt/capture_runbook.md`](mqtt/capture_runbook.md) — wiring up live state.
5. [`hub/local_api.md`](hub/local_api.md) — only if you need config, diagnostics, or Zigbee.
