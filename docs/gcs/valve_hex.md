# GCS Valve Hex Reference

How the Anthem GCS valve command word encodes temperature, flow, and outlets,
in both directions:

- **Encode** — building `primaryValve1` / `secondaryValve1` for the HTTPS
  `commands/gcs/solowritesystem` endpoint.
- **Decode** — reading them back out of the MQTT `GCS_SOLO_STS` status message.

Both directions use the same layout, so an encoder and a decoder that disagree
are wrong. Device: `gcs-sio32343h7` (SKU `GCS`).

| Where it is implemented | File |
|---|---|
| Encoder (Home Assistant) | `scripts.yaml` → `anthem_valve_hex_convert` |
| Sender | `kohler_konnect_custom/send_solowritesystem.py` |
| **Decoder — authoritative** | `kohler_konnect_custom/mqtt_capture.py` → `decode_valve_state()` |

**`mqtt_capture.py` is the reference implementation.** Where any other document or library
disagrees with it, it wins — its constants (`VALVE_TEMPERATURE_BASE_C = 25.6`,
`VALVE_TEMPERATURE_STEP_C = 0.1`, `VALVE_FLOW_PER_PERCENT = 2`, `OUTLET_MASK_BITS = 0x07`,
`VALVE_PAUSE_FLAG = 0x40`) are the ones validated against the captures below. Two earlier
decompile-derived readings contradicted it and are recorded in
[Superseded readings](#superseded-readings).

## Word layout

The valve fields are 16 hex characters; only the **first 8** carry the command.
The trailing 8 have been `00000001` in every captured message and are ignored.

```text
 0 1 | 2 3 | 4 5 | 6 7
  01 | 84  | C8  | 07
  ^     ^     ^     ^
  |     |     |     └─ outlet mask
  |     |     └─────── flow
  |     └───────────── temperature
  └─────────────────── prefix
```

Two valves, each with three outlets:

| Field | Valve | Home Assistant outlets |
|---|---|---|
| `primaryValve1` | valve1 | 1, 2, 3 |
| `secondaryValve1` | valve2 | 4, 5, 6 |

`secondaryValve2` … `secondaryValve7` exist in the payload but are
`0000000000000000` on this system.

## Byte 0 — valve index, status flags, temperature high bits

**RESOLVED 2026-08-12** from `p315jj/h.java` in the app decompile, verified against 363
captured messages. Byte 0 is not a prefix, and **read and write layouts differ**:

```text
status (read):   [valve index : 4][atFlow : 1][atTemp : 1][temp high : 2]
command (write): [valve index : 4][   0      ][   0      ][temp high : 2]
```

| Mask | Read | Write |
|---|---|---|
| `0xF0` | valve index — `0` primary, `1` secondary, `2` third… | same |
| `0x08` | **`atFlow`** — reached its flow setpoint | always 0 |
| `0x04` | **`atTemp`** — reached its temperature setpoint | always 0 |
| `0x03` | temperature bits 8–9 | same |

`atFlow` and `atTemp` are **read-only status the device asserts**. The client hardcodes both
to zero when building a command, which is why they never appear in a word we send. In the
app they land in `ValveStatusModel.atFlow` / `.atTemp`.

> **Correction, decompile 2026-08-17: THREE bits are hardcoded on write, not two.** The single
> command encoder `h.s1()` builds byte 0 by string concatenation —
> `i(index + "000" + binaryString)` — and because temperature never exceeds 500 tenths that
> last piece is always one character. So bit 1, the *high* bit of the 2-bit temperature field,
> is a literal zero too. The effective write contract is:
>
> ```text
> byte0 = (valveIndex << 4) | (temperature >> 8)      with temperature <= 511
> ```
>
> There is no branch, flag or parameter: the app is structurally incapable of setting `atFlow`
> or `atTemp` on a write. `encode_word` here masks with `0x03` rather than hardcoding, which is
> equivalent given `TEMPERATURE_MAX_TENTHS` is 488 — bit 1 can never be reached.
>
> Corroboration that these are not protocol fields at all: in the **preset** word (`h.W()`, a
> different 6-hex format) the same bit positions carry **outlet flags**.

### `atTemp` is SYSTEM-level, and lives only on the primary valve

Confirmed against the touchscreen by a deliberate experiment. The user narrated their
actions; the bit matched exactly:

| Time | What the user saw | Bit |
|---|---|---|
| 09:49:50 | water on, screen **flashing** 102 | clear |
| 09:50:26 | flashing stops, **solid** 102 | **set** |
| 09:52:05 | shower off | clear |

So `atTemp` is precisely what the touchscreen's flashing indicates: the delivered water has
reached the displayed setpoint.

**It is reported only on `primaryValve1`, and it describes the whole system.** The secondary
valve never asserts it — 0 of 133 in that session — even though zone 2 was the *only* zone
running when the water came up to temperature.

That aligns with Kohler's documented expectation that **zone 1 / outlet 1 is the main
shower**. System-level status is carried on the primary word regardless of what the plumbing
actually feeds, so an install that puts the main shower on zone 2 (as the test system does,
for plumbing reasons) still gets a correct signal — just not from the valve doing the work.

> **Do not read it as "currently at setpoint" from sampled data.** The channel is
> event-driven with gaps of 20 s or more; the user observed the screen re-flash for two to
> five seconds after each setpoint change, and none of those clears appear in the log. An
> earlier analysis concluded from "43 setpoint changes, bit never cleared" that the label
> was wrong. That was treating absence of evidence as evidence of absence on a channel that
> cannot support it.

#### Why the ice experience does not contradict this

During the ice ramp the screen flashed continuously while the bit stayed set. Both are
correct, because two different comparisons are running:

* the **valve** walks its own setpoint down in 1.0 °C steps, and is always at whatever it
  just commanded → `atTemp` set;
* the **screen** shows the experience's *target*, which the cold supply cannot reach →
  flashing.

The ramp is the valve tracking what it can actually achieve, not the experience failing.

#### `atFlow` (`0x08`) — flat zero, but probably because flow control is off

Never observed set across 496 captured messages. `atTemp` toggles correctly in those same
messages, so it is not a decode error or a sampling gap.

The likely cause is configuration, not firmware: **the test system has flow control disabled
at the fixture**, a deliberate workaround because it is reportedly broken on HUB firmware
2.88. With flow control off, nothing has a flow target to reach, so nothing reports reaching
one. The measured-flow byte (byte 6) is also flat zero on the same system, which fits.

> An earlier revision of this document asserted the firmware simply does not drive the bit.
> That attributed a configuration state to the hardware. The honest position is that
> **`atFlow` is untested**, not broken — confirming it needs a system with flow control
> enabled.

This is also a reminder that the fixture's own settings shape the wire data. A field reading
zero may mean "disabled", not "unsupported".

<details>
<summary>How this was resolved, and what was ruled out first</summary>

The bit resisted explanation for a while because nothing in the *payload* correlates with
it. Ruled out against 363 messages before the decompile settled it:

| Candidate | Result |
|---|---|
| Valve 1's own outlet-1 bit (`byte3 & 0x01`) | set with outlet1 on ×67, off ×122 — no |
| Any valve-2 outlet open | set/open ×82, set/closed ×107 — no |
| Outlet mask generally | `05` occurs with masks 0, 1, 3, 4, 5, 7 |
| `currentSystemState`, `presetOrExperienceId`, `BLEConnected`, `IoTActive`, `firmwareUpdate` | constant across both values |
| Alternation / toggle | no — persists in runs (`05→05` ×32, `01→01` ×22) |

The one correlation that *did* hold was dismissed as too small: all 9 `warmUpInProgress`
samples had the bit clear. That was the actual mechanism — during warmup the valve is still
climbing, so `atTemp` is correctly false. A small sample with a causal story behind it is
not noise.

The decisive question turned out not to be "what does `0x04` mean?" but **"does the app parse
byte 0 at all, or only construct it?"** It parses it: `p315jj/h.java` `r0()` → `A()` slices
byte 0 into `ValveStatusModel` fields by binary-string substring, with no numeric masks or
named constants anywhere — which is why grepping for `0x04` found nothing.

</details>

The device reports more values than it accepts:

| Reported | Valve1 | Valve2 |
|---|---|---|
| `01` | 135 messages | — |
| `05` | 169 messages | — |
| `00` | 2 messages | — |
| `11` | — | 313 messages |
| `10` | — | 2 messages |

The high nibble identifies the valve. The low-nibble bits (`0x04` on valve1,
`0x01` on both) are **not understood**. They do not correlate with warmup
status, preset ID, system state, or the outlet mask — `01` and `05` both appear
alongside mask `00` and mask `07`. Decoders should ignore byte 0; the outlet
state is fully determined by byte 3.

## Bytes 0-1 — temperature is 16-bit

**Corrected 2026-08-12.** Temperature spans two bytes as tenths of a degree Celsius, using
**two** bits of byte 0 — so it is a 10-bit value, representable to 102.3 °C:

```text
°C = ((byte0 & 0x03) << 8 | byte1) / 10

encode:  tenths = round(°C * 10)
         byte0 |= (tenths >> 8) & 0x03
         byte1  = tenths & 0xFF
```

Bit `0x02` was never set across 363 captures (nothing reached 51.2 °C), which is why a
one-bit reading agreed with every sample while still being the narrower model.

The earlier formula `°C = 25.6 + byte1/10` was the same arithmetic in disguise — 256/10 is
25.6 — and silently assumed the high bit was always set. It agrees on all 357 captured words
where the bit **is** set, and is wrong where it is not: `0000C800` and `1000C800` are
**0.0 °C**, which the old formula reported as 25.6 °C.

This also dissolves the "mysterious base": there is no base. 25.6 °C is simply the lowest
temperature whose high byte is 1.

```text
legacy (equivalent whenever byte0 & 0x01):
  encode:  byte = round((°C - 25.6) * 10)
  decode:  °C   = 25.6 + (byte / 10)
```

Representable range is **0.0–102.3 °C**, since the value is 10-bit. Cold temperatures are
perfectly expressible — 4.0 °C is `0028…`, 10.0 °C is `0064…` — they simply have byte 0's
high bit clear, which is why `0x00` / `0x10` appear as byte 0 in the captures rather than
being corrupt.

> A superseded revision claimed the range was 25.6–51.1 °C and that "anything below 25.6 °C
> clamps to `0x00`". That followed from the 8-bit misreading; 25.6 °C is merely where the
> high bit turns on.

Writes are clamped to **48.8 °C (488 tenths)** because the Konnect app never sends above it,
not because the encoding cannot carry more.

The byte accepts up to `0xFF`, but the Konnect app's own decompile treats **`0xE8`
(48.8 °C / 119.8 °F) as the maximum** it will send. Whether the firmware enforces that cap
or merely the app does is untested — do not assume values above `0xE8` are safe to write.

| Byte | °C | °F |
|---|---|---|
| `0x00` | 25.6 | 78.1 |
| `0x47` | 32.7 | 90.9 |
| `0x84` | 38.8 | 102.0 |
| `0x90` | 40.0 | 104.0 |
| `0xFF` | 51.1 | 124.0 |

Kohler's REST API reports temperatures in Celsius regardless of the account's
display unit, and so does this byte. Convert at the edge.

## ⭐ Fahrenheit is a LOOKUP TABLE, not arithmetic — decompile, 2026-08-17

`h.z()` (`p315jj/h.java:1971`) maps a displayed whole °F straight to tenths of a °C through a
hardcoded 64-entry switch covering 59–122 °F. It is **not** `round((f − 32) × 50 / 9)`. Above
86 °F it sits exactly one tenth *below* that formula at sixteen entries — 87, 89, 91, 93, 96,
98, 100, 102, 105, 107, 109, 111, 114, 116, 118, 120 — precisely the set where naive rounding
would round up.

**The low bias is the mechanism, not sloppiness.** Paired with `h.j(c) = round(c × 1.8 + 32)`
for display, it makes the round trip exact: `z(j(t)) == t` for all 64 entries. Naive arithmetic
breaks it on **12 of the 34 values this integration's slider offers**, every one by +1 tenth.

| displayed | Kohler `z()` | naive arithmetic | drift |
|---|---|---|---|
| 102 °F | `0x184` (388) | `0x185` (389) | **+1** |
| 101 °F | `0x17F` (383) | `0x17F` (383) | 0 |
| 100 °F | `0x179` (377) | `0x17A` (378) | **+1** |
| 99 °F | `0x174` (372) | `0x174` (372) | 0 |
| 98 °F | `0x16E` (366) | `0x16F` (367) | **+1** |

This is why the touchscreen's values always sit 0.04–0.16 °F *below* the integer they display:
that is the table, and the touchscreen and the app share it.

### 🚨 `0x185` (389) is our fingerprint, and it was our bug

No Kohler client can emit 389. It is absent from `z()`, and the Celsius path writes whole
degrees (380/390/400). Yet it appears **11 times in this system's capture corpus**, on
2026-08-14. Those were this integration's own writes, through
`unit_to_celsius`'s arithmetic — which is what the owner was seeing when they reported the
temperature "coming back one more" after a restart. **Fixed 2026-08-17:** the table is now in
`anthem_plus/valve_hex.py` as `FAHRENHEIT_TO_TENTHS_C` and `unit_to_celsius` uses it, with
`test_temperature_ladder.py` pinning every slider value against it.

The valve accepts off-ladder values perfectly happily — this is not a protocol requirement.
What it cost was that a setpoint written from Home Assistant no longer sat where the
touchscreen would have put it, so the next panel adjustment started from a value one tenth off.

### ✅ The reported symptom has not recurred — 2026-08-18

**Session 9 left the whole-degree jump the owner actually reported ("lowered to 101, restored
to 102") open, with an experiment planned. Four sessions of evidence later it has not
reappeared.**

Every valve temperature in the corpus was re-checked against the ladder — **2892 readings
across all 89 capture files**. Excluding whole-degree Celsius values, which are the
Celsius-native path and legitimate, the off-ladder population is:

| value | count | dates |
|---|---|---|
| **`0x185` (389)** — our arithmetic fingerprint | **66** | 08-07, 08-08, 08-11, 08-12, **last on 08-14** |
| a `*8` block, `0x09E` (158) … `0x17A` (378) | 3–4 each | **08-12 only** — a systematic sweep from the preset-decompile work |

**Nothing has been off-ladder since 2026-08-14**, and the fix landed 2026-08-17.

The symptom itself was also directly exercised:

* **[Case study 5](../case_studies/05_three_restarts_and_the_unexplained_00.md) §8a** — three
  Endless Shower restores at three different setpoints, `383` → `383`, `377` → `377`,
  `366` → `366`. Byte-exact, no drift, no whole-degree jump.
* **[Case study 4](../case_studies/04_two_touchscreens_and_what_off_means.md) §7** — sixteen
  setpoint changes from both physical touchscreens, every intermediate value on the ladder,
  mirrored exactly by the controller.

> ⚠️ **What this does and does not prove.** The restore path preserves
> `word.temperature_celsius` directly and never converts from Fahrenheit, so **case study 5
> exercises preservation, not the ladder.** `unit_to_celsius` — the function that was fixed —
> runs only when a temperature is set from the Home Assistant entity, and no such write appears
> in any capture since the fix. So: **the reported symptom is not reproducible and the
> fingerprint is gone, but the ladder itself has not been re-verified on hardware.**
> `test_temperature_ladder.py` pins it offline against all 34 slider values in both directions.

Outside 59–122 °F the app returns **0**, which on a device that opens water valves would mean
full cold. `unit_to_celsius` falls back to the arithmetic instead of copying that.

> **The Celsius path really does drift, in the app.** `Pi/A.java`'s `W()` displays
> `round(38.8) = 39` and writes `39 × 10 = 390` — a genuine +0.2 °C per touch. This account is
> in Fahrenheit so it does not bite, and it should **not** be ported.

## Byte 2 — flow

```text
encode:  byte = percent * 2
decode:  percent = byte / 2
```

| Byte | Flow |
|---|---|
| `0x47` | 35.5% |
| `0x9B` | 77.5% |
| `0xC8` | 100% (maximum) |

### Four scales for one byte — including a physical one

The same value is reported on three different scales depending on where you read it, and
maps to a fourth in the real world. The first three are the most likely source of a silent
2× or 4× error:

| Scale | Range | From the byte | Where it appears |
|---|---|---|---|
| Byte | `0x00`–`0xC8` | — | the wire format, here and in MQTT |
| `flowSetpoint` | 0–50 | byte ÷ 4 | GCS `gcs-state` — the device's native unit |
| Percent | 0–100 | byte ÷ **maximumFlowRate** × 100 | HUB favourite `flowrate`, Home Assistant entities |
| **US gallons per minute** | 0–~13 | **byte ÷ 200 × 13.03** | the physical system — fitted, never transmitted |

> ⚠️ **Percent is a ratio against the configured ceiling — confirmed by decompile 2026-08-17.**
> The app decodes byte 2 as `byte / 4.0` (the setpoint scale) and computes the *displayed*
> percentage as `h.B(flow, maxFlow)` — a ratio against that outlet's `maximumFlowRate`, which
> is itself divided by 4 (`AnthemCustomizationActivity:1932`). So **`byte ÷ 2` is correct here
> only because this install reports `maximumFlowRate` `0xC8` (200) on all six outlets.**
> `FLOW_PER_PERCENT = 2` in `valve_hex.py` carries that assumption. It is right for this
> system and wrong for any install with a lower ceiling, where writing "100%" would send
> double the intended flow. `OutletLimits` already reads the real ceiling; wiring it into the
> percent conversion is an open item, deliberately not done blind on a device that runs water.

On the reference install **flow byte `0xC8` (200, 100%) works out at ~13 gpm**, and byte
`0x10` (16, the floor) at ~1.04 gpm. That maximum is **system-wide, shared by both zones**,
which is why neither zone reaches 100% alone — zone 1's whole plumbing is 4.56 gpm, so it
tops out at 35%.

**That maximum is PER ZONE.** Kohler publishes 9.5 gpm per outlet and 22.0 gpm for both zones
combined, but no per-zone figure — and the flow byte is per zone, so its scale is exactly that
missing number.

> **Fitted, never transmitted.** 13.03 comes from this install's HUB calibration and its
> observed ceilings; nothing on the wire carries it. Treat the gpm column as well-corroborated
> for this system, not as a protocol constant. Full reasoning in
> [`api.md`](api.md#the-scale-byte-200-is-the-per-zone-maximum-13-gpm).

Verified live 2026-08-11: with the shower idle, `gcs-state` reports `flowSetpoint: "50"` on
both valves, and 50 × 4 = `0xC8`, the maximum flow byte.

The outlet configuration's documented `flow 16–200` range is in **byte** units
(`0x10`–`0xC8`) — neither of the other two scales.

**The HUB has no flow of its own** — but be careful which direction that claim covers.

* **Read: evidenced.** Across **366** `SHOWER_VALVE_STS` messages with `status: ON`, the HUB
  reports `flowrate: 100` while the valve word carries byte 200. 1:1, no scaling.
* **Write: measured 2026-08-14, and it is NOT straight through.** With HUB flow control
  enabled, the HUB's flow arrives at the valve scaled down by a fixed factor — **0.20 on zone
  2, 0.10 on zone 1**. Asking the Anthem Plus panel for 100% produces valve byte **41**
  (20.5%) on zone 2 and **20** (10.0%) on zone 1, linearly across the whole slider.

**Do not assume a HUB flow value equals the valve's.** Full measurement and the mechanism —
both devices calibrate independently and both scale, in series — in
[`../architecture.md`](../architecture.md#why-hub-flow-control-is-broken-double-calibration--measured-2026-08-14).

### How the ceiling is *observed*: the byte-2 dip

The ceiling is never announced. The only way it becomes visible is a **transient dip in byte
2**: while a zone is stopped (`0x00`) or paused (`0x40`), the valve briefly reports its
calibrated ceiling in place of the setpoint, then reverts to `0xC8`.

```text
14:50:37.285  pv1=0184 47 00…  sv1=1184 c8 00…   zone 1  100% -> 35.5%
14:50:37.396  pv1=0184 47 00…  sv1=1184 9b 00…   zone 2  100% -> 77.5%
14:50:38.614  pv1=0184 c8 00…  sv1=1184 c8 00…   both back to 100%
```

Mask, preset, `configChangeIndent` and temperature are unchanged across the burst — only byte
2 moves. Measured over the `kohler_konnect_custom` corpus (2026-08-07 → 08-13):

| | dip cycles | within 5 s | median |
|---|---:|---:|---:|
| `primaryValve1` | 62 | 38 | 2.4 s |
| `secondaryValve1` | 60 | 32 | 2.8 s |

Both zones dip together, so that is ~38 paired events. **62.3% of all flow changes in that
corpus (213 of 342) occur immediately after a `0x00` or `0x40` word**, and the flow running
before the stop was `100%` in 58 of 62 cases on each zone.

The ceiling values are **exclusive to non-running words**. `0x47` (35.5%) appears 67 times —
58 idle, 9 paused, **0 running**; `0x9B` (77.5%) 76 times — 63 idle, 13 paused, **0 running**.
So byte 2 carries two different meanings: the delivered setpoint while flowing, and the
calibrated **capability** while stopped.

A recalibration is visible in that corpus as the pair changing cleanly between 08-12 20:25 and
23:42 — zone 1 `35.5% → 34.5%`, zone 2 `77.5% → 82.5%`.

In the integration's own corpus the same dip appears but slower — median ~92 s, with 12 landing
1–154 s after a `DEVICE_REBOOT_STS`.

> **Nothing on the wire reports calibration.** `minimumFlowRate` and `maximumFlowRate` are
> **constant at `16` and `200`** on every outlet, in both corpora, before and after every
> factory reset. They are device constants, not calibration, and **no field ever goes null**.
> An earlier note in this project implied a null after a factory reset; that was an artifact of
> a diff script printing its own "no previous value" sentinel, not device data. Corrected
> 2026-08-15. Do not go looking for a calibration field — there has never been one.

### An uncalibrated valve has NO ceiling — measured 2026-08-15

**After a factory reset in which the valve was never calibrated and flow control was never
enabled, the ceiling tied to the ~13 gpm per-zone maximum disappears completely.** Byte 2 sits
at `0xC8` (200, 100%) the whole time: **no dip, no correction, no calibration ceiling taking
over.**

Last non-`0xC8` word anywhere: **2026-08-14T21:38:18Z**. Every valve word since is `0xC8` —
including all **74** words of a full 40-minute two-zone shower on 08-15, across masks
`0x00`–`0x07` and `0x40`.

**The HUB *was* calibrated** — that step is required and was completed. So a calibrated HUB
alone does not produce the ceiling.

**What this refines.** The derivation in [`api.md`](api.md#-resolved-2026-08-14--the-ceiling-is-the-zones-plumbing-as-a-fraction-of-13-gpm)
uses **HUB** calibration figures and attributes the computation to the touchscreen. The
prediction still holds — 35% and 80% against observed 34.5–36.0% and 78.0–82.5% — but this test
shows the **valve** is what applies the clamp, from its own calibration. With the HUB
calibrated and the valve not, no ceiling appears at all. The HUB figures predicted well because
both devices were calibrated from the same plumbing, not because the HUB enforces it.

**Confounded, stated plainly.** Three conditions changed together — factory reset, valve
calibration skipped, flow control left disabled. Which one is *necessary* is untested; only the
combination is measured.

### Flow is always commandable through the hex word

Flow can be set via the valve word regardless of the valve's "flow control enabled"
setting. That setting appears only to expose flow control on the **touchscreen** UI; it
does not gate the API. The Konnect app POSTs a fresh `solowritesystem` on every
temperature, flow, or outlet adjustment — it never forces a fixed flow, including on
preset start.

## Byte 3 — outlet mask + state flags

Full layout, from `p315jj/h.java` (`i(skipWarmUp + state + "000" + out3 + out2 + out1)`):

```text
byte3 = [skipWarmUp : 1][state : 1][0 0 0][outlet3][outlet2][outlet1]
          0x80            0x40                0x04    0x02    0x01
```

| Mask | Meaning |
|---|---|
| `0x80` | **`skipWarmUp`** — start without triggering warmup. Never sent by this client; untested. |
| `0x40` | **`pauseFlag`** — the session is held. Round-trips the device's own flag (write: `getPauseFlag()` in `Pi/r.java`; read: decodes into `ValveStatusModel.pauseFlag`). |
| `0x07` | the three outlet bits |

**The outlet mask is only the low three bits.** `0x40` is an *independent* pause bit, not a
mask value, and it coexists with outlet bits — a paused valve keeps the assignment it will
resume to:

| byte 3 | Meaning |
|---|---|
| `00` | idle — nothing assigned, nothing flowing |
| `01` / `02` / `04` | running to outlet 1 / 2 / 3 |
| `07` | running to all three |
| `40` | **paused**, nothing assigned |
| `41` / `42` / `44` | **paused**, outlet 1 / 2 / 3 still assigned |
| `47` | **paused**, all three still assigned |

Valve 2's outlets are Home Assistant outlets 4–6 on a 6-outlet model; see
[`../architecture.md`](../architecture.md) for the model-dependent split.

> ### ⚠️ IMPORTANT — who writes `0x40`, and what it means when a preset id clears with it
>
> `0x40` on its own means only "paused". Three different things produce it, and the
> **preset id** is what tells them apart:
>
> | Source | Byte 3 | `presetOrExperienceId` |
> |---|---|---|
> | Touchscreen pause button | `0x40` (or `0x41`…`0x47` with assignment) | unchanged — already `0` on a direct session |
> | `{preset, action:"Off"}` | `0x40` on **every zone the preset drives** | **cleared to `0`** |
> | **Valve run-time cutoff** | `0x40` — *identical to `action:"Off"`* | **cleared to `0`** |
> | `solowritesystem` mask `0x00` | `0x00` — a genuine stop, not a pause | unchanged |
>
> **The run-time cutoff performs the same `action:"Off"` the cloud API exposes.** Verified
> live 2026-08-13: driving a two-zone preset and firing `action:"Off"` by hand produced words
> byte-identical to a real cutoff apart from the setpoint. A run-time limit therefore does not
> close an outlet — **it ends the experience**, which is why a preset-driven session loses
> every zone the preset was driving while a direct session loses only the zone that fired.
>
> Practical consequence: `0x40` **plus** a preset id dropping to `0` is an *ended preset*.
> `0x40` alone, with the preset id already `0`, is just somebody pressing pause. Full evidence
> in [`api.md`](api.md#-important--actionoff-pauses-and-clears-the-active-preset).
>
> **One exception to reading the id at all: warm-up.** A preset activated while the valve is
> warming up applies its word but never sets `presetOrExperienceId`, so a preset-driven
> session can run with the id at `0` throughout. Every `warmUpInProgress` sample in the
> corpus carries `0`. See
> [api.md](api.md#-important--a-preset-activated-during-warm-up-never-latches).

> ### ⚠️ The flow byte is only meaningful while an outlet is open
>
> Read it on an idle valve and it is **not** the commanded flow. Across the corpus, 296 words
> with no outlet open carry a flow other than 100%, in recurring pairs — `01844700`/`11849B00`
> (35.5% / 77.5%) and `01844500`/`1184A500` (34.5% / 82.5%) — and `totalFlow` collapses to `2`
> in the same message before returning to its previous value seconds later.
>
> ```text
> 19:18:06  017fc800 / 117fc800   totalFlow=1656   water off
> 19:20:05  01844500 / 1184a500   totalFlow=2      <- 34.5% / 82.5%, nothing open
> 19:20:07  0184c800 / 1184c800   totalFlow=1653   back to 100%
> ```
>
> Seen on 2026-08-07, 08-11 and 08-14, so it is a recurring frame rather than corruption. The
> mechanism is **not established** — stored per-outlet defaults and a standby snapshot both
> fit. What is established is the consequence: anything reporting "the flow setting" must gate
> on an outlet actually being open, or it will show a number nobody chose.
>
> By contrast, while water *is* flowing the byte is stable and trustworthy: 579 of the 757
> flowing words read exactly 100%, and every exception falls in the pre-2026-08-13 window when
> the touchscreen was still hijacking flow (see [`api.md`](api.md)).

> ### ⚠️ IMPORTANT — `maximumRunTime` is reported per outlet but **timed per zone**
>
> The valve reports `maximumRunTime` in `READ_GCS_OUTLET_CONFIG_CFG`, one message per outlet,
> which reads as a per-outlet limit. **It is not.** Measured over 156 completed zone-open
> periods across the whole capture corpus:
>
> * The clock starts when a zone goes from *nothing flowing* to *something flowing*.
> * It **does not reset when the outlet mask changes within that zone** — opening a second
>   head, closing the first, swapping between them, none of it touches the timer.
> * At the limit, the valve writes `0x40` to that zone and clears its mask.
>
> All 11 cutoffs in the corpus land within **1.32 s** of the limit measured from *zone* start.
> Measured from each outlet's own opening, only 8 of them land anywhere near it — the other
> three had no single outlet open for the full duration.
>
> ```
> 2026-08-14 01:52:00  zone 1 cut after 900.0 s of zone flow
>   its outlets, individually:  outlet 1 = 189 s   outlet 3 = 520 s
> ```
>
> An integration that re-opens outlets after a cutoff must therefore time zones, not outlets.
> This one did the latter until 2026-08-14 and missed 3 of the owner's 4 cutoffs in the
> session that exposed it — every one where they moved between shower heads mid-shower.
>
> **Which limit applies to a zone whose outlets disagree is unknown.** All six outlets read
> the same value on the reference install (900 s now, 3600 s before reconfiguration), so
> nothing distinguishes "the zone's limit", "the limit of whichever outlet opened the zone",
> and "a system-wide value stored per outlet". The integration matches against any distinct
> value configured in the zone; see `anthem_plus/runtime_cutoff.py`.

> Treating `0x40` as a whole-mask sentinel makes `0x41` unrepresentable and misreads a
> paused-with-assignment valve as *running*. Anything answering "is this outlet on" must
> clear the assignment while paused; anything answering "what will it resume to" must not.
>
> The library's `ValveMode` enum misread both halves of this byte: `0x01` as a "SHOWER" mode
> (it is the outlet-1 bit) and `0x40` as "preset-mode" (it is the pause flag).

```python
# decode: outlet N (1-6) is on
valve_code = valve1_code if number <= 3 else valve2_code
mask = int(valve_code[6:8], 16) & 0x07
is_on = bool(mask >> ((number - 1) % 3) & 1)

# encode
mask = (1 if outlet_a else 0) | (2 if outlet_b else 0) | (4 if outlet_c else 0)
```

STOP and PAUSE are indistinguishable from the outlet bits alone — check
`byte3 & 0x40` if an automation needs to tell a paused session from a stopped
one. `mqtt_capture.py` exposes this as `valve1_paused` / `valve2_paused` in the
state document.

### Do not read byte 3 as a mode enum

The `kohler-anthem` library treats this byte as a `ValveMode` enum — `0x00`
OFF, `0x01` SHOWER, `0x40` STOP — and `custom_components/kohler/helpers.py`
follows it. That model only *looks* right because `0x01` means outlet 1; it
cannot represent `0x02`–`0x07`, all of which occur in normal use.

The concrete consequence: `build_preset_valve_control()` keeps the preset's
temp and flow bytes but hardcodes `ValveMode.SHOWER` as the last byte,
discarding the preset's own outlet mask. Starting the "Default shower" preset
(`Valve1="018448"`, `Valve2="05849c"` — masks `01` and `05`) through the
integration would run outlet 1 only, and nothing on valve 2.

## Presets pack outlets into byte 0, at different bit positions

**Corrected twice.** A preset's `hexString` is `[byte0][temp low][flow]`, where byte 0
carries the temperature high bit **and** the outlet flags — but at different positions from
a command word:

```text
preset  byte0:  0x04 outlet1   0x08 outlet2   0x10 outlet3   0x01 temp high bit
command byte3:  0x01 outlet1   0x02 outlet2   0x04 outlet3
```

There is no valve-index nibble in a preset; the valve is identified by field position.

| Preset | Valve | `hexString` | byte 0 | decodes to | `outlets[].value` |
|---|---|---|---|---|---|
| Default shower | Valve1 | `018448` | `01` | none, 38.8 °C | `[0,0,0]` ✅ |
| Default shower | Valve2 | `05849c` | `05` | outlet 1, 38.8 °C | `[1,0,0]` ✅ |
| Test favourite | Valve1 | `1190c8` | `11` | outlet 3, 40.0 °C | `[0,0,1]` ✅ |
| Test favourite | Valve2 | `0589c8` | `05` | outlet 1, 39.3 °C | `[1,0,0]` ✅ |

All four match, and all four re-encode byte-exact.

> **Two earlier readings were wrong.** The first claimed `[mask][temp][flow]` with the mask
> leading. The second — written the same day — concluded presets carried *no* mask, because
> it tested the **command word's** bit positions (`0x01/0x02/0x04`) against preset bytes.
> The mask was there all along, three bits to the left.

The superseded table, kept so the mistake is not repeated:

| Preset | Valve | `hexString` | byte 0 | `outlets[].value` | mask would need |
|---|---|---|---|---|---|
| Default shower | Valve1 | `018448` | `01` | `[0,0,0]` | `00` |
| Default shower | Valve2 | `05849c` | `05` | `[1,0,0]` | `01` |
| Test favourite | Valve1 | `1190c8` | `11` | `[0,0,1]` | `04` |
| Test favourite | Valve2 | `0589c8` | `05` | `[1,0,0]` | `01` |

**Outlets live in the separate `outlets` array**, which also carries plain, unpacked values
for temperature (Celsius) and flow (the native 0–50 scale):

```json
{ "valveIndex": "Valve2", "hexString": "0589c8",
  "outlets": [ {"outletIndex":"outlet1","value":"1","temperature":"39.3","flow":"50"},
               {"outletIndex":"outlet2","value":"0", …},
               {"outletIndex":"outlet3","value":"0", …} ] }
```

So converting a preset to a command means building the mask from `outlets[].value` and
taking temperature and flow from the same array — the `hexString` is only a fallback.

This also confirms the flow scale a third time: `0x48`=72 → 18, `0x9C`=156 → 39,
`0xC8`=200 → 50, all byte ÷ 4.

### Two open questions about the measurement half

**Where does `atTemp` come from, if not from a reported measurement?**
The tested valve asserts `atTemp` reliably (99 of 239 open-outlet messages) while reporting
zero for measured temperature. So the comparison happens somewhere we cannot see — most
likely a hardware-level sensor whose value is simply not surfaced in the status word. That
would make `atTemp` the *only* usable "water is ready" signal on such a unit, which is a good
reason to expose it as an entity even though the underlying temperature is invisible.

**Does ice-shower mode produce genuinely low measured temperatures?**
Anthem Plus exposes `iceShowerExperiences` (e.g. "Beginner Ice Shower"), and the encoding
represents sub-25.6 °C without difficulty. If an ice session is captured on a unit that
*does* populate measurements, expect byte 4 to be `0x00` and byte 5 to carry the whole value
— the same shape as the two anomalous `0000C800` / `1000C800` words in the current captures,
which under the corrected model decode to 0.0 °C rather than 25.6 °C.

Worth noting those two words may therefore be a genuine cold reading rather than the device
reset they were assumed to be. Nothing in the captures settles it.

### Reading presets

```text
REST   GET /devices/api/v1/device-management/gcs-preset/{device_id}
       → { deviceId, sku, tenantId, createdTime, gcsPresetExperienceDetails: [ … ] }
MQTT   GCS_PRESET_STS — one preset per message
```

Each entry carries `presetId`, `title`, `isExperience`, `state`, `time`, `pauseFlag`, and
`valveDetails`. Experiences have no usable valve data and cannot be started this way.

### A preset's stored flow may not be the flow it runs at

The Konnect app states that a favourite created in the app **runs at maximum flow (50)**,
regardless of what its `valveDetails` store. The "Default shower" preset is app-configured
and stores flow `39` (`0x9C`, 78%), yet runs at 50.

This matters when converting a preset to a command: reproducing the stored flow gives 78%
where the app would give 100%. Anything starting a preset has to choose whether to match
the app's behaviour (force max flow) or the stored value. Neither is obviously right —
a preset created on the **touchscreen** may well store a flow it genuinely honours.

### Temperature round-tripping is not exact for every input

Setting a preset to 104 °F stored `0x90` → 40.0 °C → exactly 104.0 °F. Setting 103 °F
stored `0x89` → 39.3 °C → 102.74 °F, about 0.3 °F low. The byte's 0.1 °C resolution cannot
land on 103 °F exactly — the closest is `0x8A` (102.92 °F) — but the app chose a value one
step further away still.

**Partly explained, 2026-08-17.** The app does not compute Fahrenheit at all — it looks it up
in `h.z()` (see the Fahrenheit-ladder section above), which is why its values never land on
the arithmetic answer. The ladder gives 103 °F → `0x18A` (394), while this preset held
`0x189` (393); both display as 103 under `h.j()`, so the *preset* write path still uses
something other than a straight `z()` lookup. Small, and still in the app's write path rather
than in this decode.

## Worked examples

Decode, from the capture at `2026-08-10T20:47:53`:

```text
primaryValve1   = 0184C807  → valve1: 38.8 °C (102 °F), 100%, outlets 1+2+3
secondaryValve1 = 1184C803  → valve2: 38.8 °C (102 °F), 100%, outlets 4+5
```

The HUB's `SHOWER_VALVE_STS` for the same moment reported `[1,1,1,0,0,0]` and
`[1,1,0,0,0,0]` at 102 °F / 100% on both zones.

Encode, "outlets 1 and 3 at 104 °F and full flow":

```text
104 °F → 40.0 °C → (40.0 - 25.6) * 10 = 144 = 0x90
100%   → 0xC8
1 + 4  → 0x05
result → 0190C805
```

## Superseded readings

Both of these came from the Konnect 3.0.1 decompile and were carried in the older
`GCS_NOTES.md`. Both are **wrong**; they are recorded here so the same guesses are not
re-derived from the app source later.

### Temperature: `°C = 15 + byte × 0.146`

Superseded by `°C = 25.6 + byte / 10`. The old formula **fails its own worked examples**:

| Byte | Old formula | New formula | The note's own claim |
|---|---|---|---|
| `0x79` (121) | 32.7 °C = **90.8 °F** | 37.7 °C = **99.9 °F** | "≈100 °F" ✓ new |
| `0x9B` (155) | 37.6 °C = **99.7 °F** | 41.1 °C = **106.0 °F** | "≈106 °F" ✓ new |

The old constant is back-fitted from the `kohler-anthem` library's claimed 15–49 °C range
spread across `0x00`–`0xE8`: (49 − 15) / 232 = 0.1466. It was never checked against a
capture. The example values beside it were real observations, which is why they match the
capture-derived formula and not the formula they were printed next to.

### Byte 3: a `ValveMode` enum

Superseded by the outlet mask above. The old reading was
`00`=off, `01`=on/shower, `02`=tub, `40`=preset-mode.

It only *looks* right because outlet 1 is the showerhead and outlet 2 is the tub filler, so
the single-outlet masks `0x01` and `0x02` coincide with app-side labels named "shower" and
"tub". The enum cannot represent `0x03`–`0x07`, all of which occur in normal use and all of
which decode correctly as masks (26 distinct mask→outlet pairings confirmed below).

`0x40` is **PAUSE**, not "preset-mode" — a paused session reports it with every outlet bit
clear, and it is how you tell PAUSE from STOP.

The app may genuinely define such an enum internally; that is a fact about the app's source,
not about the wire format. This misreading is the direct cause of the
`build_preset_valve_control()` bug noted above.

## Verification

Derived and checked against 315 `GCS_SOLO_STS` messages across the 18 raw
capture logs in `log/`, correlated with the HUB's `SHOWER_VALVE_STS`:

| Field | Result |
|---|---|
| Outlet mask | 26 distinct mask→outlet pairings, all matching |
| Temperature | 135 / 136 valve-ON samples within rounding |
| Flow | 136 / 136 valve-ON samples exact |

Every exception is the **HUB lagging the GCS word by 0.3–2 seconds** and
briefly reporting the pre-transition state, never a decode error. This lag is
why the GCS valve word, not `SHOWER_VALVE_STS`, is the right source for outlet
state.

Masks not present in the captures — valve1 `02`, valve2 `04`–`07` — follow from
the bit rule and from the Home Assistant encoder, but are not independently
confirmed by capture data.

## Outlet inventory

`READ_GCS_OUTLET_CONFIG_CFG` enumerates the installed outlets. This system
reports six, zero-indexed, all with `outLetFlags: 1`:

| `outLetId` | HA outlet | `outLetType` |
|---|---|---|
| 0 | 1 | 62 |
| 1 | 2 | 52 |
| 2 | 3 | 1 |
| 3 | 4 | 11 |
| 4 | 5 | 39 |
| 5 | 6 | 21 |

Shared limits across all six: `minimumOutletTemperature` 150, `default` 388,
`maximum` 450 (tenths of °C), flow 16–200, `maximumRunTime` 3600 s.
