# Case study 2 — the controller-commanded shower, and its 15-minute ceiling

**2026-08-18. The mirror image of [case study 1](01_ha_driven_shower_hub_blind.md): same
hardware, same afternoon, opposite commander. Home Assistant touched nothing.**

> **What these case studies are for.** Neither 1 nor 2 is a test of Endless Shower. They
> exist to establish **the command surface** — who can start and stop water, which device
> then owns the session, whose timer runs, and what each device reports while it does. That
> has to be nailed down before the restart feature can be designed against it rather than
> guessed at. Consequences for Endless Shower are noted where they fall out, but they are
> consequences, not the objective.

> **The headline.** Started with the controller's own `valveOnOff`, the Anthem Plus owns the
> session completely: its clock runs, it cuts at exactly its configured **15 minutes** with a
> `0x00` stop, and it reports every transition — including `status: ON` with populated outlet
> arrays, which case study 1 never saw. The valve's own 60-minute `maximumRunTime` never came
> near firing. **The two ceilings do not cooperate; the earlier one simply wins, and which
> device is counting was decided at the moment the shower started.**

---

## 1. Configuration at the time

| Setting | Where | Value | How verified |
|---|---|---|---|
| **GCS max shower duration** (`maximumRunTime`) | Anthem valve, per outlet | **3600 s = 60 min**, all six | cutoff journal `arm` line, read over REST at setup |
| **HUB max shower duration** | Anthem Plus controller | **900 s = 15 min** | **read live** from the local API — see §8 |
| Warm-up mode | controller | `on` — water stays on through warm-up | local API |
| Endless Shower | integration option | enabled | `arm` line |
| Flow control | system-wide | disabled (`flowcontrol: false`) | local API |

```json
{"ts":"2026-08-18T20:15:26.236943Z","event":"arm","enabled":true,
 "run_times":{"1":3600,"2":3600,"3":3600,"4":3600,"5":3600,"6":3600},
 "awaiting":[],"zone_limits":{"1":[3600],"2":[3600]}}
```

**This is the first session in which both maximums are known rather than assumed.** Case
study 1 could only cite the HUB's 60 minutes from configuration memory; here it is read from
the device, and it is the number that ended the shower.

## 2. Who commanded what

