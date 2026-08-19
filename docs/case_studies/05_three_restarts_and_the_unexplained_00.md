# Case study 5 — three restarts, a clear flag, broken zone tracking, and one `00/00` nobody can explain

**2026-08-18, 15:51:00 – 16:31:49 local. Two zones started eight minutes apart, both
maximums at 900 s, Endless Shower on. Three cutoffs, three restores — and the middle one
behaved unlike the other two.**

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

> **The headline.** **Restart 1 and restart 3 were normal.** **Restart 2 was not**: an
> unexplained `00/00` zeroed both zones mid-restore, which **reset the other zone's run-time
> clock and merged the two zones' independent timers into one**. Fifteen minutes later they
> expired together — that is restart 3. Along the way `configWriteAllowedFlag` gave us the
> first clear window into the valve's internal state, and the controller published a zone
> state the valve never held.

**An interactive colour-coded readout of this entire session is published as
[Anthem Valve Trace](https://claude.ai/code/artifact/6c10c36c-7486-43e4-99af-8e90618b26b6)** —
all 107 events on one `+0.000s` timeline, filterable by source.

---

## 1. Configuration at the time

| Setting | Value | How verified |
|---|---|---|
| GCS `maximumRunTime` | **900 s = 15 min** | `"limits":[900]` on every journal event |
| HUB max shower duration | 900 s = 15 min (unchanged from [case study 3](03_both_ceilings_at_15_minutes.md)) | not exercised — no HUB stop appeared |
| Endless Shower | **enabled** | fired three times |
| Home Assistant Core | restarted 15:41:05 | new capture file, PID 71 |

**Started from Home Assistant** — the outlet switches, via `solowritesystem`. Owner-confirmed:
the first-generation touchscreen was not used to start any shower that day. The wire agrees as
far as it can: the first word is a bare `1184c80100000001` with no warm-up recipe, so it was
certainly not `valveOnOff`.

## 2. The three restarts

| | local | zone cut | duration | signal | outcome |
|---|---|---|---|---|---|
| **Restart 1** | 16:06:00.114 | **zone 2** | 899.85 s | `0x40` | **normal** — 2 messages, clean swap |
| **Restart 2** | 16:14:12.891 | **zone 1** | 899.92 s | `0x40` | **anomalous** — `00/00`, both zones zeroed |
| **Restart 3** | 16:29:14.048 | **both** | 899.84 s each | `0x40` | **normal** — but caused by restart 2 |

Zone 2 began flowing at 15:51:00.260 and zone 1 at 15:59:12.974 — **492.7 s apart**. That
offset produced restarts 1 and 2 in that order, exactly as two independent clocks should.

**No `0x00` cutoff signal appeared at any of the three.** All three were pure `0x40` pauses
from the valve. The controller never commanded a stop this session.

## 3. Restart 1 — what normal looks like

```text
16:06:00.114  +0.000s  v1=057FC801 atTemp | v2=117FC840 PAUSE   cfgW=0
16:06:00.789  +0.676s  HUB  z1=ON:100000 T=101  z2=OFF
16:06:00.945  +0.832s  JRN  restore_done outlets=[1,4] write_seconds=0.83
16:06:01.552  +1.438s  v1=057FC801 atTemp | v2=117FC801         cfgW=0
16:06:01.907  +1.793s  HUB  z1=ON:100000  z2=ON:100000
```

Two valve messages. Zone 1's word is **byte-identical before and after**. Temperature `383`
(101 °F) unchanged. atTemp undisturbed. `cfgW` stays `0` throughout, because zone 1 — the
primary — never stopped flowing. Water off 1.438 s, zone 2 only. Zone 1's clock untouched.

## 4. ⭐ Restart 2 — the anomaly

```text
16:14:12.891  +0.000s  v1=0579C840 PAUSE atTemp | v2=1179C802   cfgW=0
16:14:12.892  +0.001s  JRN  flow_end zone 1, 899.92 s, verdict cutoff, matched 900
16:14:12.892  +0.001s  JRN  restore zones=[1] masks={"1":5,"2":2}
16:14:13.313  +0.422s  HUB  z1=OFF  z2=ON:010000 T=100
16:14:13.527  +0.636s  JRN  restore_done outlets=[1,3,5] write_seconds=0.64
16:14:13.643  +0.751s  v1=0579C840 PAUSE atTemp | v2=1179C802   cfgW=1   ← flag flips, word identical
16:14:13.766  +0.875s  v1=0179C800              | v2=1179C800   cfgW=1   ← 00/00, atTemp clears
16:14:13.767  +0.875s  JRN  flow_end zone 2, 492.21 s, paused=false, verdict ignored, off_by 407.79
16:14:14.207  +1.316s  v1=0179C805              | v2=1179C802   cfgW=0   ← our restore lands
16:14:14.208  +1.316s  JRN  flow_start zone 1  AND  flow_start zone 2   ← identical timestamps
16:14:15.067  +2.175s  v1=0579C805 atTemp       | v2=1179C802   cfgW=0
```

Three things happened here that did not happen at restarts 1 or 3.

**A `00/00` appeared at +0.875 s** and zeroed **both** zones — including zone 2, which was
delivering water at mask `0x02` and had nothing to do with the cutoff. Water stopped on both
for roughly 0.44 s.

**Zone 2's run-time clock was cleared.** The journal recorded a `flow_end` for it at 492.21 s
— `verdict: ignored`, since that matched no limit — and then restarted it. **The reset comes
from the `flow_end` bookkeeping, not from the `0x00`-treated-as-`0x40` policy**; any zone that
stops flowing has its timer cleared regardless of verdict, so the old pause-only rule would
have done the same.

**The two zones' clocks merged.** Both `flow_start` entries carry the identical timestamp
**16:14:14.208**. From that instant the zones were no longer independent.

### What we sent

One `solowritesystem` POST, reconstructed through the shipped encoder from the journal:

```text
+0.001s   decided          v1=0179C805   v2=1179C802
+0.636s   POST returned    (write_seconds 0.64)
+1.316s   valve applied
```

The `00/00` arrived **0.239 s after our POST returned but 0.441 s before our word was
applied.** We did not cause it in any way we can demonstrate, and we did not prevent it — our
write simply landed last and restored both zones.

## 5. Restart 3 — normal mechanism, caused by restart 2

```text
16:29:14.048  +0.000s  v1=056EC840 PAUSE atTemp | v2=116EC840 PAUSE   cfgW=0
16:29:14.446  +0.397s  HUB  z1=OFF  z2=ON:010000 T=98
16:29:14.647  +0.598s  HUB  z1=OFF  z2=OFF
16:29:14.991  +0.942s  JRN  restore_done outlets=[1,5] write_seconds=0.94
16:29:15.728  +1.680s  v1=056EC801 atTemp | v2=116EC802             cfgW=0
16:29:16.114  +2.065s  HUB  z1=ON:100000  z2=ON:010000
```

Two valve messages, no `00/00`, `cfgW` never flips, temperature `366` (98 °F) preserved on
both, atTemp never clears. Mechanically this is as clean as restart 1.

**But it should not have happened at all.** Both zones show `duration: 899.84` — identical to
the millisecond — because both clocks were re-anchored at 16:14:14.208 by restart 2's
teardown. 16:14:14.208 + 899.84 s = 16:29:14.048.

**Two zones that started 492.7 s apart, and would never have expired together, were merged by
our own restore and then cut as one.**

## 6. ⭐ `configWriteAllowedFlag` — the clearest new instrument we have

**`1` = configuration writes allowed. `0` = not allowed.** Established across all 1446 valve
messages in the corpus, against the state of **zone 1, the primary valve**:

| | `cfgW=0` | `cfgW=1` |
|---|---|---|
| zone 1 idle (mask `0x00`, no `0x40`) | 6 | **775** |
| zone 1 doing something | **602** | 63 |

99.2% / 90.5%. You cannot reconfigure a valve that is delivering water. Zone 2 barely predicts
it at all (433 vs 268) — [case study 1](01_ha_driven_shower_hub_blind.md) is the clean
demonstration, with zone 2 running 86 minutes while `cfgW` read `1` throughout.

**Why this matters more than the flag itself:** at restart 2 the byte-identical word
`0579C840 / 1179C802` appeared twice, 0.751 s apart, first with `cfgW=0` and then with
`cfgW=1`. **The flag is not derivable from the four command bytes.** It exposes internal valve
state that the word does not carry — the only such window we have found.

What it shows: **the primary goes idle roughly 0.8 s after its water stops.** Two clean
measurements — restart 2 at **+0.751 s**, [case study 4](04_two_touchscreens_and_what_off_means.md)
at **+0.875 s**. That is a settling time, not a decision.

⚠️ **It predicts nothing downstream.** Case study 4 sat at `cfgW=1` for **119 seconds** before
its teardown. Measured intervals from `cfgW=1` to a teardown across the corpus: **0.104 s,
0.124 s, ~35 s, ~87 s, 119.19 s** — and most often no teardown at all. Every teardown occurs
while `cfgW=1`; that is necessary and nowhere near sufficient.

## 7. ⭐ Individual zone tracking is broken on the controller

At restart 3 the valve paused **both zones in one word**. The controller then published two
messages, 201 ms apart:

```text
16:29:14.048  VALVE  v1=056EC840 PAUSE | v2=116EC840 PAUSE     both, one word
16:29:14.446  HUB    z1=OFF  z2=ON:010000 T=98                 +0.397s  ← z2 reads ON
16:29:14.647  HUB    z1=OFF  z2=OFF                            +0.598s  ← catches up
```

The valve published **nothing** between 14.048 and 15.728. So that first controller message
corresponds to **no valve state that ever existed**: zone 1's half is current, zone 2's half is
stale from 16:25:54.

**The controller refreshes its two zones independently and will push a card after updating only
one of them.** For roughly 200 ms the app would have shown a shower that was half-paused when
the valve had stopped both.

This is a genuine addition to [`intro.md`](intro.md) §1's rules. It was already recorded there
that absence of a message is weak evidence; this shows **presence of a message can be actively
wrong**, transiently, about a state the device was never in.

Restarts 1 and 2 show no such artefact — every controller message there matched a real valve
state, because in both cases the zones genuinely changed at different moments and no
coalescing was needed.

## 8. Temperature and `atTemp`

### 8a. No temperature drift across three restores

| | before | after |
|---|---|---|
| Restart 1 | `383` (38.3 °C, 101 °F) | **`383`** |
| Restart 2 | `377` (37.7 °C, 100 °F) | **`377`** |
| Restart 3 | `366` (36.6 °C, 98 °F) | **`366`** |

Byte-exact, three for three, at three different setpoints. A clean negative result against the
whole-degree jump reported in session 9 §2b. The pause word also carries the same setpoint as
the word before it, so the pause itself disturbs nothing.

### 8b. `atTemp` survives a pause and clears only on a full stop

| | during pause | after restore |
|---|---|---|
| Restart 1 | `v1` untouched, atTemp set | set |
| Restart 2 | `0579C840` — **atTemp still set while paused** | **cleared** at the `00/00`, returns 0.860 s after the restore |
| Restart 3 | `056EC840` / `116EC840` — atTemp set on both | set |

The one clearing is at the `00/00` — mask zero with **no** pause flag — and again at the
16:29:49 manual stop.

**So the bit tracks "the system is active", not "the water is at the setpoint".** Combined with
[case study 4](04_two_touchscreens_and_what_off_means.md), where it did not move across sixteen
setpoint changes and a 7 °F swing, the owner's reading looks right: **`atTemp` is most likely
how the system decides whether to run warm-up, and is not a mid-session temperature check.**

## 9. The two-minute hold, from the whole corpus

Prompted by this session, every `0x40` pause in the corpus was classified by what happened
next. **29 of the 38 teardowns land at 119.6–120.7 s.**

| start route (clean sessions only) | sessions | pauses | teardown | resumed |
|---|---|---|---|---|
| `solowritesystem` | 10 | 7 | 1 | 6 |
| GCS preset | 5 | 5 | 3 | 1 |
| HUB `valveOnOff` | 7 | 8 | 2 | 6 |

**A pause left alone is held for two minutes and then torn down** — the session ends and the
setpoint reverts to `defaultTemp`. Route-independent, `cfgW`-independent, seen across every
date from 08-07 to 08-18. This is the same mechanism as case study 4's 119.19 s and this
session's 119.03 s setpoint reversion after the 16:29:49 stop.

**Start route does not predict the teardown.** Whether one happens is decided by whether
anyone resumes first.

## 10. ❌ What we could NOT determine

> ### ✅ RESOLVED — 2026-08-19, [case study 7 §7a](07_the_controller_sweeps.md)
>
> **It was the controller's 900 s ceiling.** The `00/00` landed **900.792 s** after zone 1 began
> flowing, inside the +900.30…+901.16 s band measured across seven controller cuts with the valve
> held inert at 60 min. The objection below — that a HUB clock would predict stops at restarts 1
> and 3 too — does not hold: the controller's per-zone arming is unreliable (zone 1 armed 1 of 4
> there), which §7 of this study had already established from the other direction.
>
> **Why zone 2 was zeroed at 492 s:** the cut is a **sweep** over both zones, and zone 2's
> *controller* clock was never reset by our restore — only its valve clock was. The sweep saw zone 2
> at 1393.5 s. Both zones over limit, both cut, one word.
>
> The `configWriteAllowedFlag` argument in §11 is also falsified: the same word-identical `cfgW`
> precursor appears 0.117 s and 0.224 s ahead of stops the controller provably authored.
>
> The knock-on is unchanged — the `00/00` still merged both clocks and still caused restart 3.


