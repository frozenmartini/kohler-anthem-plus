# Case study 3 — both ceilings at 15 minutes, and both fired

**2026-08-18. The controlling experiment: GCS `maximumRunTime` and HUB max shower duration
both set to 15 minutes, the shower started with the controller's `valveOnOff` so the
controller unambiguously owns the session. The question was which device sends the stop.**

**The answer is both — 1.087 seconds apart.**

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

> **The headline.** With both maximums at 900 s and the session owned by the controller,
> **both devices independently commanded a shutoff**: the valve paused at 899.918 s with
> `0x40`, and the controller stopped at 901.004 s with `0x00`. Neither deferred to the other.
> **This is the control that closes case study 1** — see §7.

---

## 1. Configuration at the time

| Setting | Where | Value | How verified |
|---|---|---|---|
| **GCS max shower duration** (`maximumRunTime`) | Anthem valve, per outlet | **900 s = 15 min** | cutoff journal, `limits":[900]` on every event |
| **HUB max shower duration** | Anthem Plus controller | **900 s = 15 min** | owner-set; the 901.004 s stop is the measurement |
| Start route | — | **HUB `valveOnOff`** | deliberate — puts the session unambiguously under the controller |
| Endless Shower | integration option | **enabled** | it fired; see §5 |

**The design of the experiment is the point.** Case studies 1 and 2 each had exactly one
timer in play. This one puts both in play at the same value, on a session the controller
demonstrably owns, so that whatever happens at 900 s is a direct comparison rather than an
inference.

## 2. Who commanded what

| # | Local time | Event | Commanded by |
|---|---|---|---|
| 1 | 14:20:16.516 | water on — warm-up, five outlets | **HUB `valveOnOff`** |
| 2 | 14:20:25.064 | warm-up ends, settles to outlet 4 | **the HUB** |
| 3 | 14:35:16.434 | **`0x40` pause, zone 2** | **the GCS valve** — its own 900 s expiring |
| 4 | 14:35:17.521 | **`0x00` stop, both zones** | **the HUB** — its own 900 s expiring |
| 5 | 14:35:18.173 | water restored | **Home Assistant** — Endless Shower, `solowritesystem` |
| 6 | 14:36:07.802 | shower ended | **the owner**, via Home Assistant's Anthem Plus Shower switch (`valveOnOff` OFF) |

## 3. The complete capture

