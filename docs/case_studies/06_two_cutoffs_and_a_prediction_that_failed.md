# Case study 6 — two cutoffs in one shower, and a prediction that failed

**2026-08-18, 22:39:12 – 23:02:29 local (2026-08-19T05:39–06:02Z). The first live shower on
the reverted `0x40`-required code (`d84b2d1`), with both Max Shower Durations set to 15 min.**

> ### ⚠️ MQTT is the Konnect app's UI channel — not device communication
>
> Everything below is from MQTT, and MQTT is not how the valve and the controller talk to each
> other. The cloud invokes direct methods *on us*: we are an app instance, and the payloads say
> what the app should **render**. The real device-to-device link is the **RJ wired connection**,
> and **we cannot sniff it**. Absence of a message is not silence; presence can be wrong. Read
> [`intro.md`](intro.md) §1 before this document.

> **The headline, in two parts.**
>
> **1. The design works.** Two independent zone cutoffs at 900 s, 136.7 s apart, both carrying
> `0x40`, both caught, both restored, flow and temperature preserved byte-exact. Session 10
> predicted this from five case studies; this is the first hardware confirmation.
>
> **2. A theory built on it was wrong, and the reason is methodological.** Over three replies
> this session, three successive explanations were offered for the `0x00` that followed one
> cutoff and not the other. All three were built on **58 of the corpus's 90 capture files**.
> On the full corpus none of them survive. The failure is recorded here in full, because the
> mistake is repeatable and the corrected numbers are the useful output.

---

## 1. Configuration at the time

| Setting | Value | Note |
|---|---|---|
| GCS `maximumRunTime` | **900 s = 15 min** | `"limits":[900]` on every journal event |
| HUB max shower duration | **15 min** | matched, per session 10's instruction |
| Endless Shower | **on** | `"event":"arm","enabled":true` |
| Integration code | `d84b2d1` — `0x40` required again | committed 19:06:37 local, MQTT re-armed 19:12 |
| Start route | Home Assistant (`switch.anthem_plus_shower` at 05:39:09Z) | no preset |

**Byte 3 throughout.** Where this document says `0x40` or `0x00` it means **byte 3 of the
valve word** — the outlet mask, with `0x40` as the pause flag. In `118ac840`: byte 0 `0x11`
(flags + temperature high bits), byte 1 `0x8a` (temperature low — `0x18A` (394) = 39.4 °C =
102.9 °F), byte 2 `0xc8` (200) = 100 % flow, **byte 3 `0x40`**. All six outlets on this install
report `maximumFlowRate` and `defaultFlowRate` of `0xC8` (200), so 100 % is against a full
ceiling.

## 2. The cutoff journal, verbatim

`/config/kohler_anthem_plus_raw/cutoff_20260819T021218Z_71_25466fc3.jsonl`, trimmed to the two
cutoffs and their restores:

```json
{"ts":"2026-08-19T05:39:12.511680Z","event":"flow_start","zone":2,"mask":3,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-19T05:39:12.552027Z","event":"flow_start","zone":1,"mask":7,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-19T05:39:42.280634Z","event":"flow_end","zone":1,"duration":29.73,"limits":[900],"mask":7,"paused":false,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":870.27}
{"ts":"2026-08-19T05:41:29.255910Z","event":"flow_start","zone":1,"mask":4,"limits":[900],"flow_percent":100.0,"temperature_f":101.8}
{"ts":"2026-08-19T05:48:22.207282Z","event":"setting_change","zone":1,"mask":6,"flowing_for":412.95,"was_temperature_f":101.8,"temperature_f":102.9}
{"ts":"2026-08-19T05:54:12.302039Z","event":"flow_end","zone":2,"duration":899.79,"limits":[900],"mask":1,"paused":true,"flow_percent":100.0,"temperature_f":102.9,"verdict":"cutoff","matched":900}
{"ts":"2026-08-19T05:54:12.302275Z","event":"restore","zones":[2],"also_paused":[],"masks":{"1":4,"2":1},"from_detector":{"2":1},"was_flow_percent":{"2":100.0},"was_temperature_f":{"2":102.9},"flow_preserved":true}
{"ts":"2026-08-19T05:54:13.158049Z","event":"restore_done","outlets":[3,4],"write_seconds":0.86}
{"ts":"2026-08-19T05:54:13.828386Z","event":"flow_start","zone":2,"mask":1,"limits":[900],"flow_percent":100.0,"temperature_f":102.9}
{"ts":"2026-08-19T05:55:30.540029Z","event":"flow_end","zone":2,"duration":76.71,"limits":[900],"mask":1,"paused":false,"verdict":"ignored","reason":"duration is not within 10s of any limit","off_by":823.29}
{"ts":"2026-08-19T05:56:29.033515Z","event":"flow_end","zone":1,"duration":899.78,"limits":[900],"mask":4,"paused":true,"flow_percent":100.0,"temperature_f":102.9,"verdict":"cutoff","matched":900}
{"ts":"2026-08-19T05:56:29.033720Z","event":"restore","zones":[1],"also_paused":[],"masks":{"1":4,"2":0},"from_detector":{"1":4},"was_flow_percent":{"1":100.0},"was_temperature_f":{"1":102.9},"flow_preserved":true}
{"ts":"2026-08-19T05:56:29.654119Z","event":"restore_done","outlets":[3],"write_seconds":0.62}
{"ts":"2026-08-19T05:56:30.235061Z","event":"flow_start","zone":1,"mask":4,"limits":[900],"flow_percent":100.0,"temperature_f":102.9}
```

## 3. The two cutoffs on the wire

```text
ZONE 2 — cut at 899.79 s
  05:54:12.301Z  +0.000  GCS  z1=058ac804  z2=118ac840   <- pause
  05:54:12.551Z  +0.250  HUB  zone1=ON zone2=OFF
  05:54:12.624Z  +0.323  GCS  z1=058ac804  z2=118ac800   <- stop, 0.323 s later
  05:54:13.827Z  +1.526  GCS  z1=058ac804  z2=118ac801   <- our restore
  05:54:14.296Z  +1.995  HUB  zone1=ON zone2=ON

ZONE 1 — cut at 899.78 s
  05:56:29.033Z  +0.000  GCS  z1=058ac840  z2=118ac800   <- pause
  05:56:29.564Z  +0.532  HUB  zone1=OFF zone2=OFF
  05:56:30.234Z  +1.202  GCS  z1=058ac804  z2=118ac800   <- our restore
  05:56:30.649Z  +1.617  HUB  zone1=ON zone2=OFF
                                                          no 0x00 ever published
```

`configWriteAllowedFlag` read `0` at every line above.

## 4. ⭐ What is solid

### 4a. The matched-durations fix works, confirmed live

Both zones hit their 900 s limit, both carried `0x40`, both were caught, both restored, and
the shower continued to 06:02:29Z. This is what session 10 reasoned to from case studies 1–5
and could not yet demonstrate.

The controller's own ceiling is visible landing behind the valve's, exactly as predicted: at
05:54:12.624Z, **+0.323 s** after the valve's pause, on a zone the restore then re-opened
1.2 s later. Nobody in the shower would have noticed.

### 4b. The per-zone clock is confirmed to 0.013 s

Zone 1 stopped at 29.73 s and restarted, re-anchoring its clock:

| | zone 2 | zone 1 |
|---|---|---|
| started flowing | 05:39:12.511Z | 05:41:29.255Z |
| paused `0x40` | 05:54:12.301Z (899.79 s) | 05:56:29.033Z (899.78 s) |

Gap between the starts **136.744 s**; gap between the cutoffs **136.732 s**. They agree to
**0.013 s**. Two entirely independent events — this is the premise the whole detector rests on
and it has never been measured this precisely.

### 4c. Restoring one zone does not disturb the other's valve clock

The zone 2 restore at 05:54:13Z rewrote the **whole system word**, including zone 1's mask 4
while zone 1 was 763 s into its own session. Zone 1 still cut at 899.78 s from its own start.
A restore write does not re-anchor the other zone's hardware timer.