**Why the `00/00` appeared at restart 2.** This is the one real failure of the session, and it
resisted every hypothesis tested:

* **Not the controller's ceiling.** A HUB clock anchored anywhere in this session predicts a
  stop at restart 1 and restart 3 as well; neither happened.
* **Not `configWriteAllowedFlag` causing it.** Case study 4 held at `cfgW=1` for 119 s without
  a teardown.
* **Not "the primary cannot be held while the secondary runs".** The corpus has **13** pauses
  with exactly that shape; only **two** tore down promptly. 08-17 18:13:08 and 18:28:10 are the
  same configuration with no teardown at all.
* **Not the start route.** Short teardowns occur on all three routes.
* **Not "the other zone was running".** Five of the nine short teardowns had no other zone
  running.

What is left is a population of **nine sub-60-second teardowns** — 0.767, 0.875, 0.971, 1.087,
1.326, 5.263, 5.423, 36.0, 50.0 s — against 29 at ~120 s. Seven of the nine fall in the
2026-08-13/14 flow-experiment era; **only two are from clean sessions, and both immediately
follow an Endless Shower restore.** That is the thread worth pulling, and it is not pulled here.

**No test in this session distinguishes the candidates, and none of the tested hypotheses
survived. Recorded as unexplained.**

## 11. Corrections to earlier case studies

