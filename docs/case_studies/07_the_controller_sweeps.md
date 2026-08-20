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
> limit.** 15 of 16 zone-decisions across three showers follow that rule exactly.
>
> **And there is a bug in the sweep — §5.** A **zone-2** sweep silently **disarms zone 1's
> timer**, so zone 1 loses its maximum-duration protection until some later sweep happens to
> catch it over the limit. It is one-directional: a zone-1 sweep leaves zone 2 alone. Simulated
> against five sessions it reproduces **14 of 14** controller-driven stops with **zero** false
> alarms, including [case study 5](05_three_restarts_and_the_unexplained_00.md)'s `00/00`, which
> two case studies had recorded as unexplained.
>
> **Tested against Anthem Plus controller firmware — application `2.88`, OS `5.4`.**

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
| **Anthem Plus firmware** | **application `2.88`, OS `5.4`** | `captures/20260810_*_hub_config.json`, `/configuration/about/firmware`. ⚠️ Read **2026-08-10** and not re-read since — the PIN file did not survive the container being recreated. `firmwareUpdate: noUpdateAvailable` in every capture since is weak corroboration that it has not moved. |

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

## 5. ⭐ THE MECHANISM — a zone-2 sweep disarms zone 1

**Owner's hypothesis, 2026-08-19. Simulated against the corpus with
`kohler-work/sweep_sim.py` and confirmed.** This section supersedes an earlier reading of the
same data as "zone 1 only arms when zone 2 is idle" — that was the correlation; this is the
cause.

### 5a. The rule

* **Every zone the controller sees start flowing gets a timer**, due `LIMIT` seconds later.
  **The start route is irrelevant.** `valveOnOff`, the Anthem Plus touchscreen and Home
  Assistant's `solowritesystem` all arm one. All that matters is that the controller
  acknowledges the zone as flowing.
* When a timer fires it **sweeps**: every zone currently flowing at or over `LIMIT` is cut.
* ⚠️ **THE BUG — a zone-2 sweep also disarms zone 1.** Zone 1 then has no maximum-duration
  protection at all until some later sweep happens to find it over the limit and takes it down
  as collateral.
* **The bug is one-directional.** A zone-1 sweep does **not** disarm zone 2. Shower 2's zone-1
  cut at 13:47:33 left zone 2's timer intact and zone 2 was cut on its own schedule 166 s later.
* **The disarm only happens when the sweep actually cuts zone 2** — that is, when zone 2 was
  still flowing as its timer came due. If something else had already stopped zone 2, the sweep
  runs, cuts nothing, and **leaves zone 1 armed**. That single condition is what separates case
  study 5 from every session here (§5d).

### 5b. Simulated against five sessions

`sweep_sim.py` replays the observed zone start/stop events and scores which stops each model
explains. A false alarm is a cut the model insists on that did not happen.

| model | hits | false alarms |
|---|---|---|
| **A** — zone-2 sweep disarms zone 1, unconditionally | 13 | 0, but **cannot produce case study 5's `00/00`** |
| **C** — no disarm, plain per-zone timers + sweep | 14 | **3** — insists zone 1 dies at 13:09:20, 14:07:13 and 14:47:08 |
| **E** — disarm only when the sweep actually cuts zone 2 | **14** | **0** |

Model C's three false alarms are precisely the three zone-1 overruns. **The disarm is required
to explain them.** Model E is the rule in §5a.

The eight stops model E does not predict are all outside its scope: four valve `0x40` pauses in
case study 5, the 16:29:49 pair ending that session, the owner's manual off at 12:48:05, and
14:58:15 — the one anchored to a **setpoint change** rather than a flow start, which the
simulator does not model. See §12.

### 5c. Shower 2, reproduced from the rule alone

```text
13:32:32  zone 1 opens             → arm z1, due 13:47:32
13:41:18  zone 2 opens             → arm z2, due 13:56:18
13:47:32  z1 fires → sweep         → z1 over → CUT            observed 13:47:33.614 ✓
                                   → z2 at 374 s, spared, TIMER UNTOUCHED
13:52:13  zone 1 reopens           → arm z1, due 14:07:13
13:56:18  z2 fires, z2 flowing     → z2 over → CUT            observed 13:56:19.691 ✓
                                   → z1 at 245 s, spared
                                   → ⚠️ z1's ARM CANCELLED     14:07:13 never happens ✓
14:02:44  zone 2 reopens           → arm z2, due 14:17:44
14:17:44  z2 fires → sweep         → z2 over → CUT
                                   → z1 now 1531 s → CUT      observed both 14:17:45.629 ✓
```

Every cut, **and the non-cut at 14:07:13**, from the rule.

### 5d. Case study 5's `00/00`, derived

```text
15:51:00.260  zone 2 opens                → arm z2, due 16:06:00
15:59:12.974  zone 1 opens                → arm z1, due 16:14:12
16:06:00.114  VALVE pauses zone 2                  ← the valve wins by 0.146 s
16:06:00.260  z2 timer due — ZONE 2 ALREADY STOPPED
                                          → sweep runs, cuts nothing
                                          → z1's arm SURVIVES   ← the whole difference
16:14:12.891  VALVE pauses zone 1
16:14:12.974  z1 fires → sweep            → zone 2 flowing at 1392.5 s → CUT
                                                     observed 16:14:13.766 ✓
```

