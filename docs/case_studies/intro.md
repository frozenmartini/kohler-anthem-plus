# Case studies — read this before any of them

Complete single-session walkthroughs of the Kohler Anthem / Anthem Plus system, each one
quoted in full rather than summarised, so a later session can re-derive the conclusions
instead of trusting them.

---

## ⚠️ 1. The most important thing: MQTT is the app's UI channel, not device communication

**Everything in these documents is observed over MQTT. MQTT is not how the devices talk to
each other. Read every observation here with that in mind or you will draw wrong
conclusions — this project already did, twice.**

### What the MQTT stream actually is

Kohler's cloud pushes status as **Azure IoT Hub direct methods**. The integration
**registers its own client identity** on that hub, and the cloud then *invokes methods on
us* — `$iothub/methods/POST/ExecuteControlCommand/?$rid=N` — which we must acknowledge on
`$iothub/methods/res/200/`. See [`../../anthem_plus/mqtt.py`](../../anthem_plus/mqtt.py).

That is the shape of a **cloud talking to an app client**. As far as Kohler is concerned we
are a Konnect app instance, and the payloads are instructions about **what the app should
render** — which card, and with what on it. The `sku` / `sysid` inside each payload names the
card, not a sender.

### What actually carries device-to-device traffic

**The controller and the valve are joined by an RJ wired connection, and that is where the
real communication happens.** Owner-established, 2026-08-18. It is consistent with everything
else in the docs: the valve has [two interface ports](../architecture.md), the Anthem Plus is
wired to the second one, and during a controller power-cycle
[the valve saw the wired link return before the controller's web server came back](../gcs/valve_reboot_fault.md).

**We cannot sniff that link.** No document in this folder observes it. Every statement here
about what a device "knew" is an inference from something else.

### The four rules that follow

1. **"The HUB reported X" always means "the cloud told app clients to render X on the Anthem
   Plus card."** It never means one device told another device anything.
2. **Absence of a message means there was no card change to push.** It does **not** mean the
   device was silent, offline, broken, or unaware. Silence is weak evidence.
3. **Presence of a message is evidence about the cloud's model of the app UI**, not directly
   about device state. The cloud can push a redundant or stale card update — and it can be
   **actively wrong**: in [case study 5](05_three_restarts_and_the_unexplained_00.md) §7 the
   controller pushed a card showing one zone paused and the other running, for ~200 ms, when
   the valve had stopped both in a single word. It refreshes its two zones independently.
4. **To learn what a device actually knows, use device *behaviour*, not messages** — did its
   timer fire, did water move, did a mask change. Behaviour crosses the wired link; messages
   do not.

### The worked example, and why this matters

[Case study 1](01_ha_driven_shower_hub_blind.md) is an 86-minute shower during which the
controller published **nothing at all**. The tempting reading is "the controller was broken or
offline". The correct reading is:

* The shower was opened by Home Assistant through `solowritesystem`, straight at the valve.
* The controller's own model never changed, so **its card never changed, so there was nothing
  to push.** The silence is the expected output of a UI channel, not a fault.
* The valve's card *did* change — and the capture holds exactly five `GCS_SOLO_STS`, one per
  state change.

And the conclusion that the controller genuinely did not know rests on **behaviour, not
silence**: its 15-minute ceiling never fired in 86 minutes, and
[case study 2](02_hub_commanded_shower_15min.md) proves that ceiling works and fires within
0.6 s. A clock cannot run for a session the device is unaware of. That argument survives
even if every message had been lost.

> **This corrected an earlier mistake, recorded so it is not repeated.** Case study 1's §6a
> originally reasoned that a message "should have arrived" at a controller-commanded stop and
> did not, and treated that as evidence something was wrong. That expectation only makes sense
> if MQTT is device telemetry. It is not. There was never a message to expect.

---

## 2. What these case studies are for

**None of them is a test of Endless Shower**, the run-time cutoff restart feature. They exist
to establish the **command surface**:

* who can start and stop water, and by which route;
* which device then **owns** the session;
* whose timer runs, at what value, and what it signals when it expires;
* what each device reports, and to whom.

That has to be nailed down before the restart feature can be designed against it rather than
guessed at. Consequences for Endless Shower are noted where they fall out — they are
consequences, not the objective.

---

## 3. The command surface, as established so far

From [case study 1](01_ha_driven_shower_hub_blind.md) and
[case study 2](02_hub_commanded_shower_15min.md):

| | **HA `solowritesystem`** | **HUB `valveOnOff` / panel** |
|---|---|---|
| Does the controller know? | **No** | **Yes** |
| Controller session clock | not running | runs, anchored at the open |
| Controller card updates | none — nothing to render | ON, mid-session, OFF |
| Which timer ends the shower | GCS `maximumRunTime` | HUB max shower duration |
| Stop signal | **`0x40`** pause, per zone | **`0x00`** stop, both zones |
| Limit announced to the integration? | yes | **no** — local API only |
| Warm-up | none | five outlets, **counts toward the ceiling** |

**Which device owns a shower is fixed at the moment water starts, and nothing afterwards
changes it.** A shower started from Home Assistant cannot acquire a controller clock; one
started from the panel cannot shed it.

**When both clocks run, both fire.** [Case study 3](03_both_ceilings_at_15_minutes.md) set both
maximums to 900 s: the valve paused at 899.918 s and the controller stopped at 901.004 s,
1.087 s apart, neither deferring to the other. The controller enforces its ceiling
**unconditionally whenever it knows a session is running** — which is the positive control that
closes case study 1.

⚠️ **The open question across all four: why does the controller sometimes register a shower and
sometimes not?** [Case study 4](04_two_touchscreens_and_what_off_means.md) §8 shows it
acknowledging a `solowritesystem` open in 285 ms, and the corpus shows it doing so 51 times out
of 80 — yet in case study 1 it registered nothing for 86 minutes. Presets are one categorical
answer (**0 of 15** preset-driven opens ever seen), but case study 1 had no preset. **Treat
"the controller knows" as something to verify per session, never to assume.**

The controller's entire water surface in the Konnect app is **`valveOnOff` and favourites** —
read-rich, write-poor. `SHOWER_VALVE_STS` carries per-zone status, outlets, temperature and
flow for the card to *display*, but the only things that can be *pressed* are one on/off
toggle and a stored favourite. `valveOnOff` takes no parameters: it runs whatever
`get_valve_settings` holds as the default.

---

## 3a. What the five case studies established

Findings that outlived the session they came from. Each links to where it is argued in full.

### The valve

| finding | where |
|---|---|
| **A `0x40` pause left alone is held for ~120 s, then torn down** — the session ends and the setpoint reverts to `defaultTemp`. 29 of 38 teardowns in the corpus land at 119.6–120.7 s, on every start route. | [5 §9](05_three_restarts_and_the_unexplained_00.md), [4 §5](04_two_touchscreens_and_what_off_means.md) |
| **`configWriteAllowedFlag`: `1` = writes allowed, and it tracks zone 1 — the primary — being idle** (775 of 781). It is **not derivable from the command word**, so it is the only window found into valve state the four bytes do not carry. The primary goes idle ~0.8 s after its water stops. | [5 §6](05_three_restarts_and_the_unexplained_00.md) |
| **`atTemp` is a session latch, not a thermostat.** It survives a `0x40` pause, clears only on a full stop, and does not move across setpoint changes — sixteen of them, a 7 °F swing, both touchscreens. Most likely how the system decides whether to run warm-up. | [4 §6](04_two_touchscreens_and_what_off_means.md), [5 §8b](05_three_restarts_and_the_unexplained_00.md) |
| **Temperature survives a pause and a restore byte-exactly** — three restores at three setpoints, no drift. The whole-degree jump reported in session 9 has not recurred, and the `0x185` (389) arithmetic fingerprint last appeared 2026-08-14. | [5 §8a](05_three_restarts_and_the_unexplained_00.md), [`../gcs/valve_hex.md`](../gcs/valve_hex.md) |
| **Pressing off on the first-generation touchscreen writes `0x40` — a pause, both zones** — not a stop. Indistinguishable on the wire from a preset-driven cutoff. | [4 §4](04_two_touchscreens_and_what_off_means.md) |
| **The two touchscreens cannot be told apart on the wire.** Same message shape, one word per intermediate value, both zones. Apparent differences are drag speed. | [4 §7](04_two_touchscreens_and_what_off_means.md) |

### The controller

| finding | where |
|---|---|
| **Its ceiling is enforced unconditionally whenever it knows a session is running** — it fired even when the valve had already paused the zone a second earlier. That is the positive control behind case study 1. | [3 §7](03_both_ceilings_at_15_minutes.md) |
| **The ceiling equals the configured Max Shower Duration exactly**: 60 min → 3600.20 s, 15 min → 900.557 s. It overshoots by ~0.5–1.0 s. | [2 §6b](02_hub_commanded_shower_15min.md), [3 §4](03_both_ceilings_at_15_minutes.md) |
| **`maxshowerduration` is readable — but only over the LOCAL API**, `GET /web/api/v1/device/get_valve_settings`. Minutes as a string; the dropdown offers only 15/30/45/60. The same object predicts a controller-commanded shower completely. | [2 §8](02_hub_commanded_shower_15min.md), [`../hub/local_api.md`](../hub/local_api.md) |
| **Warm-up counts toward the ceiling**, runs the configured `warmupOutlets` (five here), ends on the controller's own judgement rather than the valve's `atTemp`, and carries **no pause** at the handoff. | [2 §6a](02_hub_commanded_shower_15min.md), [3 §8a](03_both_ceilings_at_15_minutes.md), [2 §6e](02_hub_commanded_shower_15min.md) |
| **It refreshes its two zones independently** and will push a card showing a state the valve never held — measured at ~200 ms. | [5 §7](05_three_restarts_and_the_unexplained_00.md) |
| **It has never reported `status: ON` at the opening of a preset-driven session — 0 of 15.** Ten times silent, three times publishing a confident `status: OFF` while water ran. `resolve_outlet_source()` is right to prefer the valve word; its stated cause (`solowritesystem`) is wrong. | [4 §8](04_two_touchscreens_and_what_off_means.md) |

### Home Assistant's own effects

| finding | where |
|---|---|
| **A restore can re-anchor the *other* zone's run-time clock**, merging two independent timers into one. Two zones that started 492.7 s apart were cut together fifteen minutes later. | [5 §4, §5](05_three_restarts_and_the_unexplained_00.md) |
| **Endless Shower can override the controller's ceiling**, not just the valve's — incidentally, because the restore is in flight when the stop lands. | [3 §5](03_both_ceilings_at_15_minutes.md) |
| **The restore's end-to-end latency is ~1.3–1.7 s** (POST ~0.6–1.0 s, valve application ~0.68 s), which is why it consistently lands *after* a competing stop rather than before. | [3 §5](03_both_ceilings_at_15_minutes.md), [5 §4](05_three_restarts_and_the_unexplained_00.md) |
| **The detector clears a zone's timer on any `flow_end`**, regardless of verdict — so a momentary mask-zeroing resets the clock even when the cutoff is ignored. | [5 §4](05_three_restarts_and_the_unexplained_00.md) |

### What this changed in the integration

**`runtime_cutoff.py` requires the `0x40` pause flag again, as of 2026-08-18.** Session 9 had
removed that requirement after the controller's ceiling ended a shower with `0x00` and Endless
Shower let it stay off. These case studies showed that was **two maximum durations set to
different values** (valve 900 s, controller 3600 s), not a protocol gap.

With the two set equal, the valve's early bias and the controller's late bias mean **the `0x40`
always arrives first**, so it is always the actionable signal and `0x00` never needs to be
acted on. A `0x00` at a matching duration is now declined, journalled with its own verdict, and
logged at WARNING naming mismatched durations as the likely cause — the safe failure direction
is water off, and it says why.

⚠️ **The accepted risk:** pressing off on the first-generation touchscreen writes `0x40` on
**both zones**, byte-identical to a preset-driven cutoff, so ending a shower within 10 s of the
limit restarts the water. No discriminator exists in the data. At a realistic 60-minute
setting that is a ten-second window in an hour.

### Open, and important

* **Why the controller sometimes registers a shower and sometimes does not.** Presets are one categorical answer; case study 1 had no preset. See §1's worked example.
* **Why a `00/00` teardown sometimes arrives in under a second** instead of at ~120 s. Nine such cases against 29 normal ones; the two clean instances both immediately follow a restore. [5 §10](05_three_restarts_and_the_unexplained_00.md)
* **Whether the controller counts a Home-Assistant-started session** toward its ceiling. Never run long enough to find out.
* **Whether a GCS preset starts the controller's clock.** The last unmeasured row of the start-route table.

---

## 4. Three classes of evidence, in order of strength

| class | what it is | how much to trust it |
|---|---|---|
| **Device behaviour** | a timer firing, water starting or stopping, a mask changing | **Strongest.** Crosses the wired link. Independent of the app channel. |
| **Configuration** | the controller's local API, the valve's REST config | **Strong, but it is intent.** It says what the device was told, not what it did. |
| **MQTT messages** | the app UI channel | **Weakest, and easy to over-read.** Presence and absence both need the §1 rules applied. |

Where a case study states something firmly, check which class it rests on. Where two classes
agree, say so — that is what makes a finding durable.

---

## 5. Conventions

* **Device values are stated hex first, decimal in parentheses** — `0xC8` (200) — because the
  same quantity has up to three encodings. Full detail in [`../../intro.md`](../../intro.md).
* Times are **local (PDT, UTC−7)** in narrative, **UTC** in quoted records, and both in
  timelines. ⚠️ The controller's own clock runs an hour ahead of local
  ([`../hub/local_api.md`](../hub/local_api.md)) — never correlate against a hub-side log
  without correcting for it.
* Each case study ends with an appendix holding **every raw record verbatim**, with the real
  `tenantid` replaced by `<TENANT_ID>` per the placeholder policy in
  [`../README.md`](../README.md). Device ids are left in place.
* Attribution is explicit: what came from a capture, what was computed, and **what the owner
  reported**. The capture can corroborate the shape of a command but never names a commander.

---

## 6. Out of scope, deliberately

**Ice shower, the ice-shower experience, and experiences generally — on both the GCS and the
HUB — are excluded from this line of work.** They are a separate feature family, driven as
presets and experiences rather than as ordinary shower control.

In particular `coldwatertimeout` in the controller's settings belongs to the ice-bath
function and is **not** a shower timer. An earlier reading of it as one was wrong.

---

## 7. Index

| | Session | Establishes |
|---|---|---|
| **[1](01_ha_driven_shower_hub_blind.md)** | 2026-08-18, 86 min, started by `solowritesystem` | The controller does not know, does not count, and does not render. Its 60-minute ceiling never fired. Silence explained by §1. |
| **[2](02_hub_commanded_shower_15min.md)** | 2026-08-18, 15 min, started by `valveOnOff` | The controller owns the session, cuts at exactly its configured 15 min with `0x00`, and renders every transition. **Warm-up counts toward the ceiling and carries no pause.** `maxshowerduration` is readable over the local API. |
| **[3](03_both_ceilings_at_15_minutes.md)** | 2026-08-18, both ceilings at 15 min, started by `valveOnOff` | The control. **Both devices fired — valve `0x40` at 899.918 s, controller `0x00` at 901.004 s, 1.087 s apart, neither deferring.** That closes case study 1: a mechanism that enforces unconditionally and did not fire there proves the controller never knew the shower existed. Endless Shower caught the pause and, incidentally, overrode the controller's ceiling too. |
| **[5](05_three_restarts_and_the_unexplained_00.md)** | 2026-08-18, two zones 8 min apart, both maximums 900 s | Three cutoffs. Restarts 1 and 3 normal; **restart 2 threw an unexplained `00/00` that zeroed both zones, reset the other zone's clock, and merged the two timers into one** — which is what caused restart 3. `configWriteAllowedFlag` established as the valve's own idle marker and the first window into state the command word does not carry. **The controller published a zone state the valve never held.** No temperature drift across three restores. Retracts case study 3's `00/00` attribution. |
| **[4](04_two_touchscreens_and_what_off_means.md)** | 2026-08-18, exploratory: HA-opened, then driven from both physical screens | **Pressing off on the first-generation screen writes `0x40` — a pause, both zones — and that pause self-terminates into `0x00` after ~2 minutes**, resetting the setpoint to default. `atTemp` is inert across 16 setpoint changes. The two touchscreens are indistinguishable on the wire. And the controller acknowledged an HA-driven open in **285 ms**, which amends case study 1's stated mechanism. |