### 4d. Flow and temperature survive a restore byte-exact

`flow_preserved: true` on both, `0xC8` (200) = 100 %, `0x18A` (394) = 102.9 °F. This is the
path session 10 §4 noted had not been exercised on hardware since the Fahrenheit fix. It has
now, twice, with no drift.

## 5. ❌ The prediction, and why it failed

### 5a. What was claimed, in order

The question asked was: does a `0x40` cutoff also produce a `0x00`? Zone 2 did (+0.323 s);
zone 1 did not. Three explanations were offered in successive replies:

| # | claim | basis | status |
|---|---|---|---|
| 1 | The `0x00` is the controller's ceiling landing late | session 10's model | **wrong** — retracted for a byte-identical event in [case study 5 §11](05_three_restarts_and_the_unexplained_00.md) before this session began; repeated without checking |
| 2 | The `0x00` is predicted by whether the **other zone is running** — the ~120 s hold never happens while it is | 25 transitions, 58 files | **wrong** — see 5c |
| 3 | The `0x00` is predicted by **which zone paused**: a lone `0x40` on zone 1 never survives (5 of 5) | 26 transitions, 58 files | **wrong** — 5 of 12 on the full corpus |

Explicit numeric predictions were given for three scenarios, for what byte 3 does within 3 s:

| scenario | predicted | basis given | actual, full corpus |
|---|---|---|---|
| zone 1 `0x40`, zone 2 running | `0x00` in ~1 s, "confident" | 3 of 3 | **3 of 8** |
| zone 2 `0x40`, zone 1 running | `0x00` in ~0.5 s, "usually" | 2 of 3 | **2 of 3** |
| zone 2 `0x40`, zone 1 off `0x00` | **nothing happens**, holds | 1 of 7 | **3 of 18** |

Only the third survives, and only directionally.

### 5b. ⚠️ The cause: the corpus was 58 files, not 90

Every analysis was run against `/config/kohler_anthem_plus_raw/` alone. **The corpus is 90
files across five directories**, and the 32 oldest live in
`/homeassistant/scripts/kohler_konnect_custom/log/` in a **different schema** —
`received_at_utc` rather than `ts`, and `payload` as a dict rather than a JSON string. A reader
written for the newer format silently sees none of them.

That is 36 % of the corpus and the entire 2026-08-07 → 08-13 period. Session 10's handoff said
"89 capture files, 2026-08-07 → 08-18" in plain text; the discrepancy went unnoticed until the
date range was printed. **Print the corpus range before trusting any corpus claim.**

`pause_resolution.py` (new, in `kohler-work/`) reads both schemas and prints its own file count
and date range on every run, so this cannot recur silently.

### 5c. The corrected numbers

**61 natural `0x40 → 0x00` resolutions** — pauses nobody re-opened, so the valve's own
behaviour — across all 90 files:

| resolution time | n | values |
|---|---|---|
| **≤ 3 s** | **11** | 0.323, 0.428, 0.563, 0.767, 0.875, 0.971, 0.993, 1.087, 1.326, 1.330, 1.547 |
| 3 – 115 s | 10 | 5.263, 5.263, 5.423, 6.108, 7.625, 31.716, 36.012, 50.032, 50.032, 77.351 |
| **≥ 115 s — the ~120 s hold** | **40** | 119.651 … 120.724 |

Split by the two variables that were proposed as discriminators:

| scenario | n | ≤ 3 s |
|---|---|---|
| zone 1 `0x40` / other `0x00` off | 4 | 2 |
| zone 1 `0x40` / other RUNNING | 8 | 3 |
| zone 1 `0x40` / other also `0x40` | 12 | 1 |
| zone 2 `0x40` / other `0x00` off | 18 | 3 |
| zone 2 `0x40` / other RUNNING | 3 | 2 |
| zone 2 `0x40` / other also `0x40` | 16 | 0 |

| era | n | ≤ 3 s |
|---|---|---|
| 2026-08-07 … 08-14 (flow experiments, valve-reboot fault) | 55 | 8 |
| 2026-08-15 … 08-19 (clean sessions) | 6 | 3 |