The `00/00` two case studies could not explain falls straight out of the rule. Both maximums
were 900 s there, so the valve beat the controller to zone 2 — and that is exactly the case
where the disarm does not happen.

### 5e. The one-line statement

> **A zone-2 timeout sweep silently disarms zone 1's timer, so zone 1 loses its
> maximum-duration protection until a later sweep catches it over the limit.**

Consequence for anyone running this hardware: **with the controller as the authority, zone 1's
15-minute limit is not enforced** whenever zone 2 has timed out during the session. It overran
by **13:05, 10:32 and 11:07** here, and was only ever stopped as collateral.

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

### 6a. ⚠️ The ~120 s value is not fixed

A seventh measurement, from the setup leg of the 2026-08-19 experiment, does not fit:

```text
16:06:32.945  water off by hand, temp 0x190 (400) = 104.0 °F
16:07:12.957  +40.01s   zone 1 reverts to 0x184 (388)
16:07:13.065  +40.12s   zone 2 reverts
```

**40.1 s, well outside the 118.68–121.09 s cluster.** The only visible difference is that this
leg was **stopped by hand**, where all six clustered cases were stopped by a timer. The
ordering claim — the session ends *after* the water stops, not at it — is unaffected; the
**value** is not a constant, and should not be quoted as one.

### 6b. ⚠️ This corrects case study 4

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
durations already agree** — the one case where it is not needed.

### 8a. ✅ Fixed the same day — but never yet exercised on hardware

**Corrected 2026-08-20; §12 item 3 and session 11 §4b both still said "not fixed".** The silent
branch stopped being silent in `1f19b33`, rebuilt in `4aa2fc5`: `match is None` now calls
`suspected_controller_limit(duration)` and, when that returns a limit, logs a WARNING naming the
controller's ceiling and telling the owner to match the two durations. Two qualifications, both
real:

* It fires only for a stop **on a whole-minute boundary overshot by `CONTROLLER_LATE_WINDOW`
  = (0.2, 2.0) s** and only when the stop carries no pause flag. That is the discriminator §11's
  measurements support — 15 of 15 journalled cutoffs, one false positive in 62 stops — not a
  guarantee that every mismatched stop is named.
* **It has never fired on hardware.** Core was restarted at 18:46 on 2026-08-19, between
  `1f19b33` (18:43) and `4aa2fc5` (20:44), so that evening's showers ran the superseded
  four-value table and its controller-shaped stops at **300.78 s** and **180.46 s** — 5 min and
  3 min, dead centre of the late window — were journalled with no hint. The minutes rule went
  live at the **2026-08-20 00:53** Core restart. First real controller cutoff after that date is
  the test.

The complementary half is `fd2b3ff`'s arm-time warning, which fires on every start regardless of
what stops the shower, and was observed working at 00:54 on 2026-08-20.

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
| "Zone 1 arms only when zone 2 is idle" (this study, first draft) | a correlation, not the cause. **Zone 1 always arms; a zone-2 sweep disarms it** — §5 |
| "Zone 1's arming is unreliable" | **it is not.** With zone 2 never opened, zone 1 armed 4 of 4 (§11) |
| The ~120 s session-end delay as a constant | one measurement at **40.1 s** — §6a |

## 11. ✅ The experiment, run 2026-08-19 16:11–17:19

Run to the protocol in §5's predecessor: **GCS 60 min, HUB 15 min, Endless Shower off, zone 2
never opened, single outlet, temperature constant at `0x184` (388) 101.8 °F.** The owner added a
fourth leg beyond the specified three.

| leg | opened | route | gap from previous cut | cut at |
|---|---|---|---|---|
| 1 | 16:11:43.975 | `valveOnOff` | — | **900.45 s** |
| 2 | 16:27:02.441 | touchscreen | **18.0 s** — same session, screen still lit | **901.25 s** |
| 3 | 16:48:43.192 | touchscreen | 398.7 s — new session | **900.51 s** |
| 4 | 17:03:58.979 | touchscreen | **15.3 s** — same session | **900.55 s** |

**4 of 4 cut.** What it settled:

* **"Arms once per session" is dead.** Legs 2 and 4 reopened 18.0 s and 15.3 s after a cut,
  inside the grace, and both re-armed and were cut.
* **"The start route decides" is dead.** Three of four legs were touchscreen-opened; all armed.
* **Zone 1's timer is not unreliable.** With zone 2 never opened there was nothing to disarm it,
  and it fired every time — which is what pointed at §5's mechanism.

⚠️ **The protocol had a design flaw, recorded so it is not repeated.** It required zone 2 to
stay closed, to stop its sweep confounding the read. Zone 2's sweep **is** the mechanism, so the
experiment was structurally incapable of observing it and could only eliminate the two wrong
hypotheses. It did that decisively; the mechanism came from simulation afterwards.