### ⚠️ Case study 3's `00/00` attribution is RETRACTED

[Case study 3](03_both_ceilings_at_15_minutes.md) §4 attributed the `00/00` at 14:35:17.521 to
the controller's 15-minute ceiling, on the strength of it landing +1.004 s past a 900 s
deadline. **That should not be relied on.**

It now sits in the population above as a **+1.087 s short teardown**, alongside eight others
spanning three start routes and eleven days — including restart 2 here, where no controller
deadline existed at that moment. The `configWriteAllowedFlag` evidence points to the valve:
`cfgW` is a field the valve reports about *itself*, the controller cannot set it, and at
restart 2 it changed **before** the `00/00` while the word was otherwise identical.

**Both are most likely the same valve-side teardown.** Case study 3's §4 subsection "The `0x00`
at 14:35:17.521 is the controller's, not ours" is superseded by this section. Its other
conclusions — both ceilings firing 1.087 s apart, the restore winning the race, the
ordering-dependence — are unaffected, because they rest on the `0x40` and the timings, not on
who sent the `0x00`.

### The restore's side effect was not previously documented

That restoring one zone can re-anchor the **other** zone's run-time clock is new here, and it
is what makes restart 3 an artefact of restart 2 rather than an independent event.

## 12. Open

1. ~~**The unexplained `00/00`** (§10)~~ — **CLOSED 2026-08-19**, the controller's ceiling
   fired as a sweep. See [case study 7 §7a](07_the_controller_sweeps.md).
2. **Why individual zone tracking staggers** (§7) — controller pipeline lag, or the controller
   seeing finer detail over the wired link than the valve's coalesced cloud publish.
3. **A genuine max-duration `0x40` left alone**, with Endless Shower off, to watch the hold play
   out unprompted. Every real cutoff in the corpus was restored within ~2 s.
4. **How this session was started** (§1) — needed for provenance.
5. Carried: whether the controller counts an HA-started session; whether a GCS preset starts
   its clock; `warmupmode: "pause"` still unexercised.

