# Case study 7 — the controller's cutoff is a software sweep, not a timer per zone

**2026-08-19, 12:47:18 – 14:58:22 local. Three consecutive showers, deliberately mismatched:
GCS `maximumRunTime` 60 min, HUB max shower duration 15 min. Every shower started with the
HUB's `valveOnOff`; everything after that was driven from the Anthem Plus touchscreen. All
three ended by themselves.**

> ### ⚠️ MQTT is the Konnect app's UI channel — not device communication
>
> Everything on the wire below is what the cloud told app clients to render. The real
> device-to-device link is the **RJ wired connection**, which cannot be sniffed. Absence of a
> message is not silence. Conclusions about what a device *knew* rest on **behaviour**. Read
> [`intro.md`](intro.md) §1 first. Two of this study's load-bearing observations come from the
> **physical screens**, not the wire, and are attributed to the owner where used.

> **The headline.** The controller does not run a countdown per zone. **It arms timers on
> events, and when one fires it sweeps every zone and cuts each one it finds at or over the
> limit.** 15 of 16 zone-decisions across three showers follow that rule exactly. It explains
> the whole shape of the controller's behaviour: why a zone can run 28 minutes past a 15-minute
> limit unnoticed, why one expiry sometimes takes both zones down, and — retroactively — what
> [case study 5](05_three_restarts_and_the_unexplained_00.md)'s unexplained `00/00` was.

---

## 1. Configuration

| Setting | Value | How verified |
|---|---|---|
| GCS `maximumRunTime` | **3600 s = 60 min** | `"limits":[3600]` on every journal event |
| HUB max shower duration | **900 s = 15 min** | owner-set; every cut lands at 900–901 s |
| Endless Shower | **on** at the last recorded `arm` (15:20:41Z) | ⚠️ no `arm` in these three captures; not directly confirmed for them |
| Start route | **HUB `valveOnOff`**, all three | owner-confirmed |
| All other control | **Anthem Plus touchscreen** | owner-confirmed |
| Warm-up / preset | `warmUpNotInProgress`, `presetOrExperienceId: 0` | first word of each capture |

Temperatures below are the wire value: `0x184` (388) = 101.8 °F is the configured
`defaultOutletTemperature`; the owner moved it to `0x17F` (383) = 100.9 °F and `0x179` (377) =
99.9 °F from the touchscreen. Flow was `0xC8` (200) = 100 % throughout, against a `0xC8` (200)
ceiling on every outlet.

**This is the mismatched configuration [session 10](../handoff/2026-08-18_session10_current.md)
§1a warns against for normal use.** That is the point: it makes the controller the sole
authority, so every cut observed here is unambiguously its own.

## 2. The three showers

```text
SHOWER 1   zone 1  leg 1  12:47:18 → 12:48:05     46.47s   ended by hand
                   leg 2  12:54:20 → 13:22:25   1685.35s   OVERRAN by 13:05
           zone 2  leg 1  12:47:18 → 13:02:19    900.60s   cut
                   leg 2  13:07:25 → 13:22:25    900.33s   cut

SHOWER 2   zone 1  leg 1  13:32:32 → 13:47:33    901.16s   cut   ← the only zone-1 cut
                   leg 2  13:52:13 → 14:17:45   1532.39s   OVERRAN by 10:32
           zone 2  leg 1  13:41:18 → 13:56:19    900.85s   cut
                   leg 2  14:02:44 → 14:17:45    901.12s   cut

SHOWER 3   zone 1  leg 1  14:32:08 → 14:58:15   1567.12s   OVERRAN by 11:07
           zone 2  leg 1  14:24:58 → 14:39:59    900.41s   cut
                   leg 2  14:43:21 → 14:58:21    900.30s   cut
```

**Zone 2: 6 of 6 legs cut. Zone 1: 1 of 4 testable legs cut.**

## 3. How the controller signals a stop

**`0x00` in byte 3. Never `0x40`.** Across all three showers — **34 valve status messages —
not one word carries the pause flag.** The controller clears the mask, which is
indistinguishable in shape from somebody pressing off.

