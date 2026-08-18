# Case study 4 — the two touchscreens, and what "off" actually means

**2026-08-18, 14:59:39 – 15:05:24 local. Exploratory rather than designed: a shower opened
from Home Assistant's outlet switches, then driven from both physical control surfaces in
turn, then turned off from the first-generation screen.**

**Two of its findings are things nothing in this project had ever measured.**

> ### ⚠️ MQTT is the Konnect app's UI channel — not device communication
>
> Every observation below is from MQTT, and **MQTT is not how the valve and the controller
> talk to each other.** The integration registers a client identity on Kohler's IoT Hub and
> the cloud invokes direct methods *on us*: we are an app instance, and the payloads say what
> the app should **render**. The real device-to-device link is the **RJ wired connection**
> between the controller and the valve, and **we cannot sniff it** — nothing here observes it.
>
> So "the HUB reported X" means "the cloud told app clients to render X", and **absence of a
> message means there was no card change to push — not that a device was silent or broken.**
> Conclusions about what a device *knew* rest on its **behaviour** (a timer firing, water
> moving), never on messages alone. Read [`intro.md`](intro.md) §1 before this document.

> **The headline.** Pressing **off on the first-generation touchscreen writes `0x40` — a
> pause, not a stop** — on both zones. That pause then **self-terminates into `0x00` after
> ~2 minutes**, resetting the setpoint to the configured default. Separately, the controller
> acknowledged a Home-Assistant-driven open in **285 ms**, which falsifies the mechanism
> [case study 1](01_ha_driven_shower_hub_blind.md) proposed for its silence — though not that
> case study's conclusion. See §8.

---

## 1. Configuration at the time

| Setting | Value | Note |
|---|---|---|
| GCS `maximumRunTime` | **900 s = 15 min** | `limits":[900]` on every journal event |
| HUB max shower duration | 15 min (unchanged from [case study 3](03_both_ceilings_at_15_minutes.md)) | **not exercised** — the session ran 224 s |
| Endless Shower | enabled | did not fire; nothing matched a limit |
| Start route | **Home Assistant outlet switches** → `solowritesystem` | no preset, no `valveOnOff` |

## 2. What was done, in order

| # | Local time | Action | Surface |
|---|---|---|---|
| 1 | 14:59:39 | zone 2 outlet 1 ON | **Home Assistant** switch |
| 2 | 14:59:53 | zone 1 outlet 3 ON | **Home Assistant** switch |
| 3 | 15:01:43–15:02:14 | 102 → 107 °F, then → 100 °F | **Anthem Plus touchscreen** |
| 4 | 15:02:35–15:02:59 | 100 → 107 °F, then → 100 °F | **first-generation touchscreen** |
| 5 | 15:03:23 | **OFF** | **first-generation touchscreen** |
| 6 | 15:05:23 | pause expires into a stop | **the controller, unprompted** |

Actions 1–5 are owner-reported; 6 is owner-confirmed as a built-in controller behaviour.

## 3. The complete capture

