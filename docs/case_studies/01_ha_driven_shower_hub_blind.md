# Case study 1 — an 86-minute shower the Anthem Plus never knew about

**2026-08-18. One shower, five MQTT messages, four control events, three different
commanders — and a controller that sat through the whole thing believing nothing was
happening.**

This is the reference case for what changes when Home Assistant drives the valve directly.
It is short enough to quote in full, every event is attributed, and it settles an open
question that had no data behind it since 2026-08-17.

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

> **The headline.** The Anthem Plus controller did not know the shower was on — not at the
> start, not through 86 minutes of running water, not when the valve paused it at its own
> 60-minute limit, and not when Home Assistant restarted it. Both devices had a 60-minute
> maximum shower duration configured. **Neither the controller's ceiling nor its awareness
> ever engaged.** The controller published **zero** MQTT messages for the entire session.
>
> **And the connection was healthy the whole time** — one unbroken MQTT session carrying both
> devices, with the valve's own messages arriving on it at the very moments the controller
> should have spoken, and the controller itself alive enough to end the shower from its own
> touchscreen. Nothing was broken. It simply had nothing to report. See [§6a](#-6a-the-connection-was-healthy-the-whole-time).

---

## 1. Configuration at the time

| Setting | Where | Value |
|---|---|---|
| **GCS max shower duration** (`maximumRunTime`) | Anthem valve, per outlet | **3600 s = 60 min**, all six outlets |
| **HUB max shower duration** | Anthem Plus controller | **60 min** |
| Endless Shower (run-time cutoff restart) | Integration option | **Enabled** |
| Valve model | — | K-28212, 6 outlets, 3 + 3 |
| Flow ceiling | `maximumFlowRate`, all outlets | `0xC8` (200) — so 100% is the true full scale |

**Both maximums were deliberately set to the same 60 minutes.** That was the mitigation
adopted after [session 9](../handoff/2026-08-17_session9_current.md) §1, where a GCS limit of
900 s underneath a HUB limit of 3600 s let the controller's longer clock expire mid-leg and
stop a shower still in use. This session is the first run with them matched.

The GCS value is not asserted from memory — the cutoff journal records it at arm time:

```json
{"ts":"2026-08-18T05:20:56.577954Z","event":"arm","enabled":true,
 "run_times":{"1":3600,"2":3600,"3":3600,"4":3600,"5":3600,"6":3600},
 "awaiting":[],"zone_limits":{"1":[3600],"2":[3600]}}
```

The HUB's 60 minutes is its configured Max Shower Duration, carried from session 9 §0a. It
is **not independently re-verified in this capture** — that value still appears in no
readable endpoint, which remains an open item.

## 2. Who commanded what

Four control events, three commanders. The attribution is **owner-reported**; the capture
corroborates the shape of each but cannot name a commander on its own.

| # | Local time | Event | Commanded by | Reaches the valve via |
|---|---|---|---|---|
| 1 | 07:52:01 | zone 2 opens, outlet 4 | **Home Assistant** | `solowritesystem` — direct, HUB not party |
| 2 | 08:52:00 | zone 2 paused, `0x40` | **the GCS valve itself** | internal — its own `maximumRunTime` expiring |
| 3 | 08:52:02 | zone 2 restarted | **Home Assistant** | `solowritesystem` — direct, HUB not party |
| 4 | 09:18:13 | shower ended, `0x00`/`0x00` | **the Anthem Plus touchscreen** | panel → HUB → valve |

Event 4 is the one that makes this case study worth keeping: **the controller commanded the
stop, so it was powered, functional and reachable** — and it still published nothing.

## 3. The complete capture

Every MQTT message received during the session. This is the whole file, not an excerpt:
`/config/kohler_anthem_plus_raw/mqtt_raw_20260818T052055Z_71_0b22dd90.jsonl`, 5 lines.

Summarised here for reading; the **complete unedited records, plus the full hour either side
of the session, are in [Appendix A](#appendix-a--every-raw-record-one-hour-either-side)**.

```text
UTC                    local           primaryValve1  secondaryValve1  totalFlow  totalVolume
2026-08-18T14:52:01.179971Z  07:52:01.179  0184C800       1184C801           24931   874658338
2026-08-18T14:52:45.891944Z  07:52:45.891  0584C800       1184C801            1657   536930912
2026-08-18T15:52:00.948159Z  08:52:00.948  0584C800       1184C840             477   536929728
2026-08-18T15:52:02.462454Z  08:52:02.462  0584C800       1184C801           25188  1713519138
2026-08-18T16:18:13.916459Z  09:18:13.916  0184C800       1184C800             477   536929728
```

All five are `sku: GCS`, `sysid: GCS-INJK966T6G`, `type: STS`, `code: GCS_SOLO_STS`, on
`$iothub/methods/POST/ExecuteControlCommand/?$rid=1..5`. Every other field
(`currentSystemState: normalOperation`, `warmUpStatus: warmUpNotInProgress`,
`presetOrExperienceId: 0`, `configChangeIndent: 4`, `secondaryValve2..7: 0000000000000000`)
is constant across all five.

> `totalFlow` and `totalVolume` are **not decoded** and behave inconsistently — both
> water-off messages carry `totalFlow 477` / `totalVolume 536929728`, but the two opens
> differ from each other by 2×. Recorded verbatim, not interpreted.

### Word by word

| Word | Zone | Decode |
|---|---|---|
| `0184C800` | 1 | `0x184` (388) = 38.8 °C = 102 °F · flow `0xC8` (200) = 100% · **mask `0x00`, closed** · atTemp clear |
| `0584C800` | 1 | same, **atTemp set** (byte 0 bit 2) — still mask `0x00`, still closed |
| `1184C801` | 2 | `0x184` (388) = 38.8 °C = 102 °F · flow `0xC8` (200) = 100% · **mask `0x01` = outlet 4 open** |
| `1184C840` | 2 | same temperature and flow · **mask cleared, pause flag `0x40` set** |
| `1184C800` | 2 | same temperature and flow · **mask `0x00`, no pause flag — a stop, not a pause** |

**Zone 1 was never open.** Its mask is `0x00` in all five messages. The only thing that ever
changed on zone 1 is the atTemp status bit the device sets for itself — byte 0 `0x01` → `0x05`
at 07:52:45 as the water came up to temperature, and back to `0x01` at the stop.

## 4. The timeline, with arithmetic

```text
07:52:01.179  HOME ASSISTANT starts the shower      solowritesystem
              -> 0184C800 / 1184C801                 zone 2 outlet 4, 102 F, 100%
              cutoff journal: flow_start zone 2, limits [3600]

07:52:45.891  valve reaches setpoint                 zone 1 byte 0: 0x01 -> 0x05 (atTemp)
              +44.71 s after the open. No command; device status only.

08:52:00.948  THE VALVE pauses zone 2                its own maximumRunTime, 3600 s
              -> 1184C840                            mask cleared, 0x40 set
              leg 1 = 3599.768 s   (limit 3600 s, 0.232 s early)

08:52:00.949  HOME ASSISTANT decides to restore      +0.4 ms — the decision is free
08:52:01.844  the solowritesystem write completes    write_seconds 0.9
08:52:02.462  THE VALVE confirms water back on
              -> 0584C800 / 1184C801                 byte-identical to the pre-pause state
              water off for 1.514 s

09:18:13.916  THE ANTHEM PLUS TOUCHSCREEN ends it    panel -> HUB -> valve
              -> 0184C800 / 1184C800                 both zones 0x00, no pause flag
              leg 2 = 1571.454 s  (26 m 11.5 s), matches no limit
```

| Quantity | Value |
|---|---|
| Leg 1 | 3599.768 s |
| Water-off gap during the restore | 1.514 s |
| Leg 2 | 1571.454 s |
| **Total wall clock** | **5172.736 s = 86 m 12.7 s** |
| **Total water flowing** | **5171.222 s = 86 m 11.2 s** |
| Where a 3600 s clock started at 07:52:01 would expire | **08:52:01.179 local** |

That last row is the whole finding. **A HUB clock anchored at the start would have fired at
08:52:01.179 — 0.23 s after our restore write went out and 1.28 s before the valve confirmed
water.** Nothing arrived. The shower then ran a further 26 minutes past its ceiling.

## 5. The cutoff journal, complete

`/config/kohler_anthem_plus_raw/cutoff_20260818T052055Z_71_c7d8362b.jsonl`, 7 lines:

```json
{"ts":"2026-08-18T05:20:56.577954Z","event":"arm","enabled":true,"run_times":{"1":3600,"2":3600,"3":3600,"4":3600,"5":3600,"6":3600},"awaiting":[],"zone_limits":{"1":[3600],"2":[3600]}}
{"ts":"2026-08-18T14:52:01.180650Z","event":"flow_start","zone":2,"mask":1,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T15:52:00.948731Z","event":"flow_end","zone":2,"duration":3599.77,"limits":[3600],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":101.8,"verdict":"cutoff","matched":3600}
{"ts":"2026-08-18T15:52:00.948956Z","event":"restore","zones":[2],"also_paused":[],"masks":{"1":0,"2":1},"from_detector":{"2":1},"from_snapshot":{"1":0,"2":1},"was_flow_percent":{"2":100.0},"was_temperature_f":{"2":101.8},"writing_flow_percent":{"2":100.0},"flow_preserved":true}
{"ts":"2026-08-18T15:52:01.844462Z","event":"restore_done","outlets":[4],"write_seconds":0.9}
{"ts":"2026-08-18T15:52:02.462964Z","event":"flow_start","zone":2,"mask":1,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T16:18:13.917012Z","event":"flow_end","zone":2,"duration":1571.45,"limits":[3600],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":2028.55}
```

`temperature_f: 101.8` is 38.8 °C exactly; the panel displays it as 102 °F.

### What Home Assistant sent

One `solowritesystem` POST at 15:52:00.949 UTC. Reproduced by running the shipped encoder
against the state at that instant:

```json
{"deviceId": "...", "sku": "GCS", "tenantId": "...",
 "gcsValveControlModel": {
   "primaryValve1":   "0184C800",
   "secondaryValve1": "1184C801",
   "secondaryValve2": "0000000000000000", ... "secondaryValve7": "0000000000000000"}}
```

**Both zones, always.** The protocol has no partial write, so "leave zone 1 alone" is
expressed as a well-formed zone 1 word with mask `0x00` — never the `00000000` sentinel,
which addresses no valve and makes the device discard the whole command. Zone 1's byte 0 is
`0x01` and not the `0x05` the valve was reporting, because atTemp is device status that our
encoder always writes zero.

The restore replayed temperature and flow **byte-exactly**: `flow_preserved: true`, and the
valve's echo at 15:52:02.462 is identical to the pre-pause word.

## 6. The controller's silence, measured

The raw logger has **no filter** — `RawLog.write()` records every message that arrives on the
subscription. And there is exactly one subscription: [`mqtt.py`](../../anthem_plus/mqtt.py)
subscribes `$iothub/methods/POST/#`, one connection carrying **every device on the account**,
GCS and HUB alike, told apart by `sku` inside the payload. The GCS messages at 14:52, 15:52
and 16:18 UTC prove the socket was up throughout.

So the silence is real, not a capture gap. Whole-file counts (for the equivalent ±1 h
windows, see [A.3](#a3--what-a-matching-window-looked-like-the-day-before)):

| Capture file | GCS messages | HUB messages |
|---|---|---|
| 2026-08-17 shower (session 9) | 58 | **42 `SHOWER_VALVE_STS`** + 20 snapshots |
| **2026-08-18 shower (this one)** | **5** | **0** |

The controller's last message of **any** code:

```text
SHOWER_VALVE_STS   2026-08-18T01:51:31.696Z   [2026-08-17 18:51:31 local]
```

That is two minutes after the previous evening's shower ended. It then stayed silent for
**~18 hours**, through two config-entry reloads (03:37 UTC and 05:20 UTC) and through this
entire shower. For contrast, this is what it used to publish, from the session 9 capture:

```text
2026-08-18T01:42:02.974Z  {'status':'ON', 'zone':'1','temperature':98,'flowrate':100,'outlets':[1,0,1,0,0,0]}
2026-08-18T01:43:07.869Z  {'status':'OFF','zone':'1','temperature':None,'flowrate':None,'outlets':[0,0,0,0,0,0]}
```

### ⭐ 6a. The connection was healthy the whole time

**This is the point of the case study, and it needs saying explicitly: nothing was broken.**
The silence was not a dropped connection, a lost subscription, a stalled client or an offline
controller. Every one of those is ruled out, and the controller published nothing anyway.

| Ruled out | How |
|---|---|
| **The MQTT link was down** | Five GCS messages arrived across the 86 minutes, including at 15:52:00 and 16:18:13 UTC — the exact instants the controller should have spoken. |
| **The connection dropped and re-established** | The IoT Hub `$rid` runs **1 → 5, unbroken, no reset** across the whole session. A new connection restarts it at 1 (visible in the next capture, which does exactly that). One connection, start to finish. |
| **Our client filtered HUB messages out** | There is no filter to apply. `RawLog.write()` records everything, and there is **one** wildcard subscription — `$iothub/methods/POST/#` — carrying both devices, told apart only by `sku` *inside* an already-recorded payload. No code path can drop one device and keep the other. |
| **The controller was powered off or hung** | It **commanded the 09:18:13 stop** from its own touchscreen, through itself, to the valve. A dead controller cannot end a shower. |
| **The controller's publishing was broken** | It publishes normally on this same account, subscription and connection — [case study 2](02_hub_commanded_shower_15min.md), a HUB-commanded shower a few hours later, where every transition produced a `SHOWER_VALVE_STS`. ⚠️ But see open question 1: that also means a message was *expected* here and did not come. |

**So the controller was healthy, connected, listening, and had nothing to say.** It was not
failing to report the shower. There was, as far as it was concerned, no shower to report.

> ⚠️ **One honest caveat.** A Home Assistant **Core restart** falls between this session and
> the healthy one (13:15:25 local, which is why the next capture is PID 72 and its `$rid`
> starts over). So the two are not a strictly uninterrupted continuation, and this does not
> *prove* the controller's publishing was healthy at 08:52 in the same way the other four
> rows prove their claims. It is ruled out on mechanism rather than on continuity: our end
> holds one wildcard subscription with no per-device handling anywhere in it, so there is no
> way for a client-side fault to deliver GCS and silently discard HUB.
>
> **Owner's assessment, 2026-08-18:** the restart before case study 2 was a mistake and
> should not have happened — an uninterrupted continuation would have settled this outright.
> The possibility of some error is left standing rather than argued away. The owner is
> nonetheless confident the connection was fine, and every other row above is independent of
> that judgement.

## 7. What this establishes

### ⭐ The controller never interpreted this as a shower — and that is a HUB fault, not an MQTT one

**Owner's conclusion, 2026-08-18, and it is the right reading of the whole session.**

> ✅ **Confirmed by positive control.** [Case study 3](03_both_ceilings_at_15_minutes.md) §7 put
> both ceilings at 15 minutes on a controller-owned session: the controller commanded its
> shutoff at 901.004 s, on its own clock, *even though the valve had already paused the zone a
> second earlier*. So the mechanism is live and enforced unconditionally when a session is
> known. It did not fire once in this session's 86 minutes — 26 minutes past its own
> 60-minute ceiling — which can only mean the condition was never met.

The chain is short. The controller pushes a card update when its own model of the shower
changes. It pushed nothing for 86 minutes. Under the app-UI-channel model
([`intro.md`](intro.md) §1) that means **its model never changed** — and its model is built
from what it observes over the **RJ wired link**, not from MQTT. So the controller, wired to
the valve the entire time, **did not interpret the valve opening outlets as a shower having
started.**

**This is therefore a controller-side interpretation gap, not an artefact of the message
channel.** MQTT reported the situation correctly: there was nothing to render, because as far
as the controller was concerned nothing was happening.

Two independent lines converge on it, and they share no failure mode:

| evidence | class | what it shows |
|---|---|---|
| No card update, for 86 minutes | the app UI channel | the controller's model of the shower never changed |
| **Its 15-minute clock never ran** | **device behaviour** | no session existed to count. [Case study 2](02_hub_commanded_shower_15min.md) proves that clock works and fires within 0.6 s |

The second crosses the wired link and is decisive on its own.

⚠️ **What this does NOT separate.** "Did not receive the valve's state over the wire" and
"received it and did not count it as a session" are both controller-side, and nothing here
tells them apart. The controller is demonstrably *not* blind to the valve in general — during
the 2026-08-17 shower it reported every one of the valve's pauses, sessions it had itself
commanded. The precise, defensible claim is: **the controller does not treat a valve-side
open it did not command as a session** — it neither renders it nor starts its clock. Which of
the two mechanisms produces that is unmeasured, and probably unmeasurable without sniffing a
link we cannot reach.

### ✅ Started by `solowritesystem`, the HUB does not count

[Session 9](../handoff/2026-08-17_session9_current.md) §1 left this explicitly open — three
ways to start water, and the countdown was **confirmed** only for a HUB-commanded start:

| started by | does the HUB command it? | HUB countdown |
|---|---|---|
| HUB valve-on (the Anthem Plus panel) | yes | starts at that moment — confirmed 2026-08-17 |
| `solowritesystem` (Home Assistant) | no | **does not run — confirmed 2026-08-18, this session** |
| GCS preset | no | still unknown |

The evidence is the 26 minutes of overrun. A 60-minute ceiling anchored anywhere in this
session — at the open, at the restore, at the pause — would have expired before 09:18:13.
None did.

**Consequence: the 60-minute ceiling handling does not apply to a Home-Assistant-started
shower at all.** It remains live for showers started at the panel.

### ✅ Matched limits produce one clean cut, as predicted

Session 9 predicted that with both maximums at 60 minutes, "the two deadlines coincide, one
cut is seen instead of two, and the restart is clean." Observed exactly: one `0x40` at
3599.77 s, one restore, 1.514 s of water off, no second stop.

⚠️ **But this session cannot confirm the mitigation works**, because the HUB's clock was not
running to be matched. The prediction and the observation agree for a reason the prediction
did not anticipate. **The mitigation is still untested for its actual purpose** — that needs
a shower started at the panel.

### ✅ The detector correctly declined the manual stop

Leg 2 ended at 1571.45 s, `off_by: 2028.55` from the only announced limit. Verdict `ignored`.
This is the behaviour that the removal of the pause-flag veto (session 9 §1) put at risk: a
`0x00` stop is now eligible for restart, and the only thing that declined it was the duration
not matching a limit. It held.

⚠️ **The journal cannot attribute this stop.** In
[`runtime_cutoff.py`](../../anthem_plus/runtime_cutoff.py) the `match is None` branch returns
before the `suppressed(zone)` check, so a non-matching duration always reports `"duration is
not within 10s of any limit"` — even if Home Assistant had issued the stop within the 30 s
grace window. **The absence of the grace reason is not evidence of an external stop.** The
attribution to the touchscreen is the owner's, not the log's.

### ✅ The controller switches were reading the wrong device

Both `switch.anthem_plus_shower` and `switch.anthem_plus_system` tracked this shower
faithfully — because their water term read the **valve**, through the old
`coordinator.water_is_running`. On a device page for a controller that knew nothing, that is
a false positive dressed as health. Changed the same day: both now read
`coordinator.hub_water_is_running`, the controller's own outlet arrays only. See
[`architecture.md`](../architecture.md) and `tests/test_hub_switch_source.py`, which replays
these five words and asserts both switches stay off through all of them.

## 8. Open questions this raises

1. **⭐ Why was there no `SHOWER_VALVE_STS` at 09:18:13?** The controller *commanded* that
   stop, and an OFF transition is precisely the case it is documented to report — see
   [`architecture.md`](../architecture.md) and `resolve_outlet_source()`. It reported
   nothing.

   **Leading hypothesis, untested:** the controller reports the *end of a session it was
   tracking*, not any OFF transition it happens to cause. It never knew this session began,
   so there was no session to close. This is consistent with everything observed here and in
   session 9 — but it is a hypothesis, and the rule as currently written in
   `resolve_outlet_source()` predicts a message that did not arrive.

   **Discriminating test:** start a shower from the Anthem Plus panel, then stop it from the
   panel. If `SHOWER_VALVE_STS` arrives, session-tracking is confirmed and the rule needs
   rewording.

   ✅ **That test was run the same afternoon —
   [case study 2](02_hub_commanded_shower_15min.md) §6d.** The controller reports a
   HUB-commanded session in full: `status: ON` with populated outlet arrays, the mid-session
   change, and the stop, each ~0.5 s behind the valve and matching it bit for bit.

   ✅ **RESOLVED 2026-08-18, by correcting what the channel is.** The premise of this
   question was wrong. It assumed a message "should have arrived" because a device commanded
   an OFF transition — which only makes sense if MQTT carries device traffic. It does not; it
   is the app's UI channel ([`intro.md`](intro.md) §1). The controller's card already read
   "off", because it never registered this shower as having started (§7). The stop left it
   "off". **No card change, no push, no message to expect.**

   The one residue is the older `solowritesystem` measurement in
   [`architecture.md`](../architecture.md), where the stop of a session the controller never
   saw open *did* produce a `status: OFF` — a redundant off→off card push. That is a much
   smaller puzzle: "when does the cloud push a no-change update", not "why was a device
   silent". Worth a footnote if it ever recurs; not worth chasing.

   **§6a's fifth row stands as originally written.** The doubt raised against it rested on the
   same wrong premise.

2. ✅ **Was the controller healthy on 2026-08-18? Yes — this is settled, see [§6a](#-6a-the-connection-was-healthy-the-whole-time).**
   Connected, listening, alive, and publishing normally on the same account and subscription
   a few hours later. The 18 hours of silence were not a fault. What remains genuinely
   unresolved is narrower and belongs to question 1: whether "nothing to report" is the
   controller's *rule* or merely what happened here.

3. **Does a GCS preset start the HUB's clock?** Still no data. The third row of the table in
   §7 is the last one open.

4. **The HUB's max shower duration is still unreadable.** Session 9 open item 2 stands: it is
   in no capture and no endpoint found so far, so the integration cannot offer it as an
   announced limit. Carried, unchanged.

## 9. Provenance

Every record this case study rests on is reproduced verbatim in
[Appendix A](#appendix-a--every-raw-record-one-hour-either-side), covering the session and a
full hour either side of it, so nothing here has to be taken on trust.

| Fact | Source |
|---|---|
| Every hex word, timestamp, and message count | `mqtt_raw_20260818T052055Z_71_0b22dd90.jsonl` — read in full, 5 lines |
| Cutoff verdicts, durations, restore fields | `cutoff_20260818T052055Z_71_c7d8362b.jsonl` — read in full, 7 lines |
| GCS `maximumRunTime` = 3600 s | the `arm` line above |
| The words Home Assistant sent | reproduced by running `anthem_plus.valve_hex.encode_word` against the captured state |
| Leg durations, totals, the 08:52:01.179 figure | computed from the capture's own timestamps |
| HUB 60-minute Max Shower Duration | configuration, carried from session 9 §0a — **not re-verified here** |
| Who commanded events 1, 2, 3 and 4 | **owner-reported.** The capture corroborates the shape of each but names no commander |

`/config/home-assistant.log` was absent for this session (only a zero-byte
`home-assistant.log.fault`), so there is no HA-side record — no `ENDLESS_SHOWER_RESTARTED`
warning, no confirmation of the 07:52:01 start from our own side. Everything above comes from
the two capture files, which is why they are quoted in full rather than summarised.

---

## Appendix A — every raw record, one hour either side

**Window: 2026-08-18 13:52:01.179971Z → 17:18:13.916459Z** (06:52:01 → 10:18:13 local) — the
session start minus one hour, to the session end plus one hour.

Every `.jsonl` in `/config/kohler_anthem_plus_raw/` was scanned across the whole window, not
just the two files this session wrote.

> **The hour before and the hour after are completely empty — on both devices.** The window
> holds **11 records in total**: the 5 MQTT messages and
> 6 journal entries already quoted above, all of them inside the session itself.
> Nothing precedes the 07:52:01 open and nothing follows the 09:18:13 stop. The valve is
> silent when idle, and the controller was silent throughout.

### A.1 — raw MQTT, verbatim (5 records)

Lines exactly as written by `RawLog.write()`, with **one substitution**: the real
`tenantid` is replaced by `<TENANT_ID>`, per the placeholder policy in
[`../README.md`](../README.md). Device ids are left in place — they identify hardware on one
account but are not credentials. Nothing else is altered, including the per-message
`messageid` and `correlationid` GUIDs.

Source file for all of them: `mqtt_raw_20260818T052055Z_71_0b22dd90.jsonl`.

**07:52:01.179 local** — line 1

```json
{"ts":"2026-08-18T14:52:01.179971Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=1","qos":0,"retain":false,"payload":"{\"messageid\":\"5E42A70F-9892-2E34-8804-D4C1C50AB0AE\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787064731\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"24931\",\"totalVolume\":\"874658338\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**07:52:45.891 local** — line 2

```json
{"ts":"2026-08-18T14:52:45.891944Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=2","qos":0,"retain":false,"payload":"{\"messageid\":\"87F8DE31-2AEE-3AD4-933D-1370F6B5323E\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787064776\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1657\",\"totalVolume\":\"536930912\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**08:52:00.948 local** — line 3

```json
{"ts":"2026-08-18T15:52:00.948159Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=3","qos":0,"retain":false,"payload":"{\"messageid\":\"168B6635-8380-63A4-9DD3-3FF4E692E177\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787068331\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c84000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**08:52:02.462 local** — line 4

```json
{"ts":"2026-08-18T15:52:02.462454Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=4","qos":0,"retain":false,"payload":"{\"messageid\":\"2D4EC44F-1297-7E94-B0CE-59FA0BA4D40A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787068333\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"25188\",\"totalVolume\":\"1713519138\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**09:18:13.916 local** — line 5

```json
{"ts":"2026-08-18T16:18:13.916459Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=5","qos":0,"retain":false,"payload":"{\"messageid\":\"F3D9D211-814C-3EA4-80B6-1E659BCD1DBC\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787069904\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"4\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

### A.2 — cutoff journal, verbatim (6 records)

Source file: `cutoff_20260818T052055Z_71_c7d8362b.jsonl`. The `arm` line quoted in §1 falls outside this window (05:20:56Z,
at integration setup) and is not repeated here.

```json
{"ts":"2026-08-18T14:52:01.180650Z","event":"flow_start","zone":2,"mask":1,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T15:52:00.948731Z","event":"flow_end","zone":2,"duration":3599.77,"limits":[3600],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":101.8,"verdict":"cutoff","matched":3600}
{"ts":"2026-08-18T15:52:00.948956Z","event":"restore","zones":[2],"also_paused":[],"masks":{"1":0,"2":1},"from_detector":{"2":1},"from_snapshot":{"1":0,"2":1},"was_flow_percent":{"2":100.0},"was_temperature_f":{"2":101.8},"writing_flow_percent":{"2":100.0},"flow_preserved":true}
{"ts":"2026-08-18T15:52:01.844462Z","event":"restore_done","outlets":[4],"write_seconds":0.9}
{"ts":"2026-08-18T15:52:02.462964Z","event":"flow_start","zone":2,"mask":1,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T16:18:13.917012Z","event":"flow_end","zone":2,"duration":1571.45,"limits":[3600],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":2028.55}
```

### A.3 — what a matching window looked like the day before

The equivalent ±1 h window around the previous evening's **panel-started** shower
(2026-08-17T23:39:08Z → 2026-08-18T02:49:32Z), counted the same way, for scale:

| | 2026-08-17, panel-started | **2026-08-18, HA-started (this one)** |
|---|---|---|
| GCS messages | 54 | **5** |
| HUB messages | **42** | **0** |
| of which `SHOWER_VALVE_STS` | 42 | 0 |

Same account, same subscription, same single MQTT connection, windows of the same width.
The difference is not volume — it is that one device stopped existing on the wire.