`/config/kohler_anthem_plus_raw/mqtt_raw_20260818T201525Z_72_d536f3df.jsonl`. Complete records
verbatim in [Appendix A](#appendix-a--every-raw-record-of-the-session).

```text
local           who  message
14:20:16.516    GCS  v1=0184C807  v2=1184C803    valveOnOff — warm-up: z1 outlets 1+2+3, z2 outlets 4+5
14:20:16.906    HUB  z1=ON:111000  z2=ON:110000   warmup=1                        (+0.389 s)
14:20:24.954    GCS  v1=0184C800  v2=1184C803    zone 1 closes                    (+8.438 s)
14:20:25.064    GCS  v1=0184C800  v2=1184C801    settles to outlet 4              (+8.548 s)
14:20:25.439    HUB  z1=OFF:000000 z2=ON:100000   warmup=0                        (+0.375 s)
14:20:50.420    GCS  v1=0584C800  v2=1184C801    atTemp set                       (+33.903 s)
              ──────────────── 14 m 26 s, outlet 4 alone ────────────────
14:35:16.434    GCS  v1=0584C800  v2=1184C840    ⬅ THE VALVE PAUSES               (+899.918 s)
14:35:17.058    HUB  z1=OFF:000000 z2=OFF:000000  renders the shower off          (+0.624 s)
14:35:17.521    GCS  v1=0184C800  v2=1184C800    ⬅ THE CONTROLLER STOPS           (+901.004 s)
14:35:18.173    GCS  v1=0184C800  v2=1184C801    ⬅ our restore lands              (+901.656 s)
14:35:18.483    HUB  z1=OFF:000000 z2=ON:100000   renders z2 ON again             (+0.310 s)
14:35:19.072    GCS  v1=0584C800  v2=1184C801    atTemp back                      (+902.556 s)
14:36:07.802    GCS  v1=0184C800  v2=1184C800    owner ends it                    (+951.286 s)
14:36:08.448    HUB  z1=OFF:000000 z2=OFF:000000                                  (+0.646 s)
```

Temperature `0x184` (388) = 38.8 °C = 102 °F throughout; flow `0xC8` (200) = 100% against a
`0xC8` (200) ceiling. Masks: `0x07` (7) = zone 1 outlets 1+2+3, `0x03` (3) = zone 2 outlets
4+5, `0x01` (1) = outlet 4, `0x00` (0) = closed, `0x40` = pause flag.

## 4. ⭐ Both devices fired, 1.087 s apart

| | fired at | against its own 900 s | signal | mask |
|---|---|---|---|---|
| **GCS valve** | **899.918 s** | **−0.082 s** (early) | **`0x40`** pause | zone 2 only |
| **HUB controller** | **901.004 s** | **+1.004 s** (late) | **`0x00`** stop | both zones |

**Neither deferred to the other.** Both clocks were anchored at the same open, both ran to
900 s, and both issued their own command. The valve pauses; the controller stops — exactly the
signalling split established in session 9, now seen side by side in a single second.

The bias is consistent, not noise: the controller also overshot in
[case study 2](02_hub_commanded_shower_15min.md), by **+0.557 s**. Two measurements, both
sub-second-and-a-bit late. The valve, by contrast, fires marginally early.

### The `0x00` at 14:35:17.521 is the controller's, not ours

Worth stating explicitly, because it lands inside our restore window and could be mistaken for
an echo of our own write:

1. **It is not what we sent.** Our restore wrote `v2=1184C801`, mask `0x01`. This word is
   `1184C800`, mask `0x00`.
2. **Its timing matches the controller's signature** — `+1.004 s` past a 900 s deadline,
   against case study 2's `+0.557 s`.
3. **Our write appears 0.652 s later**, at 14:35:18.173 — `+709 ms` after `restore_done`,
   matching case study 1's echo latency of `+618 ms`.

The pause flag did not clear because we cleared it. **The controller overwrote a paused valve
with a full stop.**

## 5. Endless Shower fired — and overrode the controller's ceiling by accident

The cutoff journal, complete for this session:

```json
{"ts":"2026-08-18T21:20:16.517294Z","event":"flow_start","zone":1,"mask":7,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:20:16.517414Z","event":"flow_start","zone":2,"mask":3,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:20:24.955154Z","event":"flow_end","zone":1,"duration":8.44,"limits":[900],"mask":7,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":891.56}
{"ts":"2026-08-18T21:20:25.065264Z","event":"mask_change","zone":2,"mask":1,"was":3,"flowing_for":8.55,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:35:16.434937Z","event":"flow_end","zone":2,"duration":899.92,"limits":[900],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":101.8,"verdict":"cutoff","matched":900}
{"ts":"2026-08-18T21:35:16.435136Z","event":"restore","zones":[2],"also_paused":[],"masks":{"1":0,"2":1},"from_detector":{"2":1},"from_snapshot":{"1":0,"2":1},"was_flow_percent":{"2":100.0},"was_temperature_f":{"2":101.8},"writing_flow_percent":{"2":100.0},"flow_preserved":true}
{"ts":"2026-08-18T21:35:17.463837Z","event":"restore_done","outlets":[4],"write_seconds":1.03}
{"ts":"2026-08-18T21:35:18.173790Z","event":"flow_start","zone":2,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:36:07.803126Z","event":"flow_end","zone":2,"duration":49.63,"limits":[900],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":850.37}
```

### The controller's stop was invisible to the detector

**There is no `flow_end` for 14:35:17.521.** The detector fires on *a flowing zone that stops
flowing*; zone 2 had already stopped 1.087 s earlier at the valve's pause. By the time the
`0x00` arrived there was no flow to end. The controller's ceiling passed through a zone that
was already closed and left no trace in the journal at all.

### And our write was already committed when it arrived

```text
21:35:16.434937Z  valve publishes 0x40 pause             the valve's 900 s
21:35:16.435136Z  detector decides: cutoff, matched 900  +0.2 ms  — the decision is free
21:35:17.463837Z  our solowritesystem POST returns       +1.029 s
21:35:17.521      valve publishes 1184C800               +1.086 s  <- the controller's stop
21:35:18.173      valve publishes 1184C801               +1.738 s  <- our write applied
```

Our POST had **already returned** before the controller's stop appeared. The valve applied the
controller's stop, then ours 0.652 s later.

> ⚠️ **So Endless Shower overrode the controller's max shower duration — a limit set on the
> other device — without ever detecting it.** Session 9 designed this feature to defeat the
> *valve's* `maximumRunTime`. Here it defeated the controller's ceiling too, incidentally,
> because the restore was in flight when the stop landed.

### That outcome is ordering-dependent

The valve fired 0.082 s early and the controller 1.004 s late — a **1.087 s** window against a
restore that takes **1.738 s** end to end. **Had the controller's stop been ~0.7 s later, it
would have landed after our restore**, shutting off water we had just restored. The detector
would then have seen a ~1 s `flow_end`, matched nothing, and left it off.

What makes the result *robust* rather than lucky is that both durations are 900 s: whichever
device fires first, its signal lands at ~900 s and **matches a limit the detector knows
about**. A `0x00` is treated exactly like a `0x40`
([`runtime_cutoff.py`](../../anthem_plus/runtime_cutoff.py), the pause veto removed in session
9), so the controller's stop would have been caught on its own had it arrived first.

**That is the real mechanism behind session 9's "set both to the same value" advice** — not
that the deadlines coincide, but that either device's cut then falls within tolerance of an
announced limit.

## 6. The owner's stop was correctly declined

14:36:07.802, 49.63 s into the restored leg, issued from Home Assistant's Anthem Plus Shower
switch (`valveOnOff` OFF). Journal: `off_by: 850.37`, `verdict: ignored`. **A `0x00` is no
longer vetoed for being a stop** — what declined it was the duration matching no limit. The
10-second tolerance is the only thing separating "end my shower" from "restart my shower", and
here it had 850 s of margin.

## 7. ⭐ The firm conclusion: the controller commands a shutoff whenever it knows a session is running

**This is what case study 3 was for, and the result is unambiguous.**

Given a session it knows about, the Anthem Plus **does** command its max-duration shutoff. It
did so here, on its own clock, 1.004 s after its deadline, with a `0x00` written to both zones
— and it did so *even though the valve had already paused the zone a second earlier*, so the
command was redundant at the moment it landed. The controller was not prompted, not waiting on
the valve, and not deferring to it. It simply enforced its own limit.

**Therefore, in [case study 1](01_ha_driven_shower_hub_blind.md), the controller did not know
the shower was running. At all.**

The argument is now closed by a positive control rather than by absence of evidence:

| | case study 1 | case study 3 |
|---|---|---|
| Shower started by | `solowritesystem` | `valveOnOff` |
| Does the controller know? | — the question — | **yes, by construction** |
| Controller max duration | 60 min, reached at 3600 s wall clock | 15 min |
| **Did the controller command a shutoff?** | **no — 86 minutes, nothing** | **yes, at 901.004 s** |

Case study 3 proves the controller's ceiling is live, enforced, and enforced *unconditionally*
when a session is known. Case study 1 ran **86 minutes** — past its 60-minute ceiling by 26
minutes — and the controller commanded nothing. A working, unconditional enforcement mechanism
that does not fire can only mean **the condition was never met: there was no session, because
the controller never registered that the shower had started.**

This is device behaviour on both sides, not message presence or absence, so it is independent
of the MQTT-channel caveats in [`intro.md`](intro.md) §1. It also matches the reasoning already
recorded in case study 1 §7 — that the controller does not treat a valve-side open it did not
command as a session — and supplies the control that argument was missing.

## 8. Two corrections to earlier readings

### 8a. Warm-up is NOT gated on the valve's `atTemp` bit

[Case study 2](02_hub_commanded_shower_15min.md) recorded warm-up ending 5.483 s **after**
`atTemp` set, which invites the reading that warm-up waits for temperature. **This session
reverses the order:**

| | warm-up ends | `atTemp` sets | order |
|---|---|---|---|
| Case study 2 | +30.258 s | +24.775 s | atTemp **first**, warm-up ends 5.483 s later |
| **Case study 3** | **+8.548 s** | **+33.903 s** | **warm-up ends first**, atTemp 25.36 s later |

Warm-up ran **8.44 s** here against 30.26 s in case study 2 — the pipes were still hot from
that shower an hour earlier. So warm-up duration tracks the plumbing, and the controller ends
it on **its own judgement**, not on the valve's `atTemp` bit. The bit then lagged another 25 s,
plausibly because dropping from five outlets to one changes the mixing and the valve had to
re-settle.

**Practical note:** the warm-up penalty on the 15-minute allowance is not fixed. It was 3.4% of
the session in case study 2 and 0.9% here.

### 8b. The controller DOES render a `solowritesystem` change — when it owns the session

At 14:35:18.483 the controller published `z2=ON:100000` — **0.310 s after our
`solowritesystem` restore**. Case study 1's controller never rendered a `solowritesystem` open
at all.

The difference is session context. In case study 1 the controller had no session, so a
valve-side open meant nothing to it. Here it had commanded the session and was watching the
valve over the wired link, so it re-rendered what it observed.

This **refines** case study 1 rather than contradicting it: the controller is not blind to the
valve. It is selective about what counts as a session start, and case study 1's `solowritesystem`
open did not.

## 9. Open

1. **Which device wins if the controller fires first?** Here the valve led by 1.087 s. The
   reverse ordering has never been observed, and it is the case where the detector must catch a
   bare `0x00` on a still-flowing zone. Predicted to work; unmeasured.
2. **Does a GCS preset start the controller's clock?** Still the last unknown row of the
   start-route table, untouched by all three case studies.
3. **Should the integration read `maxshowerduration` over the local API?**
   ([case study 2](02_hub_commanded_shower_15min.md) §8.) This session shows why it matters
   less when the two are equal and more when they differ.
4. **`warmupmode: "pause"` is still unexercised.** Only `on` has been observed, across three
   sessions.

## 10. Provenance

| Fact | Source |
|---|---|
| Every hex word, timestamp, message count | `mqtt_raw_20260818T201525Z_72_d536f3df.jsonl` — read in full |
| Cutoff verdicts, durations, restore fields | `cutoff_20260818T201525Z_72_b69de911.jsonl` — read in full |
| GCS `maximumRunTime` = 900 s | `limits":[900]` on every journal event this session |
| HUB max shower duration = 900 s | owner-set; the 901.004 s stop is the measurement |
| That the `0x00` at 14:35:17.521 is the controller's | inferred, three ways — §4 |
| That 14:36:07.802 was a manual stop via HA's `valveOnOff` | **owner-reported** |
| All timings and counterfactuals | computed from the capture's own timestamps |

---

## Appendix A — every raw record of the session

**Window: 2026-08-18 20:41:09.221Z → 21:36:08.449Z** (13:41:09 → 14:36:08 local) — from the
last message of [case study 2](02_hub_commanded_shower_15min.md) to the last message of this
one, so the two appendices abut without overlapping.

> ⛔ **Hard-capped at this session's final message, deliberately.** Case study 4 was being
> conducted immediately after, into the same capture file. Nothing after 21:36:08.449Z is
> included here and nothing after it belongs to this case study.

Every `.jsonl` in `/config/kohler_anthem_plus_raw/` was scanned across the window, not just the
two files this session wrote.

### A.1 — raw MQTT, verbatim (33 records)

Lines exactly as written by `RawLog.write()`, with **one substitution**: the real `tenantid`
is replaced by `<TENANT_ID>` per the placeholder policy in [`../README.md`](../README.md).
Device ids are left in place. Nothing else is altered.

Source file for all of them: `mqtt_raw_20260818T201525Z_72_d536f3df.jsonl`.

⚠️ The first twelve records are **not** shower activity — two identical bursts of five HUB
snapshots plus a GCS experience read, at 14:07 and 14:08 local. Each was provoked by a
**local-API login** while reading `get_valve_settings`
([case study 2](02_hub_commanded_shower_15min.md) §8), not by water. The session proper begins
at 14:20:16.516.

**14:07:43.424 local** — line 21 — HUB — SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:07:43.424052Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=21","qos":0,"retain":false,"payload":"{\"messageid\":\"51b0b645-f579-4491-942b-a50003ed876a\",\"sysid\":\"HUB-SH8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087262\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"17\",\"name\":\"Warm Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly increases to allow the body to warm up gradually while not overheating. The temperature then slowly declines.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"18\",\"name\":\"Cool Down\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly decreases to enable the body to cool down. After a cool period, water will again raise to a comfortable temperature.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"19\",\"name\":\"Sleep Simple\",\"active\":\"true\",\"duration\":\"7\",\"description\":\"Water starts at a comfortable temperature for showering. After 4 minutes, temperature will slowly lower to a neutral bathing temperature enabling the body to begin relaxing & prepare for sleep.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"20\",\"name\":\"Wake Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. As the body gets acclimated, the temperature will rise slightly keeping the body feeling warm for the duration of the shower.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"21\",\"name\":\"Shine\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. After 7 minutes the water temperature will slowly decrease to help lock in moisture in the skin and hair\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**14:07:43.644 local** — line 22 — HUB — STEAM_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:07:43.644155Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=22","qos":0,"retain":false,"payload":"{\"messageid\":\"90837782-b63b-48b1-bb8c-74a35627d7a6\",\"sysid\":\"HUB-STM8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087263\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"STEAM_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**14:07:43.978 local** — line 23 — HUB — ICE_SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:07:43.978399Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=23","qos":0,"retain":false,"payload":"{\"messageid\":\"a9d9cb9b-8588-4f4a-805c-d1983f11acdb\",\"sysid\":\"HUB-ISHEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087263\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"ICE_SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"22\",\"name\":\"Beginner Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a cool shower which will leave you feeling refreshed and awake\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"23\",\"name\":\"Advanced Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a full cold shower which will leave you feeling alert and reinvigorated\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**14:07:44.196 local** — line 24 — HUB — LUMIWAVE_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:07:44.196817Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=24","qos":0,"retain":false,"payload":"{\"messageid\":\"b9a043df-416a-438d-8355-83f35487bb31\",\"sysid\":\"HUB-LUMIEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087263\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"LUMIWAVE_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**14:07:44.519 local** — line 25 — HUB — FAVORITES_SNAPSHOT

```json
{"ts":"2026-08-18T21:07:44.519860Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=25","qos":0,"retain":false,"payload":"{\"messageid\":\"8bb35f26-c2bc-4fc6-8de6-f5348d53a671\",\"sysid\":\"HUB-INRB916T7R\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087264\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"FAVORITES_SNAPSHOT\",\"attributes\":[]}}"}
```

**14:07:45.197 local** — line 26 — GCS — READ_GCS_EXPERIENCE_STS

```json
{"ts":"2026-08-18T21:07:45.197811Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=26","qos":0,"retain":false,"payload":"{\"messageid\":\"B8FF2E2C-F63A-E444-ADD6-064639AC9042\",\"sysid\":\"GCS-INXR739U7S\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787087276\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"READ_GCS_EXPERIENCE_STS\",\"attributes\":[{\"experienceId\":\"1\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"2\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"3\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"4\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"5\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"}]}}"}
```

**14:08:13.380 local** — line 27 — HUB — SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:08:13.380603Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=27","qos":0,"retain":false,"payload":"{\"messageid\":\"7de05206-ad63-499a-8570-655a878d4acd\",\"sysid\":\"HUB-SH8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087292\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"17\",\"name\":\"Warm Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly increases to allow the body to warm up gradually while not overheating. The temperature then slowly declines.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"18\",\"name\":\"Cool Down\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly decreases to enable the body to cool down. After a cool period, water will again raise to a comfortable temperature.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"19\",\"name\":\"Sleep Simple\",\"active\":\"true\",\"duration\":\"7\",\"description\":\"Water starts at a comfortable temperature for showering. After 4 minutes, temperature will slowly lower to a neutral bathing temperature enabling the body to begin relaxing & prepare for sleep.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"20\",\"name\":\"Wake Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. As the body gets acclimated, the temperature will rise slightly keeping the body feeling warm for the duration of the shower.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"21\",\"name\":\"Shine\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. After 7 minutes the water temperature will slowly decrease to help lock in moisture in the skin and hair\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**14:08:13.589 local** — line 28 — HUB — STEAM_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:08:13.589406Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=28","qos":0,"retain":false,"payload":"{\"messageid\":\"246ba8f1-8d31-4162-92b7-c16d3b460ad4\",\"sysid\":\"HUB-STM8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087293\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"STEAM_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**14:08:13.918 local** — line 29 — HUB — ICE_SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:08:13.918442Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=29","qos":0,"retain":false,"payload":"{\"messageid\":\"9597c7bd-6b32-4674-a0cc-e24cdf4755e2\",\"sysid\":\"HUB-ISHEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087293\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"ICE_SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"22\",\"name\":\"Beginner Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a cool shower which will leave you feeling refreshed and awake\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"23\",\"name\":\"Advanced Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a full cold shower which will leave you feeling alert and reinvigorated\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**14:08:14.152 local** — line 30 — HUB — LUMIWAVE_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T21:08:14.152845Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=30","qos":0,"retain":false,"payload":"{\"messageid\":\"cd448f6b-23a0-4aba-8d33-5f37e501a6b9\",\"sysid\":\"HUB-LUMIEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087293\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"LUMIWAVE_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**14:08:14.355 local** — line 31 — HUB — FAVORITES_SNAPSHOT

```json
{"ts":"2026-08-18T21:08:14.355896Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=31","qos":0,"retain":false,"payload":"{\"messageid\":\"f707fe62-1473-42b1-aea8-4d3ad4b791b2\",\"sysid\":\"HUB-INRB916T7R\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787087294\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"FAVORITES_SNAPSHOT\",\"attributes\":[]}}"}
```

**14:08:15.444 local** — line 32 — GCS — READ_GCS_EXPERIENCE_STS

```json
{"ts":"2026-08-18T21:08:15.444982Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=32","qos":0,"retain":false,"payload":"{\"messageid\":\"465494C6-C1EE-C764-B4DF-67580D0D37A1\",\"sysid\":\"GCS-INXR739U7S\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787087306\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"READ_GCS_EXPERIENCE_STS\",\"attributes\":[{\"experienceId\":\"1\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"2\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"3\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"4\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"5\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"}]}}"}
```

**14:18:18.736 local** — line 33 — GCS — READ_GCS_OUTLET_CONFIG_CFG

```json
{"ts":"2026-08-18T21:18:18.736478Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=33","qos":0,"retain":false,"payload":"{\"messageid\":\"4E3059A0-76D2-4414-A655-EC50D76BC580\",\"sysid\":\"GCS-INSN096T8W\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"CFG\",\"timestamp\":\"1787087910\",\"simulated\":\"false\",\"data\":{\"type\":\"Config\",\"code\":\"READ_GCS_OUTLET_CONFIG_CFG\",\"attributes\":[{\"defaultFlowRate\":\"200\",\"defaultOutletTemperature\":\"388\",\"maximumFlowRate\":\"200\",\"maximumOutletTemperature\":\"450\",\"maximumRunTime\":\"900\",\"minimumFlowRate\":\"16\",\"minimumOutletTemperature\":\"150\",\"outLetFlags\":\"1\",\"outLetId\":\"0\",\"outLetType\":\"62\"}]}}"}
```

**14:18:18.859 local** — line 34 — GCS — READ_GCS_OUTLET_CONFIG_CFG

```json
{"ts":"2026-08-18T21:18:18.859385Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=34","qos":0,"retain":false,"payload":"{\"messageid\":\"F4D8AA30-66BB-F1D4-A30F-D205EDC5BE7E\",\"sysid\":\"GCS-INSN096T8W\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"CFG\",\"timestamp\":\"1787087910\",\"simulated\":\"false\",\"data\":{\"type\":\"Config\",\"code\":\"READ_GCS_OUTLET_CONFIG_CFG\",\"attributes\":[{\"defaultFlowRate\":\"200\",\"defaultOutletTemperature\":\"388\",\"maximumFlowRate\":\"200\",\"maximumOutletTemperature\":\"450\",\"maximumRunTime\":\"900\",\"minimumFlowRate\":\"16\",\"minimumOutletTemperature\":\"150\",\"outLetFlags\":\"1\",\"outLetId\":\"1\",\"outLetType\":\"52\"}]}}"}
```

**14:18:18.992 local** — line 35 — GCS — READ_GCS_OUTLET_CONFIG_CFG

```json
{"ts":"2026-08-18T21:18:18.992112Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=35","qos":0,"retain":false,"payload":"{\"messageid\":\"0B8018AF-CB35-9B74-9B36-5CD71790824B\",\"sysid\":\"GCS-INSN096T8W\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"CFG\",\"timestamp\":\"1787087910\",\"simulated\":\"false\",\"data\":{\"type\":\"Config\",\"code\":\"READ_GCS_OUTLET_CONFIG_CFG\",\"attributes\":[{\"defaultFlowRate\":\"200\",\"defaultOutletTemperature\":\"388\",\"maximumFlowRate\":\"200\",\"maximumOutletTemperature\":\"450\",\"maximumRunTime\":\"900\",\"minimumFlowRate\":\"16\",\"minimumOutletTemperature\":\"150\",\"outLetFlags\":\"1\",\"outLetId\":\"2\",\"outLetType\":\"1\"}]}}"}
```

**14:18:19.204 local** — line 36 — GCS — READ_GCS_OUTLET_CONFIG_CFG

```json
{"ts":"2026-08-18T21:18:19.204719Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=36","qos":0,"retain":false,"payload":"{\"messageid\":\"DE90398B-BB45-31F4-B661-2DB319D079C3\",\"sysid\":\"GCS-INSN096T8W\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"CFG\",\"timestamp\":\"1787087910\",\"simulated\":\"false\",\"data\":{\"type\":\"Config\",\"code\":\"READ_GCS_OUTLET_CONFIG_CFG\",\"attributes\":[{\"defaultFlowRate\":\"200\",\"defaultOutletTemperature\":\"388\",\"maximumFlowRate\":\"200\",\"maximumOutletTemperature\":\"450\",\"maximumRunTime\":\"900\",\"minimumFlowRate\":\"16\",\"minimumOutletTemperature\":\"150\",\"outLetFlags\":\"1\",\"outLetId\":\"3\",\"outLetType\":\"11\"}]}}"}
```

**14:18:19.329 local** — line 37 — GCS — READ_GCS_OUTLET_CONFIG_CFG

```json
{"ts":"2026-08-18T21:18:19.329936Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=37","qos":0,"retain":false,"payload":"{\"messageid\":\"5E9490A6-88A2-C384-9BBA-8A0B219212A5\",\"sysid\":\"GCS-INSN096T8W\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"CFG\",\"timestamp\":\"1787087910\",\"simulated\":\"false\",\"data\":{\"type\":\"Config\",\"code\":\"READ_GCS_OUTLET_CONFIG_CFG\",\"attributes\":[{\"defaultFlowRate\":\"200\",\"defaultOutletTemperature\":\"388\",\"maximumFlowRate\":\"200\",\"maximumOutletTemperature\":\"450\",\"maximumRunTime\":\"900\",\"minimumFlowRate\":\"16\",\"minimumOutletTemperature\":\"150\",\"outLetFlags\":\"1\",\"outLetId\":\"4\",\"outLetType\":\"38\"}]}}"}
```

**14:18:19.452 local** — line 38 — GCS — READ_GCS_OUTLET_CONFIG_CFG

```json
{"ts":"2026-08-18T21:18:19.452539Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=38","qos":0,"retain":false,"payload":"{\"messageid\":\"4A4093F4-E2B5-7804-9A3D-CB793072A3CD\",\"sysid\":\"GCS-INSN096T8W\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"CFG\",\"timestamp\":\"1787087910\",\"simulated\":\"false\",\"data\":{\"type\":\"Config\",\"code\":\"READ_GCS_OUTLET_CONFIG_CFG\",\"attributes\":[{\"defaultFlowRate\":\"200\",\"defaultOutletTemperature\":\"388\",\"maximumFlowRate\":\"200\",\"maximumOutletTemperature\":\"450\",\"maximumRunTime\":\"900\",\"minimumFlowRate\":\"16\",\"minimumOutletTemperature\":\"150\",\"outLetFlags\":\"1\",\"outLetId\":\"5\",\"outLetType\":\"21\"}]}}"}
```

**14:18:23.616 local** — line 39 — GCS — READ_GCS_EXPERIENCE_STS

```json
{"ts":"2026-08-18T21:18:23.616012Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=39","qos":0,"retain":false,"payload":"{\"messageid\":\"B10AE378-F0AF-8044-BF10-FEF90D3A7BB5\",\"sysid\":\"GCS-INXR739U7S\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787087914\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"READ_GCS_EXPERIENCE_STS\",\"attributes\":[{\"experienceId\":\"1\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"2\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"3\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"4\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"5\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"}]}}"}
```

**14:20:16.516 local** — line 40 — GCS — v1=0184C807 v2=1184C803

```json
{"ts":"2026-08-18T21:20:16.516772Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=40","qos":0,"retain":false,"payload":"{\"messageid\":\"A3E8D92E-BE0A-3704-9097-C309E12B4D36\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088027\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1535\",\"totalVolume\":\"536930784\",\"primaryValve1\":\"0184c80700000001\",\"secondaryValve1\":\"1184c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:20:16.906 local** — line 41 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T21:20:16.906082Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=41","qos":0,"retain":false,"payload":"{\"messageid\":\"53cd9bdb-0a63-4e0f-9e7d-d930f87144f5\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787088016\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"1\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,1,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**14:20:24.954 local** — line 42 — GCS — v1=0184C800 v2=1184C803

```json
{"ts":"2026-08-18T21:20:24.954647Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=42","qos":0,"retain":false,"payload":"{\"messageid\":\"ECEDCFFD-189C-FA74-9201-9FB17385DFB6\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088036\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:20:25.064 local** — line 43 — GCS — v1=0184C800 v2=1184C801

```json
{"ts":"2026-08-18T21:20:25.064833Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=43","qos":0,"retain":false,"payload":"{\"messageid\":\"6679D2FC-FF72-6F74-8D9E-125219A34F9E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088036\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:20:25.439 local** — line 44 — HUB — z1=OFF z2=ON

```json
{"ts":"2026-08-18T21:20:25.439620Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=44","qos":0,"retain":false,"payload":"{\"messageid\":\"3c6f1a55-49f6-42fd-a104-f9a28d1667bb\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787088025\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**14:20:50.420 local** — line 45 — GCS — v1=0584C800 v2=1184C801

```json
{"ts":"2026-08-18T21:20:50.420041Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=45","qos":0,"retain":false,"payload":"{\"messageid\":\"4E495AA9-0F42-2674-9B6F-4A299B940FF9\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088061\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:35:16.434 local** — line 46 — GCS — v1=0584C800 v2=1184C840

```json
{"ts":"2026-08-18T21:35:16.434330Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=46","qos":0,"retain":false,"payload":"{\"messageid\":\"5E42A70F-9892-2E34-8804-D4C1C50AB0AE\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088927\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:35:17.058 local** — line 47 — HUB — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T21:35:17.058022Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=47","qos":0,"retain":false,"payload":"{\"messageid\":\"6896d717-b2c7-4df5-ba42-3ec62638b5b8\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787088916\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**14:35:17.521 local** — line 48 — GCS — v1=0184C800 v2=1184C800

```json
{"ts":"2026-08-18T21:35:17.521062Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=48","qos":0,"retain":false,"payload":"{\"messageid\":\"87F8DE31-2AEE-3AD4-933D-1370F6B5323E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088928\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1655\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:35:18.173 local** — line 49 — GCS — v1=0184C800 v2=1184C801

```json
{"ts":"2026-08-18T21:35:18.173247Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=49","qos":0,"retain":false,"payload":"{\"messageid\":\"EC95E5A8-48B6-C474-B245-0B83EB62D8CF\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088929\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"12339\",\"totalVolume\":\"1646410274\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:35:18.483 local** — line 50 — HUB — z1=OFF z2=ON

```json
{"ts":"2026-08-18T21:35:18.483008Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=50","qos":0,"retain":false,"payload":"{\"messageid\":\"1099f423-713b-438e-86b3-7bba21c912d1\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787088918\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**14:35:19.072 local** — line 51 — GCS — v1=0584C800 v2=1184C801

```json
{"ts":"2026-08-18T21:35:19.072767Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=51","qos":0,"retain":false,"payload":"{\"messageid\":\"F80B856C-6E34-06D4-9953-4BA9ADFC34B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088930\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1658\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:36:07.802 local** — line 52 — GCS — v1=0184C800 v2=1184C800

```json
{"ts":"2026-08-18T21:36:07.802571Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=52","qos":0,"retain":false,"payload":"{\"messageid\":\"4430ACBA-83A7-3394-B5F8-D07AFB682C2A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787088979\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**14:36:08.448 local** — line 53 — HUB — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T21:36:08.448811Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=53","qos":0,"retain":false,"payload":"{\"messageid\":\"3e21a3f6-bcb7-43e1-9006-b5daa12b80fe\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787088968\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

### A.2 — cutoff journal, verbatim (9 records)

Source file: `cutoff_20260818T201525Z_72_b69de911.jsonl`. The `arm` line (20:15:26Z, at integration setup) and case study 2's
six entries fall before this window and are quoted in their own documents.

```json
{"ts":"2026-08-18T21:20:16.517294Z","event":"flow_start","zone":1,"mask":7,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:20:16.517414Z","event":"flow_start","zone":2,"mask":3,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:20:24.955154Z","event":"flow_end","zone":1,"duration":8.44,"limits":[900],"mask":7,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":891.56}
{"ts":"2026-08-18T21:20:25.065264Z","event":"mask_change","zone":2,"mask":1,"was":3,"flowing_for":8.55,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:35:16.434937Z","event":"flow_end","zone":2,"duration":899.92,"limits":[900],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":101.8,"verdict":"cutoff","matched":900}
{"ts":"2026-08-18T21:35:16.435136Z","event":"restore","zones":[2],"also_paused":[],"masks":{"1":0,"2":1},"from_detector":{"2":1},"from_snapshot":{"1":0,"2":1},"was_flow_percent":{"2":100.0},"was_temperature_f":{"2":101.8},"writing_flow_percent":{"2":100.0},"flow_preserved":true}
{"ts":"2026-08-18T21:35:17.463837Z","event":"restore_done","outlets":[4],"write_seconds":1.03}
{"ts":"2026-08-18T21:35:18.173790Z","event":"flow_start","zone":2,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T21:36:07.803126Z","event":"flow_end","zone":2,"duration":49.63,"limits":[900],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":850.37}
```