## 13. Provenance

| Fact | Source |
|---|---|
| Every hex word, timestamp, message count | `mqtt_raw_20260818T224105Z_71_0d8d74e5.jsonl` — read in full |
| Cutoff verdicts, durations, restore fields | `cutoff_20260818T224105Z_71_74bf20b2.jsonl` — read in full |
| GCS `maximumRunTime` = 900 s | `"limits":[900]` on every journal event |
| The words Home Assistant sent | reproduced by running `anthem_plus.valve_hex.encode_word` against the captured state |
| `cfgW` meaning, 1446-message correlation | all 89 capture files, scripted analysis |
| The 120 s hold, 38 teardowns, route breakdown | all 89 capture files, scripted analysis |
| How the session was started | **owner-reported** — Home Assistant outlet switches; the first-gen screen was not used that day |

---

## Appendix A — every raw record of the session

**Window: the whole of `mqtt_raw_20260818T224105Z_71_0d8d74e5.jsonl` and `cutoff_20260818T224105Z_71_74bf20b2.jsonl`** — from the integration arming at 15:41:06 through
the final setpoint reversion at 16:31:49 local. Both files are reproduced in their entirety;
nothing is excluded.

### A.1 — raw MQTT, verbatim (62 records)

Lines exactly as written by `RawLog.write()`, with **one substitution**: the real `tenantid`
is replaced by `<TENANT_ID>` per the placeholder policy in [`../README.md`](../README.md).
Device ids are left in place. Nothing else is altered.

**15:51:00.260 local** — line 1 — VALVE — v1=0184C80000000001 v2=1184C80100000001 cfgW=1