| # | Local time | Event | Commanded by |
|---|---|---|---|
| 1 | 13:26:08 | water on — warm-up, five outlets | **HUB `valveOnOff`** (equivalent to the Anthem Plus panel's default shower button) |
| 2 | 13:26:38 | warm-up ends, settles to outlet 4 | **the HUB**, its own warm-up logic |
| 3 | 13:41:08 | shower ends, `0x00`/`0x00` | **the HUB**, its 15-minute ceiling expiring |

**Home Assistant issued nothing.** The cutoff journal records only observations — two
`flow_start`s, a `mask_change`, and two `flow_end`s. No `restore`, no write.

## 3. The complete capture

`/config/kohler_anthem_plus_raw/mqtt_raw_20260818T201525Z_72_d536f3df.jsonl`. Complete
records verbatim in [Appendix A](#appendix-a--every-raw-record-of-the-session).

```text
local           who  message
13:26:08.110    GCS  v1=0184C800  v2=1184C803    zone 2 opens: outlets 4+5
13:26:08.355    GCS  v1=0184C807  v2=1184C803    zone 1 opens: outlets 1+2+3   (+0.245 s)
13:26:08.846    HUB  z1=ON:111000  z2=ON:110000  warmup=1                      (+0.491 s)
13:26:32.885    GCS  v1=0584C807  v2=1184C803    atTemp set                    (+24.775 s)
13:26:38.369    GCS  v1=0584C800  v2=1184C801    warm-up ends -> outlet 4 only
13:26:38.915    HUB  z1=OFF:000000 z2=ON:100000  warmup=0                      (+0.547 s)
              ────────── 14 m 30 s, outlet 4 alone ──────────
13:41:08.667    GCS  v1=0184C800  v2=1184C800    STOP — both zones, no pause flag
13:41:09.220    HUB  z1=OFF:000000 z2=OFF:000000 warmup=0                      (+0.553 s)
```

Temperature `0x184` (388) = 38.8 °C = 102 °F throughout; flow `0xC8` (200) = 100% against a
`0xC8` (200) ceiling on every outlet. Masks: `0x07` (7) = zone 1 outlets 1+2+3, `0x03` (3) =
zone 2 outlets 4+5, `0x01` (1) = outlet 4 alone, `0x00` (0) = closed.

### The HUB's outlet arrays match the valve exactly

For the first time in this project the controller reports open outlets, and its report agrees
with the valve word bit for bit:

| local | HUB array | valve mask | agree? |
|---|---|---|---|
| 13:26:08.846 | z1 `[1,1,1]`, z2 `[1,1,0]` | `0x07` (7), `0x03` (3) | ✅ |
| 13:26:38.915 | z1 `[0,0,0]`, z2 `[1,0,0]` | `0x00` (0), `0x01` (1) | ✅ |
| 13:41:09.220 | z1 `[0,0,0]`, z2 `[0,0,0]` | `0x00` (0), `0x00` (0) | ✅ |

It trails the valve by **0.491, 0.547 and 0.553 s** — consistent, and small.

## 4. The timeline, with arithmetic

```text
13:26:08.110   HUB valveOnOff — water on, warm-up recipe    <- the session clock starts HERE
13:26:08.355   zone 1 joins                                  +0.245 s
13:26:32.885   valve reaches setpoint (atTemp)               +24.775 s
13:26:38.369   warm-up ends, zone 1 closes, zone 2 -> 0x01   +30.258 s (5.483 s after atTemp)
13:41:08.667   HUB STOP, both zones 0x00
```

| Quantity | Value |
|---|---|
| Zone 2, open to stop | **900.557 s** — ceiling 900 s, overshoot **+0.557 s** |
| Zone 1, open to warm-up end | 30.013 s |
| Warm-up settle → stop | 870.299 s |
| Had the clock reset at the warm-up settle, the stop would have been | **13:41:38.369** |

## 5. The cutoff journal, complete

`/config/kohler_anthem_plus_raw/cutoff_20260818T201525Z_72_b69de911.jsonl`, 6 lines:

```json
{"ts":"2026-08-18T20:15:26.236943Z","event":"arm","enabled":true,"run_times":{"1":3600,"2":3600,"3":3600,"4":3600,"5":3600,"6":3600},"awaiting":[],"zone_limits":{"1":[3600],"2":[3600]}}
{"ts":"2026-08-18T20:26:08.111479Z","event":"flow_start","zone":2,"mask":3,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T20:26:08.356403Z","event":"flow_start","zone":1,"mask":7,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T20:26:38.369551Z","event":"flow_end","zone":1,"duration":30.01,"limits":[3600],"mask":7,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":3569.99}
{"ts":"2026-08-18T20:26:38.369659Z","event":"mask_change","zone":2,"mask":1,"was":3,"flowing_for":30.26,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T20:41:08.668124Z","event":"flow_end","zone":2,"duration":900.56,"limits":[3600],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":2699.44}
```

## 6. What this establishes

### ⭐ 6a. The warm-up period COUNTS toward the ceiling

The clock starts when **water** starts, not when warm-up finishes. The arithmetic is decisive
and leaves no room for interpretation:

| hypothesis | predicted stop | actual | verdict |
|---|---|---|---|
| clock starts at the warm-up open, 13:26:08.110 | 13:41:08.110 | **13:41:08.667** | ✅ +0.557 s |
| clock starts when warm-up ends, 13:26:38.369 | 13:41:38.369 | 13:41:08.667 | ❌ 29.70 s early |

**Practical consequence: warm-up costs you shower time.** 30.258 s of a 15-minute allowance
went to bringing five outlets up to temperature before the shower proper began — 3.4% of the
session, and it scales with how long the pipes take, not with anything the user chooses.

### ⭐ 6b. The ceiling is the configured value, exactly — and the two are independent

Two points now, from two settings, both HUB-commanded starts:

| HUB max shower duration | measured cut | overshoot |
|---|---|---|
| 60 min (2026-08-17, session 9) | 3600.20 s | +0.20 s |
| **15 min (this session)** | **900.557 s** | **+0.557 s** |

Meanwhile the valve's `maximumRunTime` was 3600 s and **never fired** — the session ended at
a quarter of it. The two timers do not negotiate, do not reset one another, and do not know
about each other. **The earlier deadline simply wins.**

### ⭐ 6c. The HUB's clock is not reset by transitions it commands mid-session

Session 9 proposed the rule *"the HUB resets on transitions it commands, not on transitions it
observes."* This session **narrows it**. The warm-up settle at 13:26:38 was unambiguously
HUB-commanded — it flipped the controller's own `showerwarmup` flag and rewrote both zone
masks — and the clock did not reset. The stop came 900.557 s after the **original** open.

Corrected rule: **the clock anchors when the HUB starts a session and runs to its ceiling.
Changes within the session, even ones the HUB itself commands, do not restart it.**

### ⭐ 6d. The HUB reports a session it commanded, in full and accurately

Three `SHOWER_VALVE_STS`: the open, the mid-session change, and the stop. Populated outlet
arrays, correct temperature and flow, matching the valve exactly, ~0.5 s behind.

This is a genuine correction to a claim carried in
[`architecture.md`](../architecture.md): *"the HUB emits `SHOWER_VALVE_STS` only for
transitions that land in an **OFF** state."* That was measured on a `solowritesystem`-driven
session and **holds only there**. For a session the HUB commanded, it reports every
transition in both directions.

### ⭐ 6e. The warm-up handoff carries NO pause — it is one direct mask rewrite

The obvious guess is that the controller pauses the valve to reconfigure it between the
warm-up recipe and the shower proper. **It does not.** Byte 3 of every word in the session:

```text
13:26:08.110  v1=0184c800 byte3=0x00  | v2=1184c803 byte3=0x03
13:26:08.355  v1=0184c807 byte3=0x07  | v2=1184c803 byte3=0x03   (+0.245 s)
13:26:32.885  v1=0584c807 byte3=0x07  | v2=1184c803 byte3=0x03   (+24.530 s)
13:26:38.369  v1=0584c800 byte3=0x00  | v2=1184c801 byte3=0x01   (+5.483 s)  <- the handoff
13:41:08.667  v1=0184c800 byte3=0x00  | v2=1184c800 byte3=0x00   (+870.299 s)
```

**The `0x40` bit is set nowhere, in either zone, at any point in the session.** The handoff is
a single message in which zone 1 goes `0x07` (7) → `0x00` (0) and zone 2 `0x03` (3) → `0x01`
(1) simultaneously. Outlet 4 is open before and after; water never stops.

That is exactly what `warmupmode: "on"` means — the UI label for that enum value is **"Water
Stays ON"**. The third option, `pause`, is presumably the one that produces a `0x40`, and it
has never been exercised here (§10).

⚠️ One limit on this claim: the valve publishes on change, so a pause word lasting less than
one publish interval could escape capture. The open resolves two words 0.245 s apart, so a
genuine pause would very likely have been published — but "no pause was reported" is the
measurement, and "no pause occurred" is the inference.

### 6f. The cutoff detector cannot see this cut — and that is expected, not a bug

`900.56` against announced limits `[3600]` → `off_by: 2699.44` → `ignored`. The water stayed
off.

Stated plainly rather than as a failure: the detector matches **announced** limits, the only
announced limits come from the GCS outlets, and the HUB's ceiling has never been announced to
anything. It behaved exactly as designed on information it did not have. §8 is what changes
that.

## 7. Read together with case study 1 — the command surface

This is the payoff of running both. The two sessions differ in exactly one variable — who
started the water — and everything else follows from it:

| | **Case study 1** — HA `solowritesystem` | **Case study 2** — HUB `valveOnOff` |
|---|---|---|
| Does the HUB know? | **No** | **Yes** |
| HUB session clock | **not running** | runs, anchored at the open |
| HUB MQTT reporting | **silent — zero messages** | full: ON, mid-session, OFF |
| Which timer ends it | GCS `maximumRunTime` | HUB max shower duration |
| Stop signal | `0x40` pause, per zone | `0x00` stop, both zones |
| Recoverable by the integration | yes — the limit is announced | no — the limit is not |
| Warm-up | none — HA opens outlets directly | five outlets, counts toward the ceiling |

**The decisive fact: which device owns the session is fixed at the moment water starts, and
nothing afterwards changes it.** A shower started from Home Assistant cannot acquire a HUB
clock; a shower started from the panel cannot shed one. Session 9's mitigation — "set both
maximums to the same value" — now reads as a workaround for not knowing which regime you are
in, rather than a fix.

## 8. ✅ The HUB's max shower duration IS readable — over the LOCAL API

Open since session 9 (§6 item 2) and repeated as case study 1 open question 4: the value
appears in no cloud response and no MQTT message. **It is on the controller's local API.**

Found in the hub's own UI bundle (`http://<HUB_IP>/web/main.<hash>.js`):

```js
getValveSettings() { return this.commonHttpService.httpGet("web/api/v1/device/get_valve_settings") }
```

`GET /web/api/v1/device/get_valve_settings`, authenticated with the PIN→JWT flow in
[`../hub/local_api.md`](../hub/local_api.md) §2. Read live 2026-08-18:

```json
{"coldwatertimeout":"5","configuration":"Custom","flowcontrol":false,
 "lowflowstate":false,"maxshowerduration":"15","maxtemp":"113","warmupmode":"on",
 "zone1":{"defaultFlow":"100","defaultOutlets":[],"defaultTemp":"102",
          "port1":62,"port2":52,"port3":1,"ports":3,"warmupOutlets":[1,2,3]},
 "zone2":{"defaultFlow":"100","defaultOutlets":[1],"defaultTemp":"102",
          "port1":11,"port2":38,"port3":21,"ports":3,"warmupOutlets":[1,2]}}
```

**Minutes, as a string.** The UI dropdown that writes it offers exactly four values —
`15 / 30 / 45 / 60`:

```js
this.maxShowerDurationData = [{text:"15 Min",value:15},{text:"30 Min",value:30},
                              {text:"45 Min",value:45},{text:"60 Min",value:60}]
```

⚠️ Session 9 §1 worried that *"at a 20- or 25-minute Max Shower Duration the ceiling falls
mid-leg, matches nothing, and is ignored"*. **On this firmware those values are unreachable** —
only four are selectable. That narrows the problem but does not remove it: 15, 30 and 45 all
fall mid-leg against a 60-minute `maximumRunTime`, as this session shows.

### Every observation in §3 was predictable from this object

| Observed on the wire | Configuration that produced it |
|---|---|
| opens z1 `0x07` (7) + z2 `0x03` (3) | `zone1.warmupOutlets:[1,2,3]`, `zone2.warmupOutlets:[1,2]` |
| water runs through warm-up rather than pausing | `warmupmode:"on"` — the enum is `on`/`off`/`pause` |
| settles to z1 `0x00` (0), z2 `0x01` (1) | `zone1.defaultOutlets:[]`, `zone2.defaultOutlets:[1]` |
| `0x184` (388) = 102 °F | `defaultTemp:"102"`, both zones |
| `0xC8` (200) = 100% | `defaultFlow:"100"`, `flowcontrol:false` |
| stop at 900.557 s | `maxshowerduration:"15"` |

The warm-up mask is **configuration, not firmware behaviour** — and it is readable, which
means a HUB-commanded shower is predictable in advance rather than only in hindsight.

Read with `/homeassistant/scripts/kohler-work/hub_local_read.py` — GET-only by construction,
with `req_update_command`, `set_hub_datetime` and `factory_reset` deliberately off its
allow-list.

### Two side findings from the same read

* **The controller's clock is in the wrong timezone.** `get_hub_settings` reports
  `datetime: "2026-08-18T15:07"` with `timezone: "(UTC-06:00) … America/Guatemala"` while the
  house is UTC-7 — the hub runs **one hour ahead**. Harmless for these case studies, whose
  timestamps are stamped by Home Assistant, but it would corrupt any correlation against a
  hub-side log.
* **Authenticating to the local API makes the controller publish its cloud snapshots.** Two
  logins at 14:07:43 and 14:08:13 each produced a burst of five HUB snapshot messages plus a
  GCS experience read. Reproducible, and the same burst appears at integration startup.

## 9. Scope — deliberately excluded

**Ice shower, the ice-shower experience, and experiences generally on both the GCS and the
HUB are out of scope for this line of work.** They are a separate feature family, driven as
presets/experiences rather than as ordinary shower control.

In particular: `coldwatertimeout: "5"` in the object above is **not** a fourth shower timer.
It belongs to the ice-bath function and does not apply to a normal shower. An earlier reading
of it as a general timer was wrong and is corrected here.

## 10. Open

1. **Does a GCS preset start the HUB's clock?** The last unknown row of the start-route table.
   Neither case study covers it.
2. **Should the integration read the local API?** §8 makes the fix possible: feed
   `maxshowerduration` to the detector as a second announced limit and a 900 s stop becomes
   matchable. The cost is real — the integration currently makes no local connection at all,
   and this would add a LAN dependency plus a PIN in the config flow. Worth deciding
   deliberately, not by momentum.
3. **Case study 1's silence is still unexplained**, and this session sharpens it. We now know
   the controller reports HUB-commanded transitions in full, yet case study 1's stop — also
   HUB-commanded, from the panel — produced nothing. See
   [case study 1 §6a](01_ha_driven_shower_hub_blind.md#-6a-the-connection-was-healthy-the-whole-time).
4. **What does `warmupmode: "pause"` do?** The enum offers `on` / `off` / `pause`. Only `on`
   has been observed. Whether `pause` produces a `0x40` — and whether the ceiling counts
   through it — is unmeasured.

## 11. Provenance

| Fact | Source |
|---|---|
| Every hex word, timestamp, message count | `mqtt_raw_20260818T201525Z_72_d536f3df.jsonl` — read in full |
| Cutoff verdicts and durations | `cutoff_20260818T201525Z_72_b69de911.jsonl` — read in full, 6 lines |
| GCS `maximumRunTime` = 3600 s | the `arm` line |
| **HUB max shower duration = 15 min** | **live read**, `get_valve_settings`, 2026-08-18 |
| The `15/30/45/60` dropdown and the endpoint name | the hub's own UI bundle, downloaded from the device |
| Leg durations and the 13:41:38.369 counterfactual | computed from the capture's own timestamps |
| Who commanded events 1–3 | **owner-reported**; the capture corroborates the shape of each |

`/config/home-assistant.log` was absent for this session, as for case study 1, so there is no
Home-Assistant-side record. Everything above comes from the two capture files.

---

## Appendix A — every raw record of the session

**Window: 2026-08-18 19:26:08.110Z → 20:41:09.220Z** (12:26:08 → 13:41:09 local) — one hour
before the session opened, to its final message.

Every `.jsonl` in `/config/kohler_anthem_plus_raw/` was scanned across that window, not just
the two files this session wrote.

> ⛔ **Hard-capped at the session's last message, deliberately.** Case study 3 was being
> conducted while this was written, into the same capture file. Nothing after 20:41:09.220Z
> is included here, and nothing after it belongs to this case study. Twelve later records do
> exist and are named in §8 so they are not mistaken for case study 3: the snapshot bursts at
> 14:07:43 and 14:08:13 local, provoked by local-API logins, not by water.

The hour before the session contains **nothing at all** — the previous capture file's last
record was at 09:18:13 local, and this one opens at 13:15:25 with the Core restart.

### A.1 — raw MQTT, verbatim (20 records)

Lines exactly as written by `RawLog.write()`, with **one substitution**: the real `tenantid`
is replaced by `<TENANT_ID>` per the placeholder policy in [`../README.md`](../README.md).
Device ids are left in place. Nothing else is altered.

Source file for all of them: `mqtt_raw_20260818T201525Z_72_d536f3df.jsonl`.

**13:24:17.327 local** — line 1 — HUB — SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:17.327450Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=1","qos":0,"retain":false,"payload":"{\"messageid\":\"fbd251e5-27f7-4484-a276-d0e9f37ba870\",\"sysid\":\"HUB-SH8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084656\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"17\",\"name\":\"Warm Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly increases to allow the body to warm up gradually while not overheating. The temperature then slowly declines.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"18\",\"name\":\"Cool Down\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly decreases to enable the body to cool down. After a cool period, water will again raise to a comfortable temperature.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"19\",\"name\":\"Sleep Simple\",\"active\":\"true\",\"duration\":\"7\",\"description\":\"Water starts at a comfortable temperature for showering. After 4 minutes, temperature will slowly lower to a neutral bathing temperature enabling the body to begin relaxing & prepare for sleep.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"20\",\"name\":\"Wake Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. As the body gets acclimated, the temperature will rise slightly keeping the body feeling warm for the duration of the shower.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"21\",\"name\":\"Shine\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. After 7 minutes the water temperature will slowly decrease to help lock in moisture in the skin and hair\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**13:24:17.656 local** — line 2 — HUB — STEAM_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:17.656369Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=2","qos":0,"retain":false,"payload":"{\"messageid\":\"e08daaf0-2e45-4c99-b87c-347d957773cd\",\"sysid\":\"HUB-STM8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084657\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"STEAM_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**13:24:17.875 local** — line 3 — HUB — ICE_SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:17.875686Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=3","qos":0,"retain":false,"payload":"{\"messageid\":\"2bc2de53-5e8f-455d-b37e-2c5736adad54\",\"sysid\":\"HUB-ISHEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084657\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"ICE_SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"22\",\"name\":\"Beginner Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a cool shower which will leave you feeling refreshed and awake\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"23\",\"name\":\"Advanced Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a full cold shower which will leave you feeling alert and reinvigorated\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**13:24:18.096 local** — line 4 — HUB — LUMIWAVE_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:18.096014Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=4","qos":0,"retain":false,"payload":"{\"messageid\":\"ed7e0924-3016-4594-8ee6-ff57f3c8a7c9\",\"sysid\":\"HUB-LUMIEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084657\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"LUMIWAVE_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**13:24:18.442 local** — line 5 — HUB — FAVORITES_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:18.442401Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=5","qos":0,"retain":false,"payload":"{\"messageid\":\"187c807b-9ac3-443d-945c-9fc0f2dd1439\",\"sysid\":\"HUB-INRB916T7R\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084658\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"FAVORITES_SNAPSHOT\",\"attributes\":[]}}"}
```

**13:24:19.233 local** — line 6 — GCS — READ_GCS_EXPERIENCE_STS

```json
{"ts":"2026-08-18T20:24:19.233974Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=6","qos":0,"retain":false,"payload":"{\"messageid\":\"69FAB080-5FDC-2AB4-BF70-D4D5D31746B8\",\"sysid\":\"GCS-INXR739U7S\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787084670\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"READ_GCS_EXPERIENCE_STS\",\"attributes\":[{\"experienceId\":\"1\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"2\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"3\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"4\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"5\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"}]}}"}
```

**13:24:48.006 local** — line 7 — HUB — SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:48.006781Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=7","qos":0,"retain":false,"payload":"{\"messageid\":\"2bbc6ce8-1eeb-473b-b432-aa20c8d1cd82\",\"sysid\":\"HUB-SH8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084687\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"17\",\"name\":\"Warm Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly increases to allow the body to warm up gradually while not overheating. The temperature then slowly declines.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"18\",\"name\":\"Cool Down\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature and then slowly decreases to enable the body to cool down. After a cool period, water will again raise to a comfortable temperature.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"19\",\"name\":\"Sleep Simple\",\"active\":\"true\",\"duration\":\"7\",\"description\":\"Water starts at a comfortable temperature for showering. After 4 minutes, temperature will slowly lower to a neutral bathing temperature enabling the body to begin relaxing & prepare for sleep.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"20\",\"name\":\"Wake Up\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. As the body gets acclimated, the temperature will rise slightly keeping the body feeling warm for the duration of the shower.\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"21\",\"name\":\"Shine\",\"active\":\"true\",\"duration\":\"10\",\"description\":\"Water starts at a comfortable temperature for showering. After 7 minutes the water temperature will slowly decrease to help lock in moisture in the skin and hair\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**13:24:48.336 local** — line 8 — HUB — STEAM_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:48.336482Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=8","qos":0,"retain":false,"payload":"{\"messageid\":\"483d8c4e-49fe-4d48-a694-3e8266ac23f3\",\"sysid\":\"HUB-STM8EXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084687\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"STEAM_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**13:24:48.553 local** — line 9 — HUB — ICE_SHOWER_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:48.553239Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=9","qos":0,"retain":false,"payload":"{\"messageid\":\"9b9609a6-eef2-4f85-a1b7-0089daf8d717\",\"sysid\":\"HUB-ISHEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084688\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"ICE_SHOWER_EXP_SNAPSHOT\",\"attributes\":[{\"id\":\"22\",\"name\":\"Beginner Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a cool shower which will leave you feeling refreshed and awake\",\"audio\":\"Music\",\"status\":\"OFF\"},{\"id\":\"23\",\"name\":\"Advanced Ice Shower\",\"active\":\"true\",\"duration\":\"4.75\",\"description\":\"Experience a full cold shower which will leave you feeling alert and reinvigorated\",\"audio\":\"Music\",\"status\":\"OFF\"}]}}"}
```

**13:24:48.788 local** — line 10 — HUB — LUMIWAVE_EXP_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:48.788413Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=10","qos":0,"retain":false,"payload":"{\"messageid\":\"40e6db3e-c690-4f47-87ff-644af408fa62\",\"sysid\":\"HUB-LUMIEXPSNP\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084688\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"LUMIWAVE_EXP_SNAPSHOT\",\"attributes\":[]}}"}
```

**13:24:49.108 local** — line 11 — HUB — FAVORITES_SNAPSHOT

```json
{"ts":"2026-08-18T20:24:49.108901Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=11","qos":0,"retain":false,"payload":"{\"messageid\":\"d1b77fca-c31b-4fdf-b40f-2b75ef299682\",\"sysid\":\"HUB-INRB916T7R\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084688\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"FAVORITES_SNAPSHOT\",\"attributes\":[]}}"}
```

**13:24:49.875 local** — line 12 — GCS — READ_GCS_EXPERIENCE_STS

```json
{"ts":"2026-08-18T20:24:49.875924Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=12","qos":0,"retain":false,"payload":"{\"messageid\":\"EC95E5A8-48B6-C474-B245-0B83EB62D8CF\",\"sysid\":\"GCS-INXR739U7S\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787084701\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"READ_GCS_EXPERIENCE_STS\",\"attributes\":[{\"experienceId\":\"1\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"2\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"3\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"4\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"},{\"experienceId\":\"5\",\"name\":\"\",\"valves\":\"0\",\"steps\":\"0\",\"stepTime\":\"0\"}]}}"}
```

**13:26:08.110 local** — line 13 — GCS — v1=0184C800 v2=1184C803

```json
{"ts":"2026-08-18T20:26:08.110922Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=13","qos":0,"retain":false,"payload":"{\"messageid\":\"F80B856C-6E34-06D4-9953-4BA9ADFC34B8\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787084779\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"1\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1535\",\"totalVolume\":\"536930784\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**13:26:08.355 local** — line 14 — GCS — v1=0184C807 v2=1184C803

```json
{"ts":"2026-08-18T20:26:08.355859Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=14","qos":0,"retain":false,"payload":"{\"messageid\":\"4430ACBA-83A7-3394-B5F8-D07AFB682C2A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787084779\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"1\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"3\",\"totalVolume\":\"536929056\",\"primaryValve1\":\"0184c80700000001\",\"secondaryValve1\":\"1184c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**13:26:08.846 local** — line 15 — HUB — z1=ON z2=ON

```json
{"ts":"2026-08-18T20:26:08.846601Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=15","qos":0,"retain":false,"payload":"{\"messageid\":\"2dcb4ade-a10e-4e8f-abc5-6f220737b7ca\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084768\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"1\",\"attributes\":[{\"status\":\"ON\",\"zone\":\"1\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,1,1,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,1,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**13:26:32.885 local** — line 16 — GCS — v1=0584C807 v2=1184C803

```json
{"ts":"2026-08-18T20:26:32.885564Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=16","qos":0,"retain":false,"payload":"{\"messageid\":\"168B6635-8380-63A4-9DD3-3FF4E692E177\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787084804\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"0\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"1\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"2\",\"totalVolume\":\"536929016\",\"primaryValve1\":\"0584c80700000001\",\"secondaryValve1\":\"1184c80300000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**13:26:38.369 local** — line 17 — GCS — v1=0584C800 v2=1184C801

```json
{"ts":"2026-08-18T20:26:38.369024Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=17","qos":0,"retain":false,"payload":"{\"messageid\":\"2D4EC44F-1297-7E94-B0CE-59FA0BA4D40A\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787084809\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"1\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"1653\",\"totalVolume\":\"536930904\",\"primaryValve1\":\"0584c80000000001\",\"secondaryValve1\":\"1184c80100000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**13:26:38.915 local** — line 18 — HUB — z1=OFF z2=ON

```json
{"ts":"2026-08-18T20:26:38.915609Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=18","qos":0,"retain":false,"payload":"{\"messageid\":\"e7a365cd-5dcd-4b73-a824-f158e111fa39\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787084798\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"ON\",\"zone\":\"2\",\"temperature\":102,\"flowrate\":100,\"outlets\":[1,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

**13:41:08.667 local** — line 19 — GCS — v1=0184C800 v2=1184C800

```json
{"ts":"2026-08-18T20:41:08.667539Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=19","qos":0,"retain":false,"payload":"{\"messageid\":\"482C0C83-6ABF-8E84-9E15-48ADABB10C56\",\"sysid\":\"GCS-INJK966T6G\",\"deviceid\":\"gcs-sio32343h7\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"correlationid\":\"00000000-0000-0000-0000-000000000000\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"INTERNAL-0000-0000-0000-SENSATE00000\",\"sku\":\"GCS\",\"type\":\"STS\",\"timestamp\":\"1787085679\",\"simulated\":\"false\",\"data\":{\"type\":\"Status\",\"code\":\"GCS_SOLO_STS\",\"attributes\":[{\"code\":\"GCS_SOLO_STS\",\"firmwareUpdate\":\"noUpdateAvailable\",\"BLEPairing\":\"normal\",\"BLEConnected\":\"NotConnected\",\"IoTActive\":\"Active\",\"IoTProvision\":\"noProvisionMode\",\"warmUpStatus\":\"warmUpNotInProgress\",\"configWriteAllowedFlag\":\"1\",\"currentSystemState\":\"normalOperation\",\"configChangeIndent\":\"1\",\"presetOrExperienceId\":\"0\",\"totalFlow\":\"477\",\"totalVolume\":\"536929728\",\"primaryValve1\":\"0184c80000000001\",\"secondaryValve1\":\"1184c80000000001\",\"secondaryValve2\":\"0000000000000000\",\"secondaryValve3\":\"0000000000000000\",\"secondaryValve4\":\"0000000000000000\",\"secondaryValve5\":\"0000000000000000\",\"secondaryValve6\":\"0000000000000000\",\"secondaryValve7\":\"0000000000000000\"}]}}"}
```

**13:41:09.220 local** — line 20 — HUB — z1=OFF z2=OFF

```json
{"ts":"2026-08-18T20:41:09.220092Z","topic":"$iothub/methods/POST/ExecuteControlCommand/?$rid=20","qos":0,"retain":false,"payload":"{\"messageid\":\"a03c4fa4-028a-4d56-afd5-173b10f0324b\",\"sysid\":\"HUB-BVBSRFX6\",\"deviceid\":\"gcs-sious0103D\",\"ver\":\"1.0\",\"protocol\":\"MQTT\",\"ttl\":\"5000\",\"durable\":\"true\",\"tenantid\":\"<TENANT_ID>\",\"internalid\":\"<INTERNAL_ID>\",\"sku\":\"HUB\",\"type\":\"STS\",\"timestamp\":\"1787085668\",\"simulated\":\"false\",\"data\":{\"type\":\"status\",\"code\":\"SHOWER_VALVE_STS\",\"experienceid\":\"0\",\"favoriteid\":\"0\",\"showerwarmup\":\"0\",\"attributes\":[{\"status\":\"OFF\",\"zone\":\"1\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":\"valve1\",\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"},{\"status\":\"OFF\",\"zone\":\"2\",\"temperature\":null,\"flowrate\":null,\"outlets\":[0,0,0,0,0,0],\"errorcode\":null,\"component\":null,\"errorstate\":\"0\",\"code\":\"SHOWER_VALVE_STS\"}]}}"}
```

### A.2 — cutoff journal, verbatim (6 records)

Source file: `cutoff_20260818T201525Z_72_b69de911.jsonl`. This is the file in its entirety.

```json
{"ts":"2026-08-18T20:15:26.236943Z","event":"arm","enabled":true,"run_times":{"1":3600,"2":3600,"3":3600,"4":3600,"5":3600,"6":3600},"awaiting":[],"zone_limits":{"1":[3600],"2":[3600]}}
{"ts":"2026-08-18T20:26:08.111479Z","event":"flow_start","zone":2,"mask":3,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T20:26:08.356403Z","event":"flow_start","zone":1,"mask":7,"limits":[3600],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T20:26:38.369551Z","event":"flow_end","zone":1,"duration":30.01,"limits":[3600],"mask":7,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":3569.99}
{"ts":"2026-08-18T20:26:38.369659Z","event":"mask_change","zone":2,"mask":1,"was":3,"flowing_for":30.26,"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-18T20:41:08.668124Z","event":"flow_end","zone":2,"duration":900.56,"limits":[3600],"mask":1,"paused":false,"flow_percent":100.0,"temperature_f":101.8,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":2699.44}
```

### A.3 — the twelve records that are NOT shower activity

Twelve of the twenty MQTT records above bracket the shower rather than describing it, in two
identical bursts of five HUB snapshots plus one GCS experience read. The remaining eight are
the shower itself — five `GCS_SOLO_STS` and three `SHOWER_VALVE_STS`.

```text
13:24:17.327 - 13:24:19.233   SHOWER_EXP / STEAM_EXP / ICE_SHOWER_EXP / LUMIWAVE_EXP /
13:24:48.006 - 13:24:49.875   FAVORITES snapshots, then READ_GCS_EXPERIENCE_STS
```

These are the integration's reseed after the Core restart at 13:15:25, repeated. The identical
burst reappears after any local-API login (§8). They carry no water state and are included
only so the record is complete.
