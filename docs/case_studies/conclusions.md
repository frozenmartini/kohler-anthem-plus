# Conclusions — how max shower duration works, and what Kohler broke

**Synthesis across case studies 1–7, 2026-08-19. Every figure below comes from a case study's
own logs; each row names its source. Nothing here is inferred from anything outside them.**

> ### ⚠️ MQTT is the Konnect app's UI channel — not device communication
>
> Read [`intro.md`](intro.md) §1 before using any of this. Absence of a message means "no card
> change to push", never "a device was silent". Conclusions about what a device *knew* rest on
> **behaviour** — a timer firing, water moving. Two findings here come from the **physical
> screens** and are marked as such.

**Firmware under test: Anthem Plus controller application `2.88`, OS `5.4`.** Valve firmware
`PrimaryValveFirmwareVersion: 10`. Everything below is specific to those versions.

---

## Part A — How it works

### A1. Two products, two limits, two clocks, no cooperation

| | **GCS valve (Anthem)** | **Anthem Plus controller** |
|---|---|---|
| setting | `maximumRunTime` | `maxshowerduration` |
| granularity | **per outlet**, but **timed per zone** | one value for the controller |
| values seen | 900 / 1800 / 3600 s | dropdown offers only **15 / 30 / 45 / 60 min** |
| how to read it | MQTT `READ_GCS_OUTLET_CONFIG_CFG`, or REST `gcsadvancestate` | local API `GET /web/api/v1/device/get_valve_settings` [[2 §8]](02_hub_commanded_shower_15min.md) |
| **stop signal** | **`0x40`** — pause flag set in byte 3, mask cleared | **`0x00`** — plain mask clear, no flag |
| **timing** | **early, always** | **late, always** |
| implementation | firmware countdown | **software sweep** [[7 §5]](07_the_controller_sweeps.md) |
| session ends | at `0x40/0x40` — GCS screen shows totals, goes dark | **~120 s after all water stops** — Anthem Plus screen shows totals, goes dark |

The valve's clock **starts when a zone goes from nothing flowing to something flowing, and does
not reset when outlets change within that zone.** Confirmed to **0.013 s** across two
independent zone cutoffs 136.7 s apart [[6 §4b]](06_two_cutoffs_and_a_prediction_that_failed.md).

### A2. The valve fires early. The controller fires late. They never overlap.

**Valve — 7 measurements, every one `0x40`:**

| duration | limit | offset | source |
|---|---|---|---|
| 3599.768 s | 3600 | **−0.232 s** | [1](01_ha_driven_shower_hub_blind.md) |
| 899.918 s | 900 | **−0.082 s** | [3](03_both_ceilings_at_15_minutes.md) |
| 899.85 / 899.92 / 899.84 s | 900 | −0.15 / −0.08 / −0.16 s | [5](05_three_restarts_and_the_unexplained_00.md) |
| 899.79 / 899.78 s | 900 | −0.21 / −0.22 s | [6](06_two_cutoffs_and_a_prediction_that_failed.md) |

→ **−0.08 to −0.23 s.**

**Controller — 13 measurements, every one `0x00`:**

| duration | offset | source |
|---|---|---|
| 900.557 s | **+0.557 s** | [2](02_hub_commanded_shower_15min.md) |
| 901.004 s | **+1.004 s** | [3](03_both_ceilings_at_15_minutes.md) |
| 900.30 · 900.33 · 900.41 · 900.45 · 900.51 · 900.55 · 900.60 · 900.85 · 901.12 · 901.16 · 901.25 s | **+0.30 to +1.25 s** | [7](07_the_controller_sweeps.md) |

→ **+0.30 to +1.25 s, never early.** A fourteenth, at **900.792 s**, is derived rather than
observed directly — case study 5's `00/00` [[7 §7a]](07_the_controller_sweeps.md).

**Consequence: with both durations set to the same value, the valve always fires first**, by
about a second. Case study 3 is the control — both at 900 s, both devices fired, **1.087 s
apart, neither deferring.**

### A3. The controller's cutoff is a sweep, not a countdown

* Every zone the controller **sees start flowing** gets a timer. **The start route is
  irrelevant** — `valveOnOff`, the Anthem Plus touchscreen and Home Assistant's
  `solowritesystem` all arm one.
* When any timer fires it **sweeps**: every zone currently flowing at or over the limit is cut.
  **15 of 16 zone-decisions** follow that exactly; the exception is a manual off
  [[7 §4]](07_the_controller_sweeps.md).
* It is **not a free-running poll** — a zone sat over its limit for 785, 632 and 667 s before
  anything looked at it.
* A **setpoint change can also arm a timer**: one sweep traces back 900.32 s to a touchscreen
  temperature change with no zone starting then.

### A4. Timing details that matter in practice

* **Warm-up counts toward the controller's ceiling** — a 15-minute setting yields less than 15
  minutes of showering [[2]](02_hub_commanded_shower_15min.md).