`/config/kohler_anthem_plus_raw/mqtt_raw_20260818T201525Z_72_d536f3df.jsonl`. Complete records
verbatim in [Appendix A](#appendix-a--every-raw-record-of-the-session).

```text
local           who  message
14:59:39.469    GCS  v1=0184C800 m=0x00        | v2=1184C801 m=0x01    HA opens zone 2 outlet 1
14:59:39.754    HUB  z1=OFF  z2=ON:100000 T=102                        +0.285 s  ⬅ ACKNOWLEDGED
14:59:40.256    GCS  v1=0584C800 atTemp        | v2=1184C801           +0.502 s
14:59:53.301    GCS  v1=0584C804 m=0x04 atTemp | v2=1184C801           HA opens zone 1 outlet 3
14:59:53.534    HUB  z1=ON:001000 z2=ON:100000 T=102                   +0.233 s  ⬅ AGAIN
              ──────── Anthem Plus touchscreen: 102 -> 107 -> 100 ────────
15:01:43.846    GCS  388(102F) -> 405(105F)                            3 messages up, 0.837 s
15:02:09.853    GCS  416(107F) -> ... -> 377(100F)                     5 messages down, 3.953 s
              ──────── first-gen touchscreen: 100 -> 107 -> 100 ────────
15:02:35.149    GCS  377(100F) -> ... -> 416(107F)                     7 messages up, 2.316 s
15:02:57.092    GCS  416(107F) -> ... -> 377(100F)                     7 messages down, 2.328 s
              ──────────────────────────────────────────────────────────
15:03:23.930    GCS  v1=0579C840 PAUSE | v2=1179C840 PAUSE   ⬅ FIRST-GEN "OFF" = 0x40, BOTH ZONES
15:03:24.375    HUB  z1=OFF z2=OFF
15:03:24.804    GCS  v1=0579C840 PAUSE | v2=1179C840 PAUSE             repeat
15:05:23.120    GCS  v1=0584C840 PAUSE | v2=1184C840 PAUSE   ⬅ +119.19 s, setpoint reset to 102
15:05:23.619    HUB  z1=OFF z2=OFF
15:05:24.103    GCS  v1=0584C800       | v2=1184C840 PAUSE             zone 1 pause clears
15:05:24.213    GCS  v1=0184C800       | v2=1184C800                   zone 2 clears, atTemp clears
```

Flow `0xC8` (200) = 100% throughout. Masks: `0x01` (1) = zone 2 outlet 1 (global outlet 4),
`0x04` (4) = zone 1 outlet 3, `0x40` = pause flag.

## 4. ⭐ The first-generation touchscreen's OFF is a PAUSE

```text
15:03:23.930   v1=0579C840   v2=1179C840      both zones: mask cleared, 0x40 set
```

**A person pressing off on that screen writes `0x40`, not `0x00`** — and on **both zones at
once**, unlike the valve's own `maximumRunTime` expiry, which pauses only the zone that timed
out ([case study 3](03_both_ceilings_at_15_minutes.md) §4).

The detector correctly declined it:

```json
{"event":"flow_end","zone":1,"duration":210.63,"limits":[900],"paused":true,"verdict":"ignored","off_by":689.37}
{"event":"flow_end","zone":2,"duration":224.46,"limits":[900],"paused":true,"verdict":"ignored","off_by":675.54}
```

⚠️ **But only because the timing missed.** Zone 2 had been flowing 224.46 s against a 900 s
limit. **Had this shower been running ~15 minutes when that button was pressed, Endless Shower
would have restarted the water.** This is the first time the corpus has captured the exact
trigger for the cost session 9 accepted when it removed the pause-flag veto — a deliberate
trade, documented in [`runtime_cutoff.py`](../../anthem_plus/runtime_cutoff.py), and now with
a concrete real-world path to it rather than a hypothetical one.

Both zones carrying `0x40` also means a first-gen OFF is **indistinguishable from a
preset-driven cutoff** on the wire, which is the other case that pauses every zone at once.

## 5. ⭐ A pause self-terminates after ~2 minutes

```text
15:03:23.930   0579C840 / 1179C840   PAUSE, setpoint 377 (100 °F)
15:05:23.120   0584C840 / 1184C840   PAUSE, setpoint 388 (102 °F)   +119.19 s
15:05:24.103   0584C800 / 1184C840   zone 1 pause clears
15:05:24.213   0184C800 / 1184C800   zone 2 clears, atTemp clears — session over
```

**119.19 s.** Owner-confirmed as a built-in controller behaviour: the Anthem Plus holds a
paused shower for two minutes, then ends it.

Two details worth keeping:

* **The setpoint reverts to the configured default** — `377` (100 °F) → `388` (102 °F), which
  is `zone1.defaultTemp` / `zone2.defaultTemp` = `"102"` from `get_valve_settings`
  ([case study 2](02_hub_commanded_shower_15min.md) §8). A setpoint returning to default is a
  session-end signature, not a temperature command.
* **The clear is split across two messages**, zone 1 at 15:05:24.103 and zone 2 110 ms later,
  rather than one atomic `00/00`.

**This is a fifth timer**, alongside the outlet `maximumRunTime`, the preset `time`, the HUB
max shower duration, and — out of scope — the ice-bath `coldwatertimeout`. It bounds how long
any restore window can ever be: a pause older than ~2 minutes no longer has a session to
resume into.

## 6. `atTemp` is inert across setpoint changes

Byte 0 held `0x05` — the `atTemp` bit set — from 14:59:40.256 straight through to the final
`00/00` at 15:05:24.213. Through **sixteen setpoint changes** spanning `377` (100 °F) to `416`
(107 °F), from both control surfaces, it never cleared once.

Since the valve publishes on change, a transient clear would have been captured; the same
capture resolves two words 0.245 s apart elsewhere. So the bit does not track "is the water at
the setpoint" in any moment-to-moment sense once it has been set.

This closes the line of enquiry session 9 §2c opened. `atTemp` was already ruled out as a
cause of the temperature drift by three independent arguments; this adds a fourth and simpler
one — **it does not move at all.**

## 7. The two touchscreens are not distinguishable on the wire

| surface | direction | messages | span | shape |
|---|---|---|---|---|
| Anthem Plus | 102 → 107 °F | 3 | 0.837 s | `388 → 405 → 411 → 416` |
| Anthem Plus | 107 → 100 °F | 5 | 3.953 s | `416 → 400 → 394 → 388 → 383 → 377` |
| first-gen | 100 → 107 °F | 7 | 2.316 s | every degree |
| first-gen | 107 → 100 °F | 7 | 2.328 s | every degree |

Same message shape from both: one word per intermediate value, both zones, no marker of
origin. The controller mirrored every step ~0.2–0.5 s behind, **including the first-gen
changes it did not command.**

⚠️ **The one apparent difference is not a discriminator.** The Anthem Plus jumped three
degrees on its first step in each direction (`388 → 405`, `416 → 400`) while the first-gen
stepped singly. That is consistent with **drag speed** — the panel covered 5 degrees in
0.837 s while the first-gen took 2.316 s for 7, and the valve only publishes values it
actually passes through. Session 9 §2b withdrew a similar lead for the same reason; do not
resurrect it on this evidence.

## 8. ⚠️ The controller acknowledged a Home-Assistant-driven open — in 285 ms

```text
14:59:39.469  GCS  v2=1184C801            HA opens zone 2 outlet 1 via solowritesystem
14:59:39.754  HUB  z2=ON:100000 T=102     +0.285 s
14:59:53.301  GCS  v1=0584C804            HA opens zone 1 outlet 3
14:59:53.534  HUB  z1=ON:001000           +0.233 s
```

No preset. No `valveOnOff`. No screen touched. **The controller saw both opens essentially
instantly, with correct outlet arrays.**

Corroborated 33 minutes later: at 15:38:59.126 the same switch was pressed again and the
controller acknowledged in **382 ms** (§10).

### What this changes, and what it does not

**It falsifies the mechanism case study 1 proposed.** That document argued the controller
"did not interpret the valve opening outlets as a shower having started". This session shows
it interprets exactly that, immediately, as a matter of routine.

**It does not change case study 1's conclusion.** That the controller did not know remains
solid, and rests on behaviour rather than messages: its 60-minute ceiling did not fire across
86 minutes, and [case study 3](03_both_ceilings_at_15_minutes.md) proves that ceiling is
enforced unconditionally when a session is known. Case study 1 §7 has been amended to narrow
its reasoning accordingly.

**What we do not know is why it sometimes sees and sometimes does not.** That is now the open
question, stated plainly rather than papered over.

### What the whole corpus says about it

Every capture ever taken — 89 files, 2026-08-07 → 08-18, 1411 `GCS_SOLO_STS`, 563
`SHOWER_VALVE_STS` — yields **130 GCS water-on episodes**. Restricting to the 95 where the
controller was demonstrably alive (published something within ±10 minutes):

| | saw the open (≤5 s) | caught up later | never saw it |
|---|---|---|---|
| **Preset active** | **0** | 2 | **13** |
| No preset | 51 | 10 | 19 |

* **The controller has never once reported `status: ON` at the moment a preset-driven session
  opens — 0 of 15.** Ten times it published nothing; **three times it published
  `status: OFF` while water was running**, within a second of the open. Two caught up ~32–36 s
  late.
* Plain `solowritesystem` opens are seen immediately **51 times out of 80**.
* Every one of the 12 late catch-ups followed a **mid-episode outlet mask change** within 3 s.
  Setpoint changes do **not** predict acknowledgement (38% blind with one, 32% without).
* Never-seen episodes are short and quiet — median **55 s** against **157 s** for seen ones.
* **29 of the 32 blind cases fall on 08-12/13/14**, the heavy-probing days around the factory
  reset. Since 08-15 there is exactly one, and it is preset-driven.

#### ❌ Long inactivity does NOT cause it — the opposite holds

A natural hypothesis is that the controller goes quiet or sleeps, and misses the first event
after a long idle stretch. **The corpus refutes it.** Blind rate by how long the *valve* had
been silent before the episode opened (valve activity is independent of the controller, so this
is not circular):

| quiet before the open | seen | blind | blind rate |
|---|---|---|---|
| < 1 min | 31 | 15 | 33% |
| **1–10 min** | 5 | 12 | **71%** |
| 10–60 min | 16 | 5 | 24% |
| 1–6 h | 5 | 0 | **0%** |
| > 6 h | 7 | 0 | **0%** |

**Every episode that followed more than an hour of quiet was seen — 12 for 12.** With preset
episodes removed, the pattern sharpens: 23% blind after < 1 min, **64% after 1–10 min**, 6%
after 10–60 min, and 0% beyond an hour.

Median quiet-before is **2.9 min for seen** episodes against **1.4 min for blind** ones — blind
episodes follow *shorter* gaps, not longer.

So the risk band is **recent prior activity**, not idleness. That fits the date concentration:
the blind cases cluster on days of rapid successive probing, where each open followed another a
few minutes earlier. Whether the controller is still settling from the previous transition, or
something else, is unmeasured.

⚠️ One near-circular figure to avoid quoting: measured against the last *HUB* message rather
than the last valve message, blind episodes show a longer preceding gap (6.4 min vs 2.2 min).
That is largely a restatement of the controller having been quiet, not evidence about cause.

⚠️ **`resolve_outlet_source()` is right to prefer the valve word, but its stated cause is
wrong.** Its docstring blames `solowritesystem`; the corpus says the categorical failure is
**presets**. A fuller cross-corpus write-up is still to be done.

## 9. What this session does NOT establish

* **Whether the controller counts a Home-Assistant-started session toward its ceiling.** The
  session ran 224 s against a 900 s limit. Untested, and still the most consequential unknown.
* **Whether water physically flowed on zone 2 alone.** The owner reports the shower did not
  start until zone 1 outlet 3 was opened 13.8 s later, on this session and on the 15:38:59
  retry. Nothing on the wire distinguishes "outlet commanded open" from "water arriving", so
  this is owner observation only and needs its own test.

## 10. Postscript — the 15:38:59 retry, and a Home Assistant non-event

At 15:36 the owner pressed the zone 2 outlet 1 switch and nothing happened. **Home Assistant
never registered the press**: the recorder shows no state change for any `anthem` entity
between 15:05:24.215 and 15:38:59, the integration logged nothing, and no `solowritesystem`
was sent. Not a device fault, and **not a code change** — no Core restart had occurred (no new
capture file, no restart marker, continuous log, same PID since 13:15).

The retry at 15:38:59 worked normally and is **not** part of this case study:

```text
15:38:59.126  GCS  v1=0184C800 | v2=1184C801     HA opens zone 2 outlet 1
15:38:59.508  HUB  z1=OFF  z2=ON:100000          +0.382 s
15:38:59.984  GCS  v1=0584C800 | v2=1184C801     atTemp
15:39:40.457  GCS  v1=0184C800 | v2=1184C800     closed, 41.3 s
15:39:40.981  HUB  z1=OFF  z2=OFF
```

Quoted here only because it is a third independent instance of the controller acknowledging a
`solowritesystem` open.

## 11. Open

1. **Why does the controller sometimes see an HA-driven open and sometimes not?** The
   headline unknown. Presets explain the categorical cases; they do not explain case study 1.
2. **Does `warmupmode: "pause"` produce a `0x40`?** Still unexercised across four sessions.
3. **Does a first-gen OFF at ~15 minutes get restarted by Endless Shower?** Predicted yes by
   §4. Deliberately not tested — it would run water unattended.
4. **Is the ~2-minute pause expiry exactly 120 s?** One measurement, 119.19 s.
5. Carried: whether the controller counts an HA-started session (§9); whether a GCS preset
   starts its clock.

## 12. Provenance

| Fact | Source |
|---|---|
| Every hex word, timestamp, message count | `mqtt_raw_20260818T201525Z_72_d536f3df.jsonl` — read in full |
| Cutoff verdicts and durations | `cutoff_20260818T201525Z_72_b69de911.jsonl` — read in full |
| GCS `maximumRunTime` = 900 s | `limits":[900]` on every journal event |
| Which surface did what, and when | **owner-reported** |
| The ~2-minute pause expiry being a device feature | **owner-confirmed** |
| Home Assistant never registering the 15:36 press | `home-assistant_v2.db` recorder, read-only query |
| The 130-episode corpus figures | all 89 capture files, scripted analysis |

---

## Appendix A — every raw record of the session

**Window: 2026-08-18 21:36:08.449Z → 22:05:24.214Z** (14:36:08 → 15:05:24 local) — from the
last message of [case study 3](03_both_ceilings_at_15_minutes.md) to the last message of this
one, so the appendices abut without overlapping.

> ⛔ **Hard-capped at this session's final message.** The 15:38:59 retry (§10) falls outside
> and is quoted there instead. Nothing after 22:05:24.214Z belongs to this case study.

The 23 minutes between case study 3 and this session contain **no records at all** — the valve
publishes only on change, and nothing changed.

### A.1 — raw MQTT, verbatim (61 records)

Lines exactly as written by `RawLog.write()`, with **one substitution**: the real `tenantid`
is replaced by `<TENANT_ID>` per the placeholder policy in [`../README.md`](../README.md).
Device ids are left in place. Nothing else is altered.

Source file for all of them: `mqtt_raw_20260818T201525Z_72_d536f3df.jsonl`.

**14:59:39.469 local** — line 54 — GCS — v1=0184C800 v2=1184C801

```json
{"ts":"2026-08-18T21:59:39.469201Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=54","qos":0,"retain":false,"payload":"{\"messageid\":\"482C0C83-6ABF-8E84-9E15-48ADABB10C56\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090390\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"25955\",\"totalVolume\":\"807549474\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:59:39.754 local** — line 55 — HUB — z1=OFF z2=ON

```json
{"ts":"2026-08-18T21:59:39.754079Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=55","qos":0,"retain":false,"payload":"{\"messageid\":\"704b684d-bc71-49e6-855f-e027a53f36d3\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090379\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**14:59:40.256 local** — line 56 — GCS — v1=0584C800 v2=1184C801

```json
{"ts":"2026-08-18T21:59:40.256089Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=56","qos":0,"retain":false,"payload":"{\"messageid\":\"F3D9D211-814C-3EA4-80B6-1E659BCD1DBC\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090391\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1657\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:59:53.301 local** — line 57 — GCS — v1=0584C804 v2=1184C801

```json
{"ts":"2026-08-18T21:59:53.301895Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=57","qos":0,"retain":false,"payload":"{\"messageid\":\"29EF1DF3-D6F1-D2D4-BB79-52A2F88A4AF6\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090404\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"12343\",\"totalVolume\":\"1629633058\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:59:53.534 local** — line 58 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T21:59:53.534941Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=58","qos":0,"retain":false,"payload":"{\"messageid\":\"a4c5a07d-c7ff-47da-8aea-03cd3acf5d65\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090393\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:01:43.846 local** — line 59 — GCS — v1=0595C804 v2=1195C801

```json
{"ts":"2026-08-18T22:01:43.846586Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=59","qos":0,"retain":false,"payload":"{\"messageid\":\"B8FF2E2C-F63A-E444-ADD6-064639AC9042\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090515\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1658\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"0595c80400000001\",\"secondaryValve1\":\"1195c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:01:44.245 local** — line 60 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:01:44.245079Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=60","qos":0,"retain":false,"payload":"{\"messageid\":\"263cf945-1433-409d-9cd6-974502ba335b\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090503\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":105,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":105,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:01:44.360 local** — line 61 — GCS — v1=059BC804 v2=119BC801

```json
{"ts":"2026-08-18T22:01:44.360958Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=61","qos":0,"retain":false,"payload":"{\"messageid\":\"465494C6-C1EE-C764-B4DF-67580D0D37A1\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090515\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"059bc80400000001\",\"secondaryValve1\":\"119bc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:01:44.670 local** — line 62 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:01:44.670503Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=62","qos":0,"retain":false,"payload":"{\"messageid\":\"d2916a5c-27c7-43b8-9b4f-591d4fbac685\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090504\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":106,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":106,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:01:44.683 local** — line 63 — GCS — v1=05A0C804 v2=11A0C801

```json
{"ts":"2026-08-18T22:01:44.683553Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=63","qos":0,"retain":false,"payload":"{\"messageid\":\"E5B54036-11E0-DAB4-9939-955C953EE0E7\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090516\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"05a0c80400000001\",\"secondaryValve1\":\"11a0c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:01:45.125 local** — line 64 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:01:45.125387Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=64","qos":0,"retain":false,"payload":"{\"messageid\":\"291644b1-9c5d-45a2-adea-9f6094d1cea0\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090504\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":107,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":107,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:09.853 local** — line 65 — GCS — v1=0590C804 v2=1190C801

```json
{"ts":"2026-08-18T22:02:09.853308Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=65","qos":0,"retain":false,"payload":"{\"messageid\":\"4E3059A0-76D2-4414-A655-EC50D76BC580\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090541\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0590c80400000001\",\"secondaryValve1\":\"1190c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:10.261 local** — line 66 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:10.261855Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=66","qos":0,"retain":false,"payload":"{\"messageid\":\"164aaeb6-16bd-4f55-b65d-d03c90acf6dc\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090529\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":104,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":104,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:10.513 local** — line 67 — GCS — v1=058AC804 v2=118AC801

```json
{"ts":"2026-08-18T22:02:10.513200Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=67","qos":0,"retain":false,"payload":"{\"messageid\":\"F4D8AA30-66BB-F1D4-A30F-D205EDC5BE7E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090541\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"058ac80400000001\",\"secondaryValve1\":\"118ac80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:10.821 local** — line 68 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:10.821640Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=68","qos":0,"retain":false,"payload":"{\"messageid\":\"893e0250-73c8-4f19-8a08-0de5d5f36147\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090530\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":103,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":103,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:11.711 local** — line 69 — GCS — v1=0584C804 v2=118AC801

```json
{"ts":"2026-08-18T22:02:11.711167Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=69","qos":0,"retain":false,"payload":"{\"messageid\":\"0B8018AF-CB35-9B74-9B36-5CD71790824B\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090543\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"118ac80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:11.818 local** — line 70 — GCS — v1=0584C804 v2=1184C801

```json
{"ts":"2026-08-18T22:02:11.818617Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=70","qos":0,"retain":false,"payload":"{\"messageid\":\"DE90398B-BB45-31F4-B661-2DB319D079C3\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090543\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:12.263 local** — line 71 — GCS — v1=057FC804 v2=117FC801

```json
{"ts":"2026-08-18T22:02:12.263539Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=71","qos":0,"retain":false,"payload":"{\"messageid\":\"5E9490A6-88A2-C384-9BBA-8A0B219212A5\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090543\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"057fc80400000001\",\"secondaryValve1\":\"117fc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:12.320 local** — line 72 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:12.320465Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=72","qos":0,"retain":false,"payload":"{\"messageid\":\"3852ed2f-4a3c-4706-842c-053bedce5f4b\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090531\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:12.542 local** — line 73 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:12.542283Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=73","qos":0,"retain":false,"payload":"{\"messageid\":\"874a893a-6cfd-4fb8-9452-b3bb1ac1968e\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090532\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:13.806 local** — line 74 — GCS — v1=0579C804 v2=1179C801

```json
{"ts":"2026-08-18T22:02:13.806173Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=74","qos":0,"retain":false,"payload":"{\"messageid\":\"4A4093F4-E2B5-7804-9A3D-CB793072A3CD\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090545\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c80400000001\",\"secondaryValve1\":\"1179c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:14.283 local** — line 75 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:14.283914Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=75","qos":0,"retain":false,"payload":"{\"messageid\":\"8fcad693-c430-4861-b246-157822b03791\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090533\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:35.149 local** — line 76 — GCS — v1=057FC804 v2=117FC801

```json
{"ts":"2026-08-18T22:02:35.149986Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=76","qos":0,"retain":false,"payload":"{\"messageid\":\"B10AE378-F0AF-8044-BF10-FEF90D3A7BB5\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090566\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"057fc80400000001\",\"secondaryValve1\":\"117fc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:35.277 local** — line 77 — GCS — v1=0584C804 v2=117FC801

```json
{"ts":"2026-08-18T22:02:35.277947Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=77","qos":0,"retain":false,"payload":"{\"messageid\":\"A3E8D92E-BE0A-3704-9097-C309E12B4D36\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090566\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"117fc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:35.369 local** — line 78 — GCS — v1=0584C804 v2=1184C801

```json
{"ts":"2026-08-18T22:02:35.369005Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=78","qos":0,"retain":false,"payload":"{\"messageid\":\"ECEDCFFD-189C-FA74-9201-9FB17385DFB6\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090566\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929096\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:35.556 local** — line 79 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:35.556838Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=79","qos":0,"retain":false,"payload":"{\"messageid\":\"0ce31105-ddf1-400e-b7ff-3da7fd1e0e8a\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090555\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:35.610 local** — line 80 — GCS — v1=058AC804 v2=118AC801

```json
{"ts":"2026-08-18T22:02:35.610273Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=80","qos":0,"retain":false,"payload":"{\"messageid\":\"6679D2FC-FF72-6F74-8D9E-125219A34F9E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090567\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930944\",\"primaryValve1\":\"058ac80400000001\",\"secondaryValve1\":\"118ac80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:35.885 local** — line 81 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:35.885439Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=81","qos":0,"retain":false,"payload":"{\"messageid\":\"3e3ccd91-3f56-4061-9388-ab5ddfce9a8f\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090555\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":103,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":103,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:35.933 local** — line 82 — GCS — v1=0590C804 v2=1190C801

```json
{"ts":"2026-08-18T22:02:35.933926Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=82","qos":0,"retain":false,"payload":"{\"messageid\":\"4E495AA9-0F42-2674-9B6F-4A299B940FF9\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090567\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"0590c80400000001\",\"secondaryValve1\":\"1190c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:36.265 local** — line 83 — GCS — v1=0595C804 v2=1190C801

```json
{"ts":"2026-08-18T22:02:36.265454Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=83","qos":0,"retain":false,"payload":"{\"messageid\":\"E4ADB7B8-7953-EF64-8595-86E5FBF069DC\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090567\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0595c80400000001\",\"secondaryValve1\":\"1190c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:36.324 local** — line 84 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:36.324933Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=84","qos":0,"retain":false,"payload":"{\"messageid\":\"228be163-4216-43b1-a09d-ff2c030d981b\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090555\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":104,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":104,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:36.478 local** — line 85 — GCS — v1=0595C804 v2=1195C801

```json
{"ts":"2026-08-18T22:02:36.478513Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=85","qos":0,"retain":false,"payload":"{\"messageid\":\"5E42A70F-9892-2E34-8804-D4C1C50AB0AE\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090567\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0595c80400000001\",\"secondaryValve1\":\"1195c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:36.696 local** — line 86 — GCS — v1=059BC804 v2=1195C801

```json
{"ts":"2026-08-18T22:02:36.696540Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=86","qos":0,"retain":false,"payload":"{\"messageid\":\"87F8DE31-2AEE-3AD4-933D-1370F6B5323E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090568\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929096\",\"primaryValve1\":\"059bc80400000001\",\"secondaryValve1\":\"1195c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:36.768 local** — line 87 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:36.768917Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=87","qos":0,"retain":false,"payload":"{\"messageid\":\"283b23bb-72c3-4987-897e-8acbeba4701c\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090556\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":105,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":104,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:36.836 local** — line 88 — GCS — v1=059BC804 v2=119BC801

```json
{"ts":"2026-08-18T22:02:36.836591Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=88","qos":0,"retain":false,"payload":"{\"messageid\":\"69FAB080-5FDC-2AB4-BF70-D4D5D31746B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090568\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930944\",\"primaryValve1\":\"059bc80400000001\",\"secondaryValve1\":\"119bc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:37.075 local** — line 89 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:37.075131Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=89","qos":0,"retain":false,"payload":"{\"messageid\":\"e82133e8-2237-453a-ae94-a0129b6d3407\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090556\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":106,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":106,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:37.465 local** — line 90 — GCS — v1=05A0C804 v2=11A0C801

```json
{"ts":"2026-08-18T22:02:37.465220Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=90","qos":0,"retain":false,"payload":"{\"messageid\":\"EC95E5A8-48B6-C474-B245-0B83EB62D8CF\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090569\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"05a0c80400000001\",\"secondaryValve1\":\"11a0c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:37.971 local** — line 91 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:37.971088Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=91","qos":0,"retain":false,"payload":"{\"messageid\":\"2e8c39e9-ddec-453f-90e3-3f5766b77273\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090557\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":107,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":106,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:38.321 local** — line 92 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:38.321472Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=92","qos":0,"retain":false,"payload":"{\"messageid\":\"0f9981ee-05c3-4ac4-ba49-2d0924c06605\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090557\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":107,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":107,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:57.092 local** — line 93 — GCS — v1=059BC804 v2=119BC801

```json
{"ts":"2026-08-18T22:02:57.092716Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=93","qos":0,"retain":false,"payload":"{\"messageid\":\"F80B856C-6E34-06D4-9953-4BA9ADFC34B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090588\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"059bc80400000001\",\"secondaryValve1\":\"119bc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:57.311 local** — line 94 — GCS — v1=0595C804 v2=1195C801

```json
{"ts":"2026-08-18T22:02:57.311688Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=94","qos":0,"retain":false,"payload":"{\"messageid\":\"4430ACBA-83A7-3394-B5F8-D07AFB682C2A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090588\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0595c80400000001\",\"secondaryValve1\":\"1195c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:57.454 local** — line 95 — GCS — v1=0590C804 v2=1195C801

```json
{"ts":"2026-08-18T22:02:57.454095Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=95","qos":0,"retain":false,"payload":"{\"messageid\":\"168B6635-8380-63A4-9DD3-3FF4E692E177\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090589\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929096\",\"primaryValve1\":\"0590c80400000001\",\"secondaryValve1\":\"1195c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:57.661 local** — line 96 — GCS — v1=0590C804 v2=1190C801

```json
{"ts":"2026-08-18T22:02:57.661126Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=96","qos":0,"retain":false,"payload":"{\"messageid\":\"2D4EC44F-1297-7E94-B0CE-59FA0BA4D40A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090589\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929096\",\"primaryValve1\":\"0590c80400000001\",\"secondaryValve1\":\"1190c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:57.670 local** — line 97 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:57.670959Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=97","qos":0,"retain":false,"payload":"{\"messageid\":\"5acd071d-e613-44c8-b9f5-2ab2d2c6d28a\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090577\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":106,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":106,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:57.868 local** — line 98 — GCS — v1=058AC804 v2=118AC801

```json
{"ts":"2026-08-18T22:02:57.868995Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=98","qos":0,"retain":false,"payload":"{\"messageid\":\"8504309F-8525-38B4-A4BB-8255AF85CEEE\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090589\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929136\",\"primaryValve1\":\"058ac80400000001\",\"secondaryValve1\":\"118ac80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:57.886 local** — line 99 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:57.886300Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=99","qos":0,"retain":false,"payload":"{\"messageid\":\"568fadbd-696c-4af5-8d39-206b7520b65c\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090577\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":105,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":105,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:58.085 local** — line 100 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:58.085908Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=100","qos":0,"retain":false,"payload":"{\"messageid\":\"6f82adbe-2ebf-4e7b-b847-b236e61b638f\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090577\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":104,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":104,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:58.421 local** — line 101 — GCS — v1=0584C804 v2=1184C801

```json
{"ts":"2026-08-18T22:02:58.421059Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=101","qos":0,"retain":false,"payload":"{\"messageid\":\"482C0C83-6ABF-8E84-9E15-48ADABB10C56\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090589\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1\",\"totalVolume\":\"265146000\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:58.430 local** — line 102 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:58.430378Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=102","qos":0,"retain":false,"payload":"{\"messageid\":\"826a2a8e-fdcd-4e35-88fa-508b4577b61d\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090578\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":103,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":103,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:58.765 local** — line 103 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:58.765145Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=103","qos":0,"retain":false,"payload":"{\"messageid\":\"6c94cf3e-2846-4c77-92a2-7ab3ac3bc516\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090578\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:58.960 local** — line 104 — GCS — v1=057FC804 v2=117FC801

```json
{"ts":"2026-08-18T22:02:58.960997Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=104","qos":0,"retain":false,"payload":"{\"messageid\":\"F3D9D211-814C-3EA4-80B6-1E659BCD1DBC\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090590\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"057fc80400000001\",\"secondaryValve1\":\"117fc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:59.416 local** — line 105 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:59.416431Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=105","qos":0,"retain":false,"payload":"{\"messageid\":\"13d55367-d993-4565-a775-4b744f340d69\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090579\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:02:59.420 local** — line 106 — GCS — v1=0579C804 v2=1179C801

```json
{"ts":"2026-08-18T22:02:59.420209Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=106","qos":0,"retain":false,"payload":"{\"messageid\":\"29EF1DF3-D6F1-D2D4-BB79-52A2F88A4AF6\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090590\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"0579c80400000001\",\"secondaryValve1\":\"1179c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:02:59.851 local** — line 107 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:02:59.851850Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=107","qos":0,"retain":false,"payload":"{\"messageid\":\"d863f8f4-66b9-48f5-afd1-614eb45b36d3\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090579\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:03:23.930 local** — line 108 — GCS — v1=0579C840 v2=1179C840

```json
{"ts":"2026-08-18T22:03:23.930182Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=108","qos":0,"retain":false,"payload":"{\"messageid\":\"B8FF2E2C-F63A-E444-ADD6-064639AC9042\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090615\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c84000000001\",\"secondaryValve1\":\"1179c84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:03:24.375 local** — line 109 — HUB — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T22:03:24.375564Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=109","qos":0,"retain":false,"payload":"{\"messageid\":\"03fc484a-e6cb-45cd-b024-d96bda5f1ff0\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090604\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:03:24.804 local** — line 110 — GCS — v1=0579C840 v2=1179C840

```json
{"ts":"2026-08-18T22:03:24.804990Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=110","qos":0,"retain":false,"payload":"{\"messageid\":\"465494C6-C1EE-C764-B4DF-67580D0D37A1\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090616\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c84000000001\",\"secondaryValve1\":\"1179c84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:05:23.120 local** — line 111 — GCS — v1=0584C840 v2=1184C840

```json
{"ts":"2026-08-18T22:05:23.120569Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=111","qos":0,"retain":false,"payload":"{\"messageid\":\"E5B54036-11E0-DAB4-9939-955C953EE0E7\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090734\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0584c84000000001\",\"secondaryValve1\":\"1184c84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:05:23.619 local** — line 112 — HUB — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T22:05:23.619307Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=112","qos":0,"retain":false,"payload":"{\"messageid\":\"75712158-dac0-407a-a3a7-876470513a85\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787090723\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:05:24.103 local** — line 113 — GCS — v1=0584C800 v2=1184C840

```json
{"ts":"2026-08-18T22:05:24.103998Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=113","qos":0,"retain":false,"payload":"{\"messageid\":\"4E3059A0-76D2-4414-A655-EC50D76BC580\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090735\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:05:24.213 local** — line 114 — GCS — v1=0184C800 v2=1184C800

```json
{"ts":"2026-08-18T22:05:24.213573Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=114","qos":0,"retain":false,"payload":"{\"messageid\":\"F4D8AA30-66BB-F1D4-A30F-D205EDC5BE7E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787090735\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

### A.2 — cutoff journal, verbatim (48 records)

Source file: `cutoff_20260818T201525Z_72_b69de911.jsonl`. Almost all of these are `setting_change` — the journal records
every setpoint step from both touchscreens. The two `flow_end` entries at the bottom are the
first-generation screen's OFF, both `"paused":true`, both declined.

```json
{"ts":"2026-08-18T21:59:39.469719Z","event":"flow_start","zone":2,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:59:53.302369Z","event":"flow_start","zone":1,"mask":4,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:01:43.847090Z","event":"setting_change","zone":1,"mask":4,"flowing_for":110.54,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":104.9}
{"ts":"2026-08-18T22:01:43.847248Z","event":"setting_change","zone":2,"mask":1,"flowing_for":124.38,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":104.9}
{"ts":"2026-08-18T22:01:44.361472Z","event":"setting_change","zone":1,"mask":4,"flowing_for":111.06,"was_flow_percent":100.0,"was_temperature_f":104.9,"flow_percent":100.0,"temperature_f":106.0}
{"ts":"2026-08-18T22:01:44.361572Z","event":"setting_change","zone":2,"mask":1,"flowing_for":124.89,"was_flow_percent":100.0,"was_temperature_f":104.9,"flow_percent":100.0,"temperature_f":106.0}
{"ts":"2026-08-18T22:01:44.683987Z","event":"setting_change","zone":1,"mask":4,"flowing_for":111.38,"was_flow_percent":100.0,"was_temperature_f":106.0,"flow_percent":100.0,"temperature_f":106.9}
{"ts":"2026-08-18T22:01:44.684072Z","event":"setting_change","zone":2,"mask":1,"flowing_for":125.21,"was_flow_percent":100.0,"was_temperature_f":106.0,"flow_percent":100.0,"temperature_f":106.9}
{"ts":"2026-08-18T22:02:09.853847Z","event":"setting_change","zone":1,"mask":4,"flowing_for":136.55,"was_flow_percent":100.0,"was_temperature_f":106.9,"flow_percent":100.0,"temperature_f":104.0}
{"ts":"2026-08-18T22:02:09.853948Z","event":"setting_change","zone":2,"mask":1,"flowing_for":150.38,"was_flow_percent":100.0,"was_temperature_f":106.9,"flow_percent":100.0,"temperature_f":104.0}
{"ts":"2026-08-18T22:02:10.513689Z","event":"setting_change","zone":1,"mask":4,"flowing_for":137.21,"was_flow_percent":100.0,"was_temperature_f":104.0,"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-18T22:02:10.513790Z","event":"setting_change","zone":2,"mask":1,"flowing_for":151.04,"was_flow_percent":100.0,"was_temperature_f":104.0,"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-18T22:02:11.711659Z","event":"setting_change","zone":1,"mask":4,"flowing_for":138.41,"was_flow_percent":100.0,"was_temperature_f":102.9,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:02:11.819129Z","event":"setting_change","zone":2,"mask":1,"flowing_for":152.35,"was_flow_percent":100.0,"was_temperature_f":102.9,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:02:12.264093Z","event":"setting_change","zone":1,"mask":4,"flowing_for":138.96,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T22:02:12.264199Z","event":"setting_change","zone":2,"mask":1,"flowing_for":152.79,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T22:02:13.806716Z","event":"setting_change","zone":1,"mask":4,"flowing_for":140.5,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T22:02:13.806821Z","event":"setting_change","zone":2,"mask":1,"flowing_for":154.34,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T22:02:35.150565Z","event":"setting_change","zone":1,"mask":4,"flowing_for":161.85,"was_flow_percent":100.0,"was_temperature_f":99.9,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T22:02:35.150694Z","event":"setting_change","zone":2,"mask":1,"flowing_for":175.68,"was_flow_percent":100.0,"was_temperature_f":99.9,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T22:02:35.278436Z","event":"setting_change","zone":1,"mask":4,"flowing_for":161.98,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:02:35.369577Z","event":"setting_change","zone":2,"mask":1,"flowing_for":175.9,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:02:35.610687Z","event":"setting_change","zone":1,"mask":4,"flowing_for":162.31,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-18T22:02:35.610800Z","event":"setting_change","zone":2,"mask":1,"flowing_for":176.14,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-18T22:02:35.934463Z","event":"setting_change","zone":1,"mask":4,"flowing_for":162.63,"was_flow_percent":100.0,"was_temperature_f":102.9,"flow_percent":100.0,"temperature_f":104.0}
{"ts":"2026-08-18T22:02:35.934572Z","event":"setting_change","zone":2,"mask":1,"flowing_for":176.46,"was_flow_percent":100.0,"was_temperature_f":102.9,"flow_percent":100.0,"temperature_f":104.0}
{"ts":"2026-08-18T22:02:36.265931Z","event":"setting_change","zone":1,"mask":4,"flowing_for":162.96,"was_flow_percent":100.0,"was_temperature_f":104.0,"flow_percent":100.0,"temperature_f":104.9}
{"ts":"2026-08-18T22:02:36.478984Z","event":"setting_change","zone":2,"mask":1,"flowing_for":177.01,"was_flow_percent":100.0,"was_temperature_f":104.0,"flow_percent":100.0,"temperature_f":104.9}
{"ts":"2026-08-18T22:02:36.697055Z","event":"setting_change","zone":1,"mask":4,"flowing_for":163.39,"was_flow_percent":100.0,"was_temperature_f":104.9,"flow_percent":100.0,"temperature_f":106.0}
{"ts":"2026-08-18T22:02:36.837081Z","event":"setting_change","zone":2,"mask":1,"flowing_for":177.37,"was_flow_percent":100.0,"was_temperature_f":104.9,"flow_percent":100.0,"temperature_f":106.0}
{"ts":"2026-08-18T22:02:37.466036Z","event":"setting_change","zone":1,"mask":4,"flowing_for":164.16,"was_flow_percent":100.0,"was_temperature_f":106.0,"flow_percent":100.0,"temperature_f":106.9}
{"ts":"2026-08-18T22:02:37.466180Z","event":"setting_change","zone":2,"mask":1,"flowing_for":178.0,"was_flow_percent":100.0,"was_temperature_f":106.0,"flow_percent":100.0,"temperature_f":106.9}
{"ts":"2026-08-18T22:02:57.093280Z","event":"setting_change","zone":1,"mask":4,"flowing_for":183.79,"was_flow_percent":100.0,"was_temperature_f":106.9,"flow_percent":100.0,"temperature_f":106.0}
{"ts":"2026-08-18T22:02:57.093391Z","event":"setting_change","zone":2,"mask":1,"flowing_for":197.62,"was_flow_percent":100.0,"was_temperature_f":106.9,"flow_percent":100.0,"temperature_f":106.0}
{"ts":"2026-08-18T22:02:57.312242Z","event":"setting_change","zone":1,"mask":4,"flowing_for":184.01,"was_flow_percent":100.0,"was_temperature_f":106.0,"flow_percent":100.0,"temperature_f":104.9}
{"ts":"2026-08-18T22:02:57.312344Z","event":"setting_change","zone":2,"mask":1,"flowing_for":197.84,"was_flow_percent":100.0,"was_temperature_f":106.0,"flow_percent":100.0,"temperature_f":104.9}
{"ts":"2026-08-18T22:02:57.454619Z","event":"setting_change","zone":1,"mask":4,"flowing_for":184.15,"was_flow_percent":100.0,"was_temperature_f":104.9,"flow_percent":100.0,"temperature_f":104.0}
{"ts":"2026-08-18T22:02:57.661610Z","event":"setting_change","zone":2,"mask":1,"flowing_for":198.19,"was_flow_percent":100.0,"was_temperature_f":104.9,"flow_percent":100.0,"temperature_f":104.0}
{"ts":"2026-08-18T22:02:57.869477Z","event":"setting_change","zone":1,"mask":4,"flowing_for":184.57,"was_flow_percent":100.0,"was_temperature_f":104.0,"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-18T22:02:57.869567Z","event":"setting_change","zone":2,"mask":1,"flowing_for":198.4,"was_flow_percent":100.0,"was_temperature_f":104.0,"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-18T22:02:58.421582Z","event":"setting_change","zone":1,"mask":4,"flowing_for":185.12,"was_flow_percent":100.0,"was_temperature_f":102.9,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:02:58.421682Z","event":"setting_change","zone":2,"mask":1,"flowing_for":198.95,"was_flow_percent":100.0,"was_temperature_f":102.9,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:02:58.961496Z","event":"setting_change","zone":1,"mask":4,"flowing_for":185.66,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T22:02:58.961597Z","event":"setting_change","zone":2,"mask":1,"flowing_for":199.49,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T22:02:59.423226Z","event":"setting_change","zone":1,"mask":4,"flowing_for":186.12,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T22:02:59.424191Z","event":"setting_change","zone":2,"mask":1,"flowing_for":199.95,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T22:03:23.932657Z","event":"flow_end","zone":1,"duration":210.63,"limits":[900],"mask":4,"paused":true,"flow_percent":100.0,"temperature_f":99.9,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":689.37}
{"ts":"2026-08-18T22:03:23.932788Z","event":"flow_end","zone":2,"duration":224.46,"limits":[900],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":99.9,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":675.54}
```