**It is always late, never early:**

```text
+900.30   +900.33   +900.41   +900.60   +900.85   +901.12   +901.16
```

Seven measurements spanning **+0.30 to +1.16 s**, extending case study 3's three (+0.20,
+0.557, +1.004). Against the valve's measured **−0.08 to −0.23 s early**, the two devices never
overlap — which is exactly why session 10's "set both durations equal and the valve always wins
the race" holds.

The lateness is itself evidence of implementation. A firmware countdown reaches zero on
schedule; a software timer fires on the next tick and then does work, and the controller's own
status messages already lag the valve's by 0.26–0.61 s. Late and scattered across ~0.9 s is
what a tick loop looks like. **Owner's framing, adopted here: the valve's limit is baked into
firmware, the controller's is pure software.**

## 4. ⭐ The sweep — what actually happens when a timer fires

Every stop, with each zone's elapsed time at that instant and what happened to it:

```text
SHOWER 1
  12:48:05.455   z1    46.47s under -> CUT            ← manual, not a timer event
  13:02:19.448   z1   479.14s under -> left running   |  z2   900.60s OVER -> CUT
  13:22:25.650   z1  1685.35s OVER  -> CUT            |  z2   900.33s OVER -> CUT
SHOWER 2
  13:47:33.614   z1   901.16s OVER  -> CUT            |  z2   374.78s under -> left running
  13:56:19.691   z1   246.45s under -> left running   |  z2   900.85s OVER -> CUT
  14:17:45.629   z1  1532.39s OVER  -> CUT            |  z2   901.12s OVER -> CUT
SHOWER 3
  14:39:59.377   z1   470.75s under -> left running   |  z2   900.41s OVER -> CUT
  14:58:15.743   z1  1567.12s OVER  -> CUT            |  z2   894.40s under -> left running
  14:58:21.648   z1  idle                             |  z2   900.30s OVER -> CUT
```

**15 of 16 zone-decisions follow "at or over 900 s → cut; under → spared".** The single
exception is 12:48:05, the owner turning zone 1 off by hand at 46 s — not a timer event at all.

**The decisive pair is 14:58.** A sweep cut zone 1 at 1567 s and **spared zone 2 with 5.6
seconds still to run**; zone 2 died 5.9 s later on its own. Only a sweep that evaluates each
zone independently against the limit produces that.

### 4a. It is not a free-running poll

If the controller polled every zone on a clock, zone 1 would have been cut the moment it crossed
900 s — not **785, 632 and 667 seconds later**. So the sweep runs *only when some armed timer
fires*. Zone 1 spent up to thirteen minutes over the limit with nothing scheduled to look at it.

**That is the whole explanation for "zone 1 is unreliable": zone 1's timer usually never arms,
so zone 1 is only ever cut as collateral, when another zone's timer wakes the sweep.**

## 5. ⭐ What arms a timer — the open half

Reliable: **every zone-2 flow start armed one, 6 for 6**, regardless of route — `valveOnOff`
for the session opener, touchscreen for every later leg.

Unreliable: **zone 1 armed once in four testable legs.** The one that armed (shower 2,
13:32:32) is the only zone-1 leg that opened the session with zone 2 idle.

And arming is not limited to flow starts. The 14:58:15.743 sweep traces back **900.32 s** to
the owner's **touchscreen temperature change** at 14:43:15.423 — no zone started then. So
control events arm timers too, which widens the search rather than narrowing it.

⚠️ **No rule is offered here.** Three candidate explanations survive on n=4 — zone 1 arms only
when it opens the session; zone 1 arms only once per session; the start route decides — and
[case study 5](05_three_restarts_and_the_unexplained_00.md) contradicts the first, since zone 1
armed there while zone 2 was running. A designed experiment is specified in §11.

## 6. ⭐ The shower does not end when the water stops

**Owner's observation, from the physical screens — this is not on the wire and could not have
been derived from it:**