```json
{"ts":"2026-08-18T22:51:00.260323Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=1","qos":0,"retain":false,"payload":"{\"messageid\":\"4E495AA9-0F42-2674-9B6F-4A299B940FF9\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787093471\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"14694\",\"totalVolume\":\"1679964706\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:51:00.800 local** — line 2 — CONTROLLER — z1=OFF z2=ON

```json
{"ts":"2026-08-18T22:51:00.800569Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=2","qos":0,"retain":false,"payload":"{\"messageid\":\"0d62ae01-dd83-449c-8dd3-d17973136cce\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787093460\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:51:03.625 local** — line 3 — VALVE — v1=0584C80000000001 v2=1184C80100000001 cfgW=1

```json
{"ts":"2026-08-18T22:51:03.625793Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=3","qos":0,"retain":false,"payload":"{\"messageid\":\"E4ADB7B8-7953-EF64-8595-86E5FBF069DC\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787093475\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1658\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:59:12.974 local** — line 4 — VALVE — v1=0584C80400000001 v2=1184C80100000001 cfgW=0

```json
{"ts":"2026-08-18T22:59:12.974340Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=4","qos":0,"retain":false,"payload":"{\"messageid\":\"87F8DE31-2AEE-3AD4-933D-1370F6B5323E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787093964\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0584c80400000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:59:13.441 local** — line 5 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:59:13.441099Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=5","qos":0,"retain":false,"payload":"{\"messageid\":\"c4e2a6bb-7230-4c3b-9cf4-0dbf5d83c15c\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787093953\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**15:59:18.781 local** — line 6 — VALVE — v1=0584C80500000001 v2=1184C80100000001 cfgW=0

```json
{"ts":"2026-08-18T22:59:18.781686Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=6","qos":0,"retain":false,"payload":"{\"messageid\":\"69FAB080-5FDC-2AB4-BF70-D4D5D31746B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787093970\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1655\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0584c80500000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**15:59:19.123 local** — line 7 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T22:59:19.123495Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=7","qos":0,"retain":false,"payload":"{\"messageid\":\"827a700c-21b4-4a6f-959a-a1eb08c3cf23\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787093958\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:04:01.587 local** — line 8 — VALVE — v1=0584C80100000001 v2=1184C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:04:01.587178Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=8","qos":0,"retain":false,"payload":"{\"messageid\":\"EC95E5A8-48B6-C474-B245-0B83EB62D8CF\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094253\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0584c80100000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:04:02.052 local** — line 9 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:04:02.052491Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=9","qos":0,"retain":false,"payload":"{\"messageid\":\"80dcb2a2-909d-4e0c-9ea9-54abc6a45cd9\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094241\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:04:19.326 local** — line 10 — VALVE — v1=057FC80100000001 v2=117FC80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:04:19.326249Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=10","qos":0,"retain":false,"payload":"{\"messageid\":\"F80B856C-6E34-06D4-9953-4BA9ADFC34B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094271\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"057fc80100000001\",\"secondaryValve1\":\"117fc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:04:19.950 local** — line 11 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:04:19.950326Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=11","qos":0,"retain":false,"payload":"{\"messageid\":\"04b0aea6-16ca-42cc-bf22-c3b3fd328d9f\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094259\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:06:00.114 local** — line 12 — VALVE — v1=057FC80100000001 v2=117FC84000000001 cfgW=0

```json
{"ts":"2026-08-18T23:06:00.114076Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=12","qos":0,"retain":false,"payload":"{\"messageid\":\"4430ACBA-83A7-3394-B5F8-D07AFB682C2A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094371\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"057fc80100000001\",\"secondaryValve1\":\"117fc84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:06:00.789 local** — line 13 — CONTROLLER — z1=ON z2=OFF

```json
{"ts":"2026-08-18T23:06:00.789594Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=13","qos":0,"retain":false,"payload":"{\"messageid\":\"0eaf2355-9a4e-4f36-ae6b-26ee073ae74f\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094360\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:06:01.552 local** — line 14 — VALVE — v1=057FC80100000001 v2=117FC80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:06:01.552129Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=14","qos":0,"retain":false,"payload":"{\"messageid\":\"168B6635-8380-63A4-9DD3-3FF4E692E177\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094373\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"25392\",\"totalVolume\":\"958544418\",\"primaryValve1\":\"057fc80100000001\",\"secondaryValve1\":\"117fc80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:06:01.907 local** — line 15 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:06:01.907056Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=15","qos":0,"retain":false,"payload":"{\"messageid\":\"81fe6381-bff4-46b0-b9e9-05ba758ffab2\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094361\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:07:39.012 local** — line 16 — VALVE — v1=057FC80100000001 v2=117FC80300000001 cfgW=0

```json
{"ts":"2026-08-18T23:07:39.012232Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=16","qos":0,"retain":false,"payload":"{\"messageid\":\"2D4EC44F-1297-7E94-B0CE-59FA0BA4D40A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094470\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1657\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"057fc80100000001\",\"secondaryValve1\":\"117fc80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:07:39.308 local** — line 17 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:07:39.308031Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=17","qos":0,"retain":false,"payload":"{\"messageid\":\"25b86c3e-39e7-4b5e-9fb2-57590a5f1c95\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094458\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:07:39.635 local** — line 18 — VALVE — v1=057FC80100000001 v2=117FC80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:07:39.635000Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=18","qos":0,"retain":false,"payload":"{\"messageid\":\"8504309F-8525-38B4-A4BB-8255AF85CEEE\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094471\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"057fc80100000001\",\"secondaryValve1\":\"117fc80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:07:39.965 local** — line 19 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:07:39.965016Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=19","qos":0,"retain":false,"payload":"{\"messageid\":\"65ebf7a7-82e6-4f65-8db8-48b2fef7b97d\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094459\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:07:51.249 local** — line 20 — VALVE — v1=057FC80500000001 v2=117FC80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:07:51.249408Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=20","qos":0,"retain":false,"payload":"{\"messageid\":\"482C0C83-6ABF-8E84-9E15-48ADABB10C56\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094482\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"057fc80500000001\",\"secondaryValve1\":\"117fc80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:07:51.479 local** — line 21 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:07:51.479652Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=21","qos":0,"retain":false,"payload":"{\"messageid\":\"a189e0f5-7f7a-4e0b-abbd-f10c3f1f5f50\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094471\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":101,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":101,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:09:05.049 local** — line 22 — VALVE — v1=0579C80500000001 v2=1179C80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:09:05.049925Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=22","qos":0,"retain":false,"payload":"{\"messageid\":\"29EF1DF3-D6F1-D2D4-BB79-52A2F88A4AF6\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094556\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0579c80500000001\",\"secondaryValve1\":\"1179c80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:09:05.387 local** — line 23 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:09:05.387839Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=23","qos":0,"retain":false,"payload":"{\"messageid\":\"2c5421ae-6ddf-4f60-8c37-d7b21236305c\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094544\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:14:12.891 local** — line 24 — VALVE — v1=0579C84000000001 v2=1179C80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:14:12.891957Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=24","qos":0,"retain":false,"payload":"{\"messageid\":\"B8FF2E2C-F63A-E444-ADD6-064639AC9042\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094864\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1655\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c84000000001\",\"secondaryValve1\":\"1179c80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:14:13.313 local** — line 25 — CONTROLLER — z1=OFF z2=ON

```json
{"ts":"2026-08-18T23:14:13.313651Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=25","qos":0,"retain":false,"payload":"{\"messageid\":\"cb6edf5b-f449-4dac-bd1a-268f2d8eed4d\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094852\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:14:13.643 local** — line 26 — VALVE — v1=0579C84000000001 v2=1179C80200000001 cfgW=1

```json
{"ts":"2026-08-18T23:14:13.643184Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=26","qos":0,"retain":false,"payload":"{\"messageid\":\"465494C6-C1EE-C764-B4DF-67580D0D37A1\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094865\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c84000000001\",\"secondaryValve1\":\"1179c80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:14:13.766 local** — line 27 — VALVE — v1=0179C80000000001 v2=1179C80000000001 cfgW=1

```json
{"ts":"2026-08-18T23:14:13.766876Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=27","qos":0,"retain":false,"payload":"{\"messageid\":\"E5B54036-11E0-DAB4-9939-955C953EE0E7\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094865\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0179c80000000001\",\"secondaryValve1\":\"1179c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:14:14.207 local** — line 28 — VALVE — v1=0179C80500000001 v2=1179C80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:14:14.207842Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=28","qos":0,"retain":false,"payload":"{\"messageid\":\"F4D8AA30-66BB-F1D4-A30F-D205EDC5BE7E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094865\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1\",\"totalVolume\":\"269422000\",\"primaryValve1\":\"0179c80500000001\",\"secondaryValve1\":\"1179c80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:14:14.224 local** — line 29 — CONTROLLER — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T23:14:14.224237Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=29","qos":0,"retain":false,"payload":"{\"messageid\":\"97076249-9cc5-480e-86d4-64ef98e79a89\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094853\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:14:14.664 local** — line 30 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:14:14.664055Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=30","qos":0,"retain":false,"payload":"{\"messageid\":\"16a9a218-e7f4-45be-8733-cfdc4c78ac82\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094854\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:14:15.067 local** — line 31 — VALVE — v1=0579C80500000001 v2=1179C80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:14:15.067437Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=31","qos":0,"retain":false,"payload":"{\"messageid\":\"0B8018AF-CB35-9B74-9B36-5CD71790824B\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094866\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c80500000001\",\"secondaryValve1\":\"1179c80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:15:03.122 local** — line 32 — VALVE — v1=0579C80500000001 v2=1179C80300000001 cfgW=0

```json
{"ts":"2026-08-18T23:15:03.122322Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=32","qos":0,"retain":false,"payload":"{\"messageid\":\"DE90398B-BB45-31F4-B661-2DB319D079C3\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094914\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c80500000001\",\"secondaryValve1\":\"1179c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:15:03.405 local** — line 33 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:15:03.405692Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=33","qos":0,"retain":false,"payload":"{\"messageid\":\"ac801bfc-e21f-4602-b367-d168a7dd741e\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094903\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:15:04.298 local** — line 34 — VALVE — v1=0579C80500000001 v2=1179C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:15:04.298694Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=34","qos":0,"retain":false,"payload":"{\"messageid\":\"5E9490A6-88A2-C384-9BBA-8A0B219212A5\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094916\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c80500000001\",\"secondaryValve1\":\"1179c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:15:04.748 local** — line 35 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:15:04.748009Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=35","qos":0,"retain":false,"payload":"{\"messageid\":\"4f4466de-90e3-4030-bfe0-e9dc7be0acf8\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094904\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:15:08.136 local** — line 36 — VALVE — v1=0579C80400000001 v2=1179C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:15:08.136902Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=36","qos":0,"retain":false,"payload":"{\"messageid\":\"4A4093F4-E2B5-7804-9A3D-CB793072A3CD\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094919\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c80400000001\",\"secondaryValve1\":\"1179c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:15:08.223 local** — line 37 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:15:08.223979Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=37","qos":0,"retain":false,"payload":"{\"messageid\":\"de5d3a22-ea3c-42f5-800a-734d7dcd27ec\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094907\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:15:09.907 local** — line 38 — VALVE — v1=0579C80600000001 v2=1179C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:15:09.907935Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=38","qos":0,"retain":false,"payload":"{\"messageid\":\"B10AE378-F0AF-8044-BF10-FEF90D3A7BB5\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094921\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0579c80600000001\",\"secondaryValve1\":\"1179c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:15:10.302 local** — line 39 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:15:10.302277Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=39","qos":0,"retain":false,"payload":"{\"messageid\":\"e7792334-de80-4020-995b-6604f9728c74\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094909\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":100,\"flowrate\":100,\"outlets\":[0,1,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":100,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:15:55.420 local** — line 40 — VALVE — v1=0574C80600000001 v2=1174C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:15:55.420120Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=40","qos":0,"retain":false,"payload":"{\"messageid\":\"A3E8D92E-BE0A-3704-9097-C309E12B4D36\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787094967\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0574c80600000001\",\"secondaryValve1\":\"1174c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:15:56.007 local** — line 41 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:15:56.007228Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=41","qos":0,"retain":false,"payload":"{\"messageid\":\"f5f91b22-65e3-4b8c-a98e-e23e837493d5\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787094955\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":99,\"flowrate\":100,\"outlets\":[0,1,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:25:30.502 local** — line 42 — VALVE — v1=0574C80400000001 v2=1174C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:25:30.502998Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=42","qos":0,"retain":false,"payload":"{\"messageid\":\"6679D2FC-FF72-6F74-8D9E-125219A34F9E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095542\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0574c80400000001\",\"secondaryValve1\":\"1174c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:25:30.951 local** — line 43 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:25:30.951518Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=43","qos":0,"retain":false,"payload":"{\"messageid\":\"5d30ed6a-ac29-47d6-945d-a676ce5d97d5\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095530\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":99,\"flowrate\":100,\"outlets\":[0,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:25:32.136 local** — line 44 — VALVE — v1=0574C80500000001 v2=1174C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:25:32.136568Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=44","qos":0,"retain":false,"payload":"{\"messageid\":\"4E495AA9-0F42-2674-9B6F-4A299B940FF9\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095543\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1655\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0574c80500000001\",\"secondaryValve1\":\"1174c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:25:32.596 local** — line 45 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:25:32.596235Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=45","qos":0,"retain":false,"payload":"{\"messageid\":\"40ceabad-b157-49f9-a8f2-573f6dc089d6\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095532\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:25:34.539 local** — line 46 — VALVE — v1=0574C80100000001 v2=1174C80100000001 cfgW=0

```json
{"ts":"2026-08-18T23:25:34.539629Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=46","qos":0,"retain":false,"payload":"{\"messageid\":\"E4ADB7B8-7953-EF64-8595-86E5FBF069DC\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095546\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0574c80100000001\",\"secondaryValve1\":\"1174c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:25:34.896 local** — line 47 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:25:34.896484Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=47","qos":0,"retain":false,"payload":"{\"messageid\":\"d1f1bc35-920b-4926-9113-106380a4452c\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095534\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:25:39.782 local** — line 48 — VALVE — v1=0574C80100000001 v2=1174C80300000001 cfgW=0

```json
{"ts":"2026-08-18T23:25:39.782782Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=48","qos":0,"retain":false,"payload":"{\"messageid\":\"5E42A70F-9892-2E34-8804-D4C1C50AB0AE\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095551\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0574c80100000001\",\"secondaryValve1\":\"1174c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:25:40.296 local** — line 49 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:25:40.296762Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=49","qos":0,"retain":false,"payload":"{\"messageid\":\"28395d8b-3845-423e-b9df-64c2cc400de6\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095539\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:25:41.216 local** — line 50 — VALVE — v1=0574C80100000001 v2=1174C80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:25:41.216851Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=50","qos":0,"retain":false,"payload":"{\"messageid\":\"87F8DE31-2AEE-3AD4-933D-1370F6B5323E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095552\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0574c80100000001\",\"secondaryValve1\":\"1174c80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:25:41.447 local** — line 51 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:25:41.447828Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=51","qos":0,"retain":false,"payload":"{\"messageid\":\"9348dd0c-c489-42b8-818f-63cc437f5a34\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095541\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":99,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":99,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:25:54.252 local** — line 52 — VALVE — v1=056EC80100000001 v2=116EC80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:25:54.252273Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=52","qos":0,"retain":false,"payload":"{\"messageid\":\"69FAB080-5FDC-2AB4-BF70-D4D5D31746B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095565\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"056ec80100000001\",\"secondaryValve1\":\"116ec80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:25:54.591 local** — line 53 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:25:54.591036Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=53","qos":0,"retain":false,"payload":"{\"messageid\":\"42849f19-0edb-4fa3-9b01-a35c362bad8e\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095554\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":98,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":98,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:29:14.048 local** — line 54 — VALVE — v1=056EC84000000001 v2=116EC84000000001 cfgW=0

```json
{"ts":"2026-08-18T23:29:14.048960Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=54","qos":0,"retain":false,"payload":"{\"messageid\":\"EC95E5A8-48B6-C474-B245-0B83EB62D8CF\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095765\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1656\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"056ec84000000001\",\"secondaryValve1\":\"116ec84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:29:14.446 local** — line 55 — CONTROLLER — z1=OFF z2=ON

```json
{"ts":"2026-08-18T23:29:14.446040Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=55","qos":0,"retain":false,"payload":"{\"messageid\":\"668f5828-fb5d-4c32-937d-adee336ead91\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095753\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":98,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:29:14.647 local** — line 56 — CONTROLLER — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T23:29:14.647121Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=56","qos":0,"retain":false,"payload":"{\"messageid\":\"21cb15e6-8aa1-452a-bace-9fc6d5e0d30c\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095754\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:29:15.728 local** — line 57 — VALVE — v1=056EC80100000001 v2=116EC80200000001 cfgW=0

```json
{"ts":"2026-08-18T23:29:15.728674Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=57","qos":0,"retain":false,"payload":"{\"messageid\":\"F80B856C-6E34-06D4-9953-4BA9ADFC34B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095767\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"26164\",\"totalVolume\":\"824326690\",\"primaryValve1\":\"056ec80100000001\",\"secondaryValve1\":\"116ec80200000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:29:16.114 local** — line 58 — CONTROLLER — z1=ON z2=ON

```json
{"ts":"2026-08-18T23:29:16.114070Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=58","qos":0,"retain":false,"payload":"{\"messageid\":\"0f7dcb9e-69c8-4463-890f-c60794e7634e\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095755\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":98,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":98,\"flowrate\":100,\"outlets\":[0,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:29:49.680 local** — line 59 — VALVE — v1=016EC80000000001 v2=116EC80000000001 cfgW=1

```json
{"ts":"2026-08-18T23:29:49.680052Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=59","qos":0,"retain":false,"payload":"{\"messageid\":\"4430ACBA-83A7-3394-B5F8-D07AFB682C2A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095801\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1657\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"016ec80000000001\",\"secondaryValve1\":\"116ec80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:29:49.993 local** — line 60 — CONTROLLER — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T23:29:49.993149Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=60","qos":0,"retain":false,"payload":"{\"messageid\":\"8343028e-010a-44cc-a792-6520c440d6a5\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095789\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**16:31:48.713 local** — line 61 — VALVE — v1=0184C80000000001 v2=1184C80000000001 cfgW=1

```json
{"ts":"2026-08-18T23:31:48.713544Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=61","qos":0,"retain":false,"payload":"{\"messageid\":\"2D4EC44F-1297-7E94-B0CE-59FA0BA4D40A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787095920\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**16:31:49.120 local** — line 62 — CONTROLLER — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T23:31:49.120189Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=62","qos":0,"retain":false,"payload":"{\"messageid\":\"9c6c9c44-f55a-455e-912f-8a0e99228a77\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787095908\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

### A.2 — cutoff journal, verbatim (43 records)

The file in its entirety. The three `restore` / `restore_done` pairs are restarts 1, 2 and 3;
the `setting_change` entries are setpoint and outlet adjustments between them.

```json
{"ts":"2026-08-18T22:41:06.889087Z","event":"arm","enabled":true,"run_times":{"1":900,"2":900,"3":900,"4":900,"5":900,"6":900},"awaiting":[],"zone_limits":{"1":[900],"2":[900]}}
{"ts":"2026-08-18T22:51:00.260991Z","event":"flow_start","zone":2,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:59:12.974874Z","event":"flow_start","zone":1,"mask":4,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T22:59:18.782235Z","event":"mask_change","zone":1,"mask":5,"was":4,"flowing_for":5.81,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T23:04:01.587752Z","event":"mask_change","zone":1,"mask":1,"was":5,"flowing_for":288.61,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T23:04:19.326784Z","event":"setting_change","zone":1,"mask":1,"flowing_for":306.35,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T23:04:19.326888Z","event":"setting_change","zone":2,"mask":1,"flowing_for":799.07,"was_flow_percent":100.0,"was_temperature_f":101.8,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T23:06:00.114640Z","event":"flow_end","zone":2,"duration":899.85,"limits":[900],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":100.9,"verdict":"cutoff","matched":900}
{"ts":"2026-08-18T23:06:00.114846Z","event":"restore","zones":[2],"also_paused":[],"masks":{"1":1,"2":1},"from_detector":{"2":1},"from_snapshot":{"1":1,"2":1},"was_flow_percent":{"2":100.0},"was_temperature_f":{"2":100.9},"writing_flow_percent":{"2":100.0},"flow_preserved":true}
{"ts":"2026-08-18T23:06:00.945709Z","event":"restore_done","outlets":[1,4],"write_seconds":0.83}
{"ts":"2026-08-18T23:06:01.552654Z","event":"flow_start","zone":2,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T23:07:39.012789Z","event":"mask_change","zone":2,"mask":3,"was":1,"flowing_for":97.46,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T23:07:39.635526Z","event":"mask_change","zone":2,"mask":2,"was":3,"flowing_for":98.08,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T23:07:51.249985Z","event":"mask_change","zone":1,"mask":5,"was":1,"flowing_for":518.28,"flow_percent":100.0,"temperature_f":100.9}
{"ts":"2026-08-18T23:09:05.050482Z","event":"setting_change","zone":1,"mask":5,"flowing_for":592.08,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:09:05.050620Z","event":"setting_change","zone":2,"mask":2,"flowing_for":183.5,"was_flow_percent":100.0,"was_temperature_f":100.9,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:14:12.892494Z","event":"flow_end","zone":1,"duration":899.92,"limits":[900],"mask":5,"paused":true,"flow_percent":100.0,"temperature_f":99.9,"verdict":"cutoff","matched":900}
{"ts":"2026-08-18T23:14:12.892707Z","event":"restore","zones":[1],"also_paused":[],"masks":{"1":5,"2":2},"from_detector":{"1":5},"from_snapshot":{"1":5,"2":2},"was_flow_percent":{"1":100.0},"was_temperature_f":{"1":99.9},"writing_flow_percent":{"1":100.0},"flow_preserved":true}
{"ts":"2026-08-18T23:14:13.527605Z","event":"restore_done","outlets":[1,3,5],"write_seconds":0.64}
{"ts":"2026-08-18T23:14:13.767414Z","event":"flow_end","zone":2,"duration":492.21,"limits":[900],"mask":2,"paused":false,"flow_percent":100.0,"temperature_f":99.9,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":407.79}
{"ts":"2026-08-18T23:14:14.208307Z","event":"flow_start","zone":1,"mask":5,"limits":[900],"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:14:14.208392Z","event":"flow_start","zone":2,"mask":2,"limits":[900],"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:15:03.122850Z","event":"mask_change","zone":2,"mask":3,"was":2,"flowing_for":48.91,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:15:04.299202Z","event":"mask_change","zone":2,"mask":1,"was":3,"flowing_for":50.09,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:15:08.137414Z","event":"mask_change","zone":1,"mask":4,"was":5,"flowing_for":53.93,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:15:09.908360Z","event":"mask_change","zone":1,"mask":6,"was":4,"flowing_for":55.7,"flow_percent":100.0,"temperature_f":99.9}
{"ts":"2026-08-18T23:15:55.420691Z","event":"setting_change","zone":1,"mask":6,"flowing_for":101.21,"was_flow_percent":100.0,"was_temperature_f":99.9,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:15:55.420799Z","event":"setting_change","zone":2,"mask":1,"flowing_for":101.21,"was_flow_percent":100.0,"was_temperature_f":99.9,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:25:30.503488Z","event":"mask_change","zone":1,"mask":4,"was":6,"flowing_for":676.3,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:25:32.137102Z","event":"mask_change","zone":1,"mask":5,"was":4,"flowing_for":677.93,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:25:34.540139Z","event":"mask_change","zone":1,"mask":1,"was":5,"flowing_for":680.33,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:25:39.783325Z","event":"mask_change","zone":2,"mask":3,"was":1,"flowing_for":685.58,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:25:41.217400Z","event":"mask_change","zone":2,"mask":2,"was":3,"flowing_for":687.01,"flow_percent":100.0,"temperature_f":99.0}
{"ts":"2026-08-18T23:25:54.252794Z","event":"setting_change","zone":1,"mask":1,"flowing_for":700.04,"was_flow_percent":100.0,"was_temperature_f":99.0,"flow_percent":100.0,"temperature_f":97.9}
{"ts":"2026-08-18T23:25:54.252896Z","event":"setting_change","zone":2,"mask":2,"flowing_for":700.04,"was_flow_percent":100.0,"was_temperature_f":99.0,"flow_percent":100.0,"temperature_f":97.9}
{"ts":"2026-08-18T23:29:14.049473Z","event":"flow_end","zone":1,"duration":899.84,"limits":[900],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":97.9,"verdict":"cutoff","matched":900}
{"ts":"2026-08-18T23:29:14.049607Z","event":"flow_end","zone":2,"duration":899.84,"limits":[900],"mask":2,"paused":true,"flow_percent":100.0,"temperature_f":97.9,"verdict":"cutoff","matched":900}
{"ts":"2026-08-18T23:29:14.049773Z","event":"restore","zones":[1,2],"also_paused":[],"masks":{"1":1,"2":2},"from_detector":{"1":1,"2":2},"from_snapshot":{"1":1,"2":2},"was_flow_percent":{"1":100.0,"2":100.0},"was_temperature_f":{"1":97.9,"2":97.9},"writing_flow_percent":{"1":100.0,"2":100.0},"flow_preserved":true}
{"ts":"2026-08-18T23:29:14.991040Z","event":"restore_done","outlets":[1,5],"write_seconds":0.94}
{"ts":"2026-08-18T23:29:15.729526Z","event":"flow_start","zone":1,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":97.9}
{"ts":"2026-08-18T23:29:15.729641Z","event":"flow_start","zone":2,"mask":2,"limits":[900],"flow_percent":100.0,"temperature_f":97.9}
{"ts":"2026-08-18T23:29:49.680563Z","event":"flow_end","zone":1,"duration":33.95,"limits":[900],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":97.9,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":866.05}
{"ts":"2026-08-18T23:29:49.680680Z","event":"flow_end","zone":2,"duration":33.95,"limits":[900],"mask":2,"paused":false,"flow_percent":100.0,"temperature_f":97.9,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":866.05}
```
