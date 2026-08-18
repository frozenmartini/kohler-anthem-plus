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
   about device state. The cloud can push a redundant or stale card update.
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

The controller's entire water surface in the Konnect app is **`valveOnOff` and favourites** —
read-rich, write-poor. `SHOWER_VALVE_STS` carries per-zone status, outlets, temperature and
flow for the card to *display*, but the only things that can be *pressed* are one on/off
toggle and a stored favourite. `valveOnOff` takes no parameters: it runs whatever
`get_valve_settings` holds as the default.

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