### 11a. The test still outstanding

The disarm has been observed only with zone 2 timing out **while flowing**. To confirm §5a's
condition directly rather than by simulation:

> Open zone 2 and let it run. Open zone 1 a few minutes later. Before zone 2's 15 minutes are
> up, **stop zone 2 by hand.** Then watch whether zone 1 is still cut at its own 15 minutes.
>
> Cut → the disarm needs zone 2 to actually be swept, as §5a says and case study 5 implies.
> Not cut → the disarm happens on expiry regardless, and case study 5 needs another explanation.

## 11b. ⚠️ CONTRADICTED — 2026-08-19 evening, zone 1's timer survived a zone-2 sweep

Three showers later the same evening, with `maxshowerduration` written to short values over the
local API ([`../hub/local_api.md`](../hub/local_api.md) §3b), produced a case §5's rule does not
predict.

**Shower at 20:15:17, controller set to 3 min, Endless Shower OFF, GCS at 900 s:**

```text
20:15:17.262  zone 2 opens
20:16:22.057  zone 1 opens          (zone 2 already running, 64.8 s in)
20:18:17.723  zone 2 CUT at 180.46 s  (+0.46 s)   ← a zone-2 sweep, which by §5a
                                                    should have disarmed zone 1
20:19:22.695  zone 1 CUT at 180.64 s  (+0.64 s)   ← but zone 1's timer fired on schedule
```

Zone 1 was at 115.7 s when zone 2's sweep ran — correctly **spared**, as the sweep model says.
But its timer was **not** disarmed: it fired 65 s later on its own anchor, +0.64 s late, exactly
like a healthy controller cutoff.

**§5's disarm rule predicts zone 1 runs on unwatched here. It did not.**

Also from the same evening, a second thing §5 does not model: in the 19:53 shower, zone 1 was
turned off **by hand** at 46.3 s and reopened after a **64.4 s** gap, and its cutoff came at
**300.57 s measured from its FIRST start** — the gap did not re-anchor its controller clock.
The 2026-08-19 afternoon experiment had shown re-anchoring at **18.0 s** and **15.3 s**.
Those two observations cannot both be explained by a single gap threshold.

⚠️ **Not resolved here, and deliberately not patched.** The disarm is well evidenced across
five sessions (§5b: 14 hits, 0 false alarms, and removing it produces exactly the three
overruns). This is one session against it. Whether the difference is the duration (180 s vs
900 s), the Endless Shower switch being off, or something else is unknown. **Case study 6
exists because this project has twice turned an n≈5 pattern into a confident rule.** Recorded
as a contradiction, not folded into the model.

## 12. Open

0. ⭐ **§11b's contradiction.** A zone-2 sweep did not disarm zone 1 on 2026-08-19 evening,
   and a 64.4 s hand-off gap did not re-anchor a controller clock that an 18.0 s gap did.
   Highest-value open item — it bears directly on §5.
1. **What else arms a timer.** Flow starts do; a **setpoint change** apparently does too — the
   14:58:15.743 sweep traces back 900.32 s to the owner's touchscreen temperature change at
   14:43:15.423, with no zone starting then. `sweep_sim.py` does not model this, and it is the
   one controller-driven stop the model cannot produce.
2. **§5a's condition, confirmed only by simulation.** The direct test is §11a.
3. ~~**§8's warning bug.** Cheap fix, not done.~~ **Done in `1f19b33` / `4aa2fc5`** — see
   §8a. What is still open is *evidence*: the fix has never met a real controller cutoff.
4. **The session-end delay is not a constant** — six cases at ~120 s, one at 40.1 s (§6a).
   Timer-stopped versus hand-stopped is the visible candidate.
5. **Whether the disarm survives a firmware update.** Everything here is
   **application `2.88` / OS `5.4`**, and that reading is from 2026-08-10 (§1).

## 13. Sources

| claim | source |
|---|---|
| Leg boundaries, durations, verdicts | `cutoff_20260819T{194552,202559,212223}Z_*.jsonl` |
| Valve words, `cfgW`, message ordering | `mqtt_raw_20260819T{194552,202559,212223}Z_*.jsonl` |
| Session-end revert table | all captures on or after 2026-08-15 |
| Two independent session ends, screen behaviour | **owner, 2026-08-19** — physical screens, not the wire |
| CS5 arithmetic | `05_three_restarts_and_the_unexplained_00.md` §2, §4 |
| The experiment, four legs | `cutoff_20260819T212223Z_72_701402e1.jsonl`, `mqtt_raw_20260819T212223Z_72_52ea9d5b.jsonl` (same connection, appended) |
| Model scoring, 14 hits / 0 false alarms | `kohler-work/sweep_sim.py`, five sessions |
| Controller firmware 2.88 / OS 5.4 | `captures/20260810_133428_hub_config.json` `/configuration/about/firmware` |
| The mechanism itself | **owner's hypothesis, 2026-08-19**; simulated and confirmed here |