> The valve treats `0x40/0x40` as the end of its shower: the GCS touchscreen shows total time
> and water usage, then goes dark. **The controller and the Anthem Plus touchscreen stay on**
> until the 2-minute mark, when the `00/00` resets to default — and only then does the Anthem
> Plus screen show its own total time and water usage and go dark.

**The two products run their shower sessions independently, each with its own end condition and
its own summary screen.**

The wire agrees. Every clean case where water stopped with a non-default setpoint and nobody
intervened:

| all water off | setpoint at stop | gap | result |
|---|---|---|---|
| 08-17 18:49:32 | `0x16E` (366) 98 °F | **119.02 s** | → `0x184` (388) |
| 08-18 16:29:49 | `0x16E` (366) 98 °F | **119.03 s** | → `0x184` (388) |
| 08-19 14:17:45 | `0x17F` (383) 100.9 °F | **118.68 s** | → `0x184` (388) |
| 08-19 14:58:21 | `0x179` (377) 99.9 °F | **119.18 s** | → `0x184` (388) |
| 08-19 13:22:25 | `0x17F` (383) 100.9 °F | **120.62 s** | → `0x184` (388) |
| 08-14 18:14:23 | `0x190` (400) 104 °F | **121.09 s** | → `0x184` (388) |

`0x184` (388) is the configured `defaultOutletTemperature`. Reverting to it is what session-end
means.

### 6a. ⚠️ This corrects case study 4

[Case study 4 §5](04_two_touchscreens_and_what_off_means.md) records the ~120 s event as
**"a `0x40` pause self-terminates into `0x00` after ~2 minutes."**

**These three showers contain zero `0x40` and still produced the revert, all three times.** The
clock is not attached to pauses. It runs from **all water off**, whatever stopped it.

That also reframes the population in [`intro.md`](intro.md) §3a: the 40 of 61 teardowns landing
at 119.6–120.7 s were not pauses tearing themselves down. They were pauses still outstanding
when the **session-end** timer fired and zeroed everything. One clock, not two.

## 7. ⭐ What this resolves in earlier case studies

### 7a. Case study 5's `00/00` is the controller's ceiling — mechanism and all

[Case study 5](05_three_restarts_and_the_unexplained_00.md) §10 recorded its `00/00` as
unexplained and §12 ranked it open item **#1**.

Zone 1 began flowing at 15:59:12.974; the `00/00` landed at 16:14:13.766:

> **16:14:13.766 − 15:59:12.974 = 900.792 s** — inside this study's +900.30…+901.16 s band,
> between the fourth and fifth of seven.

Nothing else fits: zone 2's clock would have expired at 16:06:00, and zone 2 had been running
only 492.2 s.

The sweep explains the part timing alone could not — **why zone 2 was zeroed at 492 s.** Zone
2's *valve* clock had been reset by an Endless Shower restore at restart 1; the **controller's**
had not, because the controller's clock runs straight through our 1.2–2.2 s restore gaps
(session 10, `runtime_cutoff.py`). The sweep therefore saw zone 2 at
**16:14:13.766 − 15:51:00.260 = 1393.5 s** — far over 900 → cut.

Both zones over limit, both cut, one word. Routine.

### 7b. Case study 3's retraction does not hold

Session 10 retracted case study 3's controller attribution for a `00/00` at **+1.087 s**, on the
grounds that `cfgW` flipped to `1` **before** the `00/00` with the word otherwise identical —
and `cfgW` is the valve's own field.

Two of this study's stops carry that identical signature, and here the controller is provably
the author:

| stop | precursor | lead | elapsed |
|---|---|---|---|
| 13:47:33.614 | word-identical, `cfgW` 0→1 | **0.117 s** | 901.16 s |
| 14:58:15.743 | word-identical, `cfgW` 0→1 | **0.224 s** | 900.32 s |