* **The controller's clock runs straight through a 1.2–2.2 s water interruption** without
  re-anchoring; it does re-anchor by 15.3 s. The threshold between is unmeasured.
* **A restore write does not re-anchor the *other* zone's valve clock** — verified with a whole
  system word rewritten 763 s into the other zone's session
  [[6 §4c]](06_two_cutoffs_and_a_prediction_that_failed.md).
* **A `00/00` does re-anchor both** — two zones that started 492.7 s apart were merged into one
  clock and cut together fifteen minutes later [[5 §4, §5]](05_three_restarts_and_the_unexplained_00.md).

---

## Part B — What is broken

**Every fault is on the controller. The valve is not implicated in any of them:** 7 firings
across 4 case studies, every one on time, correctly flagged, and enforced unconditionally.

### B1. ⭐ A zone-2 sweep silently disarms zone 1's timer

The headline defect. It is **one-directional** — a zone-1 sweep leaves zone 2 alone, proven
where zone 2 went on to be cut on schedule 166 s after a zone-1 cut. Zone 1 then has **no
maximum-duration protection at all** until some later sweep happens to catch it over the limit
and takes it down as collateral.

Measured overruns past a 15-minute limit: **13:05, 10:32 and 11:07.**

The disarm only happens when the sweep **actually cuts** zone 2 — if something else had already
stopped zone 2, zone 1 stays armed. Simulated across five sessions: **14 of 14 controller stops,
zero false alarms**; removing the disarm produces exactly three false alarms, the three
overruns. [[7 §5]](07_the_controller_sweeps.md)

### B2. The controller frequently does not know a shower is running

Its ceiling can only fire on sessions it registers, and it misses many. Across 130 water-on
episodes, restricted to the 95 where the controller was demonstrably alive
[[4 §8]](04_two_touchscreens_and_what_off_means.md):

| | saw the open (≤5 s) | caught up late | **never saw it** |
|---|---|---|---|
| **preset-driven** | **0** | 2 | **13** |
| no preset | 51 | 10 | **19** |

**Not once in 15 preset-driven openings has it reported the session as open.**

Worst single case: an **86-minute** shower during which the controller published **zero**
messages, with a 60-minute ceiling configured that never fired — on a healthy connection
carrying the valve's own messages throughout [[1]](01_ha_driven_shower_hub_blind.md).

### B3. It publishes states the valve never held

At one cutoff it pushed `z1=OFF z2=ON` when the valve had stopped **both**, zone 2's half stale
by 3½ minutes. For ~200 ms the app rendered a shower that never existed. It refreshes its two
zones independently and pushes after updating only one
[[5 §7]](05_three_restarts_and_the_unexplained_00.md).

Three times in the corpus it published `status: OFF` while water was running
[[4 §8]](04_two_touchscreens_and_what_off_means.md).

### B4. Mismatched durations fail silently

There is no negotiation between the two ceilings — **the shorter one simply wins.** With the
controller at 15 min and the valve at 60, the controller ends the shower with a `0x00` that is
byte-identical to somebody pressing off. Nothing announces why
[[2]](02_hub_commanded_shower_15min.md), [[7 §8]](07_the_controller_sweeps.md).

### B5. The session-end delay is not consistent

Six measurements cluster at **118.68–121.09 s**; one lands at **40.1 s**. The only visible
difference is that the outlier was stopped by hand rather than by a timer
[[7 §6a]](07_the_controller_sweeps.md).

### B6. What "off" means is ambiguous on the wire

Pressing off on the **first-generation touchscreen writes `0x40` on both zones** — a pause, not
a stop — byte-identical to a preset-driven cutoff
[[4 §4]](04_two_touchscreens_and_what_off_means.md). Nothing in the data distinguishes them.

---

## Part C — What this means operationally

* **Zone 2's limit is dependable. Zone 1's is not** — it holds only if zone 2 never times out
  during the session.
* **With both durations set equal, the valve's limit is the one that actually protects you.** It
  fires first every time, and it fires whether or not the controller knows the shower exists.
* **Set the two durations to the same value.** Not advice — the alternative is B4, a silent stop
  with no diagnostic.
* **The valve is the trustworthy authority.** Anything that depends on the controller enforcing
  a limit is depending on B1 and B2 not happening.

---

## Part D — Out of scope here

A **fourth timer** exists that no case study covers: a preset carries its own `time`,
independent of `maximumRunTime`, and the lower of the two ends the shower. Preset 1's is hidden
from both the touchscreen and the Konnect app. See [`../gcs/api.md`](../gcs/api.md), "two
independent timers".

## Part E — Still open

1. Whether the B1 disarm requires zone 2 to be **actually swept** — confirmed only by
   simulation. Direct test at [[7 §11a]](07_the_controller_sweeps.md).
2. What else arms a controller timer besides a flow start (a setpoint change appears to).
3. The controller's clock re-anchor threshold, somewhere between 2.2 s and 15.3 s.
4. Why B5's session-end delay varies.
5. Whether any of this survives a firmware update past `2.88` / `5.4`.