**Neither variable separates the populations.** Fast collapses appear in five of the six zone
buckets and in both eras. The ~120 s hold is the mode at **40 of 61**, and it appears in every
bucket except "zone 2 paused while zone 1 runs", where n=3.

### 5d. What can honestly be said

* **The `0x40` → `0x00` delay is not predicted by which zone paused, by what the other zone was
  doing, or by the date.** No rule proposed this session survives the full corpus.
* **The modal behaviour is the ~120 s hold** — 40 of 61, tightly clustered at 119.651–120.724 s.
  That is [case study 4 §5](04_two_touchscreens_and_what_off_means.md)'s finding, unchanged and
  now on a much larger sample.
* **A fast collapse is a real minority behaviour, roughly 1 in 6**, and it remains unexplained.
* **Zone 1's silence in this shower needs no explanation at all.** We restored at +0.621 s. The
  overwhelmingly likely reading is that we overwrote the pause before anything tore it down.
  Its silence is evidence about our write latency, not about the valve.

## 6. The other event: 05:55:30Z

Zone 2, restored 76.7 s earlier, stopped again with `0x00` and stayed off. Endless Shower
correctly declined — `paused: false`, `off_by` 823.29 s.

The HUB message preceded the GCS one by **0.037 s**, the only such inversion among 20
post-restore stops (the rest lead +0.031 to +1.004 s). That is suggestive of a
controller-initiated stop and no more: the margin is the same order as the smallest observed
GCS lead. **Not attributed.**

Worth noting alongside it: **7 of 20 restored zones stop again within ~130 s** — 35.6, 45.4,
51.4, 78.2, 87.0, 96.8, 129.7 s. Roughly a third of restores do not hold. Whether that is the
system or the person in the shower is not established by anything here.

## 7. The clean experiment this leaves

The three-scenario prediction table in §5a is worth running deliberately, because it is cheap
and the current answer is "we cannot predict it":

**Endless Shower OFF.** Let a zone reach its `maximumRunTime` and leave the `0x40` alone.
Record byte 3 at 1 s, 3 s, 10 s and 130 s. Repeat for each of the three scenarios.

Current best guess for all three, on 61 observations: **it holds ~120 s**, with about a 1-in-6
chance of collapsing inside 3 s. Any scenario that reliably departs from that is the
discriminator nobody has found yet.

This is session 10's open item 7, now with a number attached instead of an expectation.

## 8. Corrections this case study makes

| what | now |
|---|---|
| "The controller's `0x00` follow-up lands on an already-restored zone" (this session, reply 1) | Restated without evidence; [case study 5 §11](05_three_restarts_and_the_unexplained_00.md) had already retracted it. The attribution is open. |
| "The ~120 s hold never happens while the other zone runs" (this session, reply 3) | **Wrong.** 5 of 8 with zone 2 running held past 3 s, four of them to ~120 s. |
| "A lone `0x40` on zone 1 never survives — 5 of 5" (this session, reply 4) | **Wrong.** 5 of 12 on the full corpus. |
| `runtime_cutoff.py` `update()` docstring: "the pause flag is recorded but no longer required" | Contradicted the code from `d84b2d1` onward. Corrected in place. |
| Any claim of the form "across the corpus…" made before 2026-08-19 | Check which directories it read. 58-file and 90-file corpora give different answers. |

## 9. Sources

| claim | source |
|---|---|
| The two cutoffs, restores, durations | `cutoff_20260819T021218Z_71_25466fc3.jsonl` |
| Valve words, HUB messages, ordering | `mqtt_raw_20260819T021218Z_71_5660be0f.jsonl` |
| `switch.anthem_plus_shower` at 05:39:09Z | recorder DB, read-only |
| 61 pause resolutions, all splits | `kohler-work/pause_resolution.py`, 90 files, 2026-08-07 → 08-19 |
| Code loaded | `git log` — `d84b2d1`, 2026-08-18 19:06:37 -0700; MQTT arm 02:12:19Z |
