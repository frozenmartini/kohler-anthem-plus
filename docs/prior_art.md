# Prior art

This integration exists because of two projects that came first, and it began as an attempt
to fix problems hit while using them.

## [kohler-konnect-ha](https://github.com/kenyonj/kohler-konnect-ha) — MIT

A working Home Assistant integration for the Anthem valve. The shape of the auth and config
flow here follows it, including reading the account id from the access token's `oid` claim.
The B2C sign-in itself is a different implementation — see
[`../anthem_plus/auth.py`](../anthem_plus/auth.py) for why the browser-redirect approach had
to be replaced — but the pattern came from there.

## [kohler-anthem](https://github.com/yon/kohler-anthem) — the Python library

A library for the same valve. It was the starting point here; several of its calls did not
work against this system, and tracing why is how this project began. The specific
disagreements are documented rather than argued:

| what | where |
|---|---|
| Temperature formula, and byte 3 read as a `ValveMode` enum | [`gcs/valve_hex.md`](gcs/valve_hex.md#superseded-readings) |
| `startpreset` posting `presetOrExperienceId` | [`gcs/api.md`](gcs/api.md) §2 |
| `start_warmup` sending no `warmUp` field, and `stop_warmup` clearing a preset instead | [`gcs/api.md`](gcs/api.md) §3a, §3d |

## Why the readings differ

**Both were decompiled from the same Konnect 3.0.1 APK used here**, so this is not a case of
a newer source. The difference is method: every protocol claim in `docs/` is checked against
live MQTT captures, and where the app's source and the wire disagree, the wire wins. A
decompile shows what the app believes; a capture shows what the device does.

That cuts both ways — two of the superseded readings in
[`gcs/valve_hex.md`](gcs/valve_hex.md#superseded-readings) are this project's own earlier
guesses, corrected the same way.

## What this adds

* **The Anthem Plus controller**, not just the valve — music, lighting, steam, and the
  controller's own shower session, which neither project above covers.
* **Push instead of polling.** kohler-konnect-ha polls REST every 10 seconds. This subscribes
  to Kohler's Azure IoT Hub MQTT stream and updates on the device's own events
  (`iot_class: cloud_push`, no polling loop). For automations that fire on a shower starting
  or a run-time cutoff, that is sub-second rather than up-to-ten — and a 10-second poll can
  miss the `0x40` pause entirely, since it may resolve in about a second.