Case study 5 restart 2's lead was 0.124 s — the same. **The `cfgW` flip is the primary settling
~0.8 s after its water stops (case study 5 §6's own finding), not a fingerprint of authorship.**
It never excluded the controller. And +1.087 s is inside the band measured here.

## 8. ⚠️ The bug: the warning for this exact situation cannot fire

All seven controller cuts were journalled `verdict: "ignored"`, `reason: "duration is not within
10s of any limit"`, `off_by: ~2699`. **No warning was logged. Nothing told the owner why the
shower stopped.**

`runtime_cutoff.py` puts the mismatch warning *after* the limit match:

```python
if match is None:
    stop("duration is not within 10s of any limit", off_by=...)   # ← all 7 land here, silently
    continue
if not is_paused:
    _LOGGER.warning("... check that the ... durations ... are set to the SAME value")
```

With the valve at 3600 s, a 900 s stop matches no announced limit, so it takes the silent
branch. **The warning session 10 added to catch mismatched durations can only fire when the
durations already agree** — the one case where it is not needed. Not yet fixed.

## 9. ❌ Falsified here: message ordering says nothing about authorship

[Session 11](../handoff/2026-08-19_session11_current.md) floated that a HUB status message
*preceding* the GCS one might mark a controller-initiated stop, on a 0.037 s inversion.

**Dead.** All eight stops here are unambiguously controller-authored — its own timer, the valve
inert at 60 min — and the **GCS message arrived first every single time**, by +0.371 to
+0.594 s. Ordering carries no information about who initiated.

## 10. Corrections this case study makes

| what | now |
|---|---|
| CS5's `00/00`, "unexplained", open item #1 | **the controller's 900 s sweep**, at 900.79 s, zeroing a zone whose controller clock read 1393 s |
| CS3's `00/00` attribution, retracted by session 10 | retraction rests on `cfgW` reasoning falsified in §7b; +1.087 s is inside the measured band |
| CS4 §5: "a `0x40` pause self-terminates after ~2 min" | **the session ends ~120 s after all water stops**, pause or no pause. Three counterexamples here with zero `0x40`. |
| `intro.md` §3a: "40 of 61 teardowns at 119.6–120.7 s" | same measurements, different mechanism — session end, not pause teardown |
| Session 11: HUB-message-first implies controller-initiated | **falsified**, §9 |
| "The controller times each zone" | it arms timers on events and **sweeps all zones** when one fires |

## 11. The experiment this specifies

Run with **GCS 60 min, HUB 15 min, Endless Shower OFF**, zone 2 never opened, temperature and
flow untouched after the start.

* **Run 1** — start zone 1 alone by `valveOnOff`; expect a cut at ~15 min; reopen zone 1 from
  the touchscreen **within 60 s**, while the Anthem Plus screen is still lit (same controller
  session, per §6); wait 16 min.
* **Run 2** — a separate shower, started by opening zone 1 alone **from the touchscreen**; wait
  16 min.

| Run 1 | Run 2 | conclusion |
|---|---|---|
| not cut | cut | **same-session restart is the blocker** — the controller will not re-arm a zone inside a session it has already timed |
| not cut | not cut | the **start route** decides arming |
| cut | cut | arming is flaky, not rule-governed |

⚠️ **Restore matched durations before re-enabling Endless Shower**, or §8's silent failure is
live.

## 12. Open

1. **What arms a timer** (§5). The experiment in §11 is running.
2. **Which zones a sweep clears is fully explained; which events arm one is not.** Control
   events (a setpoint change) can arm one — §5.
3. **§8's warning bug.** Cheap fix, not done.
4. Whether the ~120 s session-end value is configurable, and whether it is the same 2 minutes
   on both products.

## 13. Sources

| claim | source |
|---|---|
| Leg boundaries, durations, verdicts | `cutoff_20260819T{194552,202559,212223}Z_*.jsonl` |
| Valve words, `cfgW`, message ordering | `mqtt_raw_20260819T{194552,202559,212223}Z_*.jsonl` |
| Session-end revert table | all captures on or after 2026-08-15 |
| Two independent session ends, screen behaviour | **owner, 2026-08-19** — physical screens, not the wire |
| CS5 arithmetic | `05_three_restarts_and_the_unexplained_00.md` §2, §4 |
