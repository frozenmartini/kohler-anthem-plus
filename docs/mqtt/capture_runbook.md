# Kohler MQTT Capture Runbook

Use this procedure to recreate an event-driven MQTT bridge for the Kohler
account. It forwards raw MQTT envelopes to local Mosquitto without saving
Kohler MQTT credentials.

> **For raw capture, you almost certainly want the integration's own, not this.**
> Since 2026-08-13 `kohler_anthem_plus` captures raw payloads itself — no second MQTT
> connection, no separate credentials, no bridge process. See
> [Raw capture from inside the integration](#raw-capture-from-inside-the-integration)
> below. The bridge in this runbook remains the right tool only when you need the messages
> *forwarded* to Mosquitto rather than written to disk.

## Raw capture from inside the integration

Every payload paho hands the integration, written before any decoding, so the messages the
decoder drops are captured too.

> **Two captures exist since 2026-08-22 — this section is the development one.** The
> **Report Log** switch on the device pages is the *consumer* capture: same record format,
> same pre-decode tap, but one file per switch-on, appended across restarts, written to
> `custom_components/kohler_anthem_plus/reports/`. It exists so a user can attach evidence
> to a GitHub issue without touching `logger.set_level` or `const.py`. Everything below —
> the logger switch, the pinned constant, `/config/kohler_anthem_plus_raw/`, the per-run
> files — is the development machine and is unchanged by it
> (`anthem_plus/report_log.py` has the full design).

**Switch it on with no restart and no file edit** — Developer Tools → Actions →
`logger.set_level`, switched to YAML mode:

```yaml
action: logger.set_level
data:
  custom_components.kohler_anthem_plus.anthem_plus.raw_log: debug
```

Set the same key to `info` to stop; the file is released on the next message.

Three things about that action that trip people up:

* **It is per-logger, not system-wide.** `logger.set_level` takes a free-form mapping of
  *logger name → level* — the whole `data:` block is that mapping. There is no `entity_id`
  and no nesting, because a logger is not an entity and has no entity id. The system-wide
  service is the other one, `logger.set_default_level`.
* **Only this exact name works.** Capture reads the level set on *this logger*, not the
  effective level, so `custom_components.kohler_anthem_plus: debug` or `logger: default:
  debug` will **not** start it. That is deliberate: debugging the integration should not
  silently begin writing files to disk.
* **It does not survive a restart** — which is the right default for a capture. To pin it on
  across restarts, set `ENABLE_RAW_MQTT_LOG = True` in the integration's `const.py`.

**Where it lands:** `<config>/kohler_anthem_plus_raw/`, alongside a `README.txt` explaining
the format and how to turn it off. Mind the two mount points for that one directory — Home
Assistant core sees it as `/config/kohler_anthem_plus_raw/`, but **from the terminal add-on
where these sessions run it is `/homeassistant/kohler_anthem_plus_raw/`.** One JSON object
per line:

```json
{"ts":"2026-08-13T15:04:28.123456Z","topic":"$iothub/methods/POST/…","qos":1,"retain":false,"payload":"{\"sku\":\"GCS\",…}"}
```

`payload` is the payload text **exactly as received** — not a re-serialised dict, so key
order, duplicates and numeric formatting survive. Bytes that are not valid UTF-8 appear as
`payload_b64` instead, with no `payload` key.

Files roll at 8 MB. **There is no limit on the number of files** — `RAW_MQTT_LOG_KEEP_FILES`
and `CUTOFF_DEBUG_LOG_KEEP_FILES` are both `None` as of 2026-08-15, at the owner's request, so
the directory is a permanent record rather than a rotating buffer. It grows in file count and
needs occasional manual clearing; deleting files is always safe. Nothing is created on disk
until a message arrives while capture is on.

To find every part of the feature in the source:

```sh
grep -rn "RAW MQTT LOG" custom_components/kohler_anthem_plus/
```

That hits `anthem_plus/raw_log.py` (the module), the constants in `const.py`, the call site
in `anthem_plus/mqtt.py:_on_message`, and the wiring in `coordinator.py`. Deleting those four
blocks removes it completely.

### The cutoff debug log — the companion file in the same directory

The run-time cutoff detector writes its own decision trail to `cutoff_*.jsonl`, **in the same
directory and stamped from the same clock**, so the two files interleave by sorting on `ts`.

It exists because the cutoff feature's real failure mode is *silence*: `home-assistant.log`
gets a WARNING when the water is restarted, and nothing whatsoever when a cutoff should have
been detected and wasn't. That is the case that shipped undetected for a day. This log
records every close the detector evaluated, including the ones it declined and why.

Same two switches, independent of the raw capture:

```yaml
action: logger.set_level
data:
  custom_components.kohler_anthem_plus.anthem_plus.cutoff_log: debug
```

…or `ENABLE_CUTOFF_DEBUG_LOG = True` in `const.py` to pin it across restarts. Volume is a
handful of lines per shower, so leaving it on for days costs nothing.

```json
{"ts":"2026-08-14T02:07:11.108Z","event":"flow_end","zone":1,"duration":900.07,"limits":[900],"mask":4,"paused":true,"verdict":"cutoff","matched":900}
{"ts":"2026-08-14T02:11:20.441Z","event":"flow_end","zone":2,"duration":249.1,"limits":[900],"mask":2,"paused":false,"verdict":"ignored","reason":"stopped (0x00) rather than paused (0x40) — not the valve's timer"}
```

Events are `arm` (what the feature could act on at startup), `flow_start`, `mask_change`,
`flow_end` (the verdict), `restore` / `restore_done` / `restore_failed`, and `forget`.

Reading the pair together — a `GCS_SOLO_STS` in the raw log whose valve word carries `0x40`,
against the `flow_end` written in the same instant — is the fastest way to answer "why did
this not fire":

```sh
cd /homeassistant/kohler_anthem_plus_raw
jq -c '{ts, code:(.payload|fromjson|.data.code)}' mqtt_raw_*.jsonl > /tmp/a.jsonl
jq -c '{ts, event, zone, verdict, reason}' cutoff_*.jsonl > /tmp/b.jsonl
cat /tmp/a.jsonl /tmp/b.jsonl | sort -t'"' -k4 | less
```

The **Start new MQTT capture** button rolls both files together, so each experiment leaves a
matched pair. Source markers:

```sh
grep -rn "CUTOFF DEBUG LOG" custom_components/kohler_anthem_plus/
```

## Known Devices

| SKU | Device ID | Description |
|---|---|---|
| `GCS` | `gcs-sio32343h7` | Anthem digital valve (Wi-Fi valve body) |
| `HUB` | `gcs-sious0103D` | Anthem Plus system controller |

The account-level direct-method subscription can deliver messages for both
devices. Filter forwarded messages by the payload field `deviceid`.

## Important Environment Rules

Run from the standalone scripts directory:

```sh
cd /root/homeassistant/scripts/kohler_konnect_custom
```

Use Home Assistant's virtual environment:

```sh
python3
```

Do not run the helper while the current working directory is `/homeassistant/custom_components/kohler`. Its `select.py` can shadow Python's standard-library `select` module and cause imports such as `asyncio` to fail.

The helper is loaded by file path so the integration directory does not need to be added to `PYTHONPATH`:

```python
module_path = "/homeassistant/custom_components/kohler/debug_get_presets.py"
spec = importlib.util.spec_from_file_location("kohler_debug_get_presets", module_path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
```

## Authentication and Registration

1. Load the single Kohler config entry from the canonical directory:

   ```python
   entry, _ = helper.load_kohler_entry(Path("/homeassistant"), None)
   ```

   Pinning `/homeassistant` is important because `/config`, `/homeassistant`, and `/root/homeassistant` may resolve to the same mounted file. Searching all three can make the helper report duplicate config entries.

2. Build and connect the API client:

   ```python
   api_client = helper.build_client(entry.get("data", {}))
   await api_client.connect()
   ```

3. Get the tenant ID from the config entry, with JWT fallback:

   ```python
   entry_data = entry.get("data", {})
   tenant_id = entry_data.get("tenant_id") or helper.decode_tenant_id(
       helper.access_token_from_client(api_client)
   )
   ```

4. Register a temporary mobile client to obtain IoT Hub settings:

   ```python
   settings = await api_client.register_mobile_device(tenant_id)
   ```

   The returned settings contain the IoT Hub hostname, mobile MQTT client ID, username, and temporary SAS password. Never print or save the username/password values.

## MQTT Connection

Use the registered mobile identity for the MQTT connection. Do not use the shower device ID as the MQTT client ID.

```python
mqtt_client = mqtt.Client(
    client_id=mobile_device_id,
    protocol=mqtt.MQTTv311,
    transport="tcp",
)
mqtt_client.username_pw_set(username, password)
mqtt_client.tls_set()
mqtt_client.connect_async(host, 8883, keepalive=60)
mqtt_client.loop_start()
```

`keepalive=60` is an MQTT heartbeat interval, not a 60-second connection limit. The connection can stay open for the capture window as long as the SAS token and network session remain valid.

## Subscriptions

Subscribe to all four topics used successfully in the captures:

```python
topics = [
    f"devices/{mobile_device_id}/messages/devicebound/#",
    f"devices/{target_device_id}/messages/events/#",
    f"devices/{target_device_id}/messages/devicebound/#",
    "$iothub/methods/POST/#",
]
```

The important status messages arrived on:

```text
$iothub/methods/POST/ExecuteControlCommand/?$rid=N
```

The `$iothub/methods/POST/#` topic is account-level. It is the reason a HUB capture also received GCS messages. Filter by `payload.deviceid` and `payload.sku`.

## Hold the connection — and reuse the identity

**A client that connects per command receives nothing, ever.** That part is solid. The
"60-second warm-up" that used to be stated here is not, and is corrected below.

Measured 2026-08-12 on one connection held for 400 s:

```text
t+  0.2s  SUBACK x4                                    (all four topics, qos 1)
t+ 60.1s  command  ->  t+ 61.2s  GCS_SOLO_STS          received
t+150.7s  command  ->  t+152.5s  GCS_SOLO_STS          received
t+241.9s  command  ->  t+243.1s  GCS_SOLO_STS          received
t+330.6s  command  ->  t+332.0s  GCS_SOLO_STS          received
```

Every command on the held connection produced a message within 1–2 s, while four earlier
attempts received nothing at all.

### Correction: the 60 s figure does not survive its own evidence

This section previously concluded "a newly registered mobile device receives nothing for
roughly the first minute". **Two problems with that.**

**The comparison was confounded.** The four failing attempts did not merely fire *early* —
they each connected, fired, and **disconnected inside a minute**. That design cannot
separate "too soon after connect" from "torn down before the reply arrived", and the reply
takes 1–2 s. Elapsed time was never isolated.

**The capture logs contradict it.** Across 27 bridge sessions — every one of them a freshly
registered identity — five received their first message *inside* the supposed window:

```text
37.1s   47.7s   50.5s   56.6s   59.0s
```

A 60-second blackout cannot be true if a fresh identity received data at 37 s.

Independently, a plain MQTT client (MQTT Explorer) connected with a **pre-existing** identity
sees messages flow immediately, with no warm-up of any kind.

### What to actually rely on

- **Hold one connection.** Connect-per-command receives nothing. Well supported.
- **Reuse one registered identity.** `mobileDeviceId` is an *identity*, not a credential:
  generate it once and persist it. Passing `None` mints a throwaway, so every connect leaves
  another dead "phone" registered on the account. The SAS password still must be fetched
  fresh each connect.
- **A newly registered identity may need a moment.** Plausible, weakly evidenced, and now
  hard to retest since a persisted identity is only ever registered once. Treat any wait as
  a cap on how long silence is uninformative — and note that **a delivered message settles
  it instantly**, which is a far better signal than any timer.
- Any experiment that connects, fires a command, and disconnects inside a minute produces a
  false negative. Several conclusions in these documents were drawn exactly that way and had
  to be retracted — see the correction in [architecture.md](../architecture.md).

Also observed on the same connection: **unprompted status pairs** roughly every three
minutes (t+189.5 s, t+370.4 s) with no command sent, so the channel is not purely
command-driven.

The HUB's `SHOWER_VALVE_STS` followed `GCS_SOLO_STS` by 0.4–0.6 s in five of six cases and
was absent once, so a HUB message is likely but not guaranteed after a GCS command.

## Readiness Signal

Do not tell the user to begin until all subscription acknowledgments have arrived. Track the message IDs returned by `subscribe()`:

```python
subscription_acks = set()

def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    subscription_acks.add(mid)
    if len(subscription_acks) == len(topics):
        print(json.dumps({
            "capture_active": True,
            "target_device_id": target_device_id,
            "listen_seconds": listen_seconds,
        }), flush=True)
```

All four subscriptions previously returned result `0` and granted QoS `[1]`.

## Message Capture

Preserve the raw payload and add a local receive timestamp. The six fractional digits in `received_at_utc` are the highest available capture precision and should be retained:

```python
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = msg.payload.decode("utf-8", errors="replace")

    record = {
        "message_number": len(messages) + 1,
        "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "topic": msg.topic,
        "payload": payload,
    }
    messages.append(record)
    print(json.dumps(record, sort_keys=True, default=str), flush=True)
```

Use a bounded wait for a normal capture:

```python
await asyncio.to_thread(threading.Event().wait, listen_seconds)
```

Recommended windows:

- `120` seconds for a quick app/controller test
- `180` seconds for a physical-controller test
- `300` seconds for a longer HUB or GCS capture

Disconnect both clients in `finally`:

```python
if mqtt_client is not None:
    mqtt_client.disconnect()
    mqtt_client.loop_stop()
await api_client.close()
```

## Device-Specific Message Codes

### GCS

Common codes:

- `GCS_SOLO_STS`: compact GCS status with valve hex values, system state, warmup status, and telemetry
- `GCS_WARM_STS`: warmup status
- `READ_GCS_EXPERIENCE_STS`: experience slots 1-5

GCS status often has `payload.data.attributes[0]` with fields such as `primaryValve1`, `secondaryValve1`, `currentSystemState`, and `warmUpStatus`.

#### Valve command word

`primaryValve1` (valve1) and `secondaryValve1` (valve2) carry a 4-byte command word in their first 8 characters:

```text
[prefix][temperature][flow][outlet mask]
```

The same layout is used for reads and writes, so `scripts.yaml`'s `anthem_valve_hex_convert` encoder and this script's decoder agree. Full byte-by-byte reference, mask tables, worked examples, and the verification evidence: [GCS valve hex reference](../gcs/valve_hex.md). Keep that document as the single source of truth — do not restate the tables here.

The GCS valve word leads the HUB's `SHOWER_VALVE_STS` by up to ~2 seconds. In the captured logs the HUB briefly reports pre-transition outlets, temperature, and flow before catching up, which is why the GCS word is the better source for outlet state.

### HUB

The HUB capture produced a different, richer schema:

- `SHOWER_VALVE_STS`: valve zone, ON/OFF status, temperature, flow rate, and outlet array
- `STEAM_STS`: steam status
- `MUSIC_STS`: amplifier status
- `LIGHT_STS`: light status, sometimes with an empty attributes list
- `FAVORITE_STS`: active favorite ID, name, and status

For HUB status, use:

```python
payload["deviceid"] == "gcs-sious0103D"
payload["sku"] == "HUB"
payload["data"]["code"]
```

For `SHOWER_VALVE_STS`, the useful fields are:

```python
for valve in payload["data"]["attributes"]:
    valve["zone"]
    valve["status"]
    valve["temperature"]
    valve["flowrate"]
    valve["outlets"]
```

The HUB HTTP `gcsadvancestate` response contains many null GCS fields and does not parse cleanly as the library's `DeviceState`. The MQTT `SHOWER_VALVE_STS` payload is the better event-driven source for HUB.

`SHOWER_VALVE_STS` is still captured and logged, but the bridge no longer turns it into entities — see [Disabled publishers](#disabled-publishers). The fields above remain accurate for reading captures.

## Filter and Summarize After Capture

Use this compact analysis to separate target-device messages and count codes:

```python
from collections import Counter

by_device = Counter()
by_code = Counter()
for message in capture["messages"]:
    payload = message.get("payload", {})
    by_device[payload.get("deviceid", "<missing>")] += 1
    by_code[payload.get("data", {}).get("code", "<missing>")] += 1
print(dict(by_device))
print(dict(by_code))
```

For local timestamps and inter-message timing:

```python
previous = None
for message in capture["messages"]:
    received = datetime.fromisoformat(message["received_at_utc"])
    local_time = received.astimezone()
    elapsed = None if previous is None else received - previous
    print(
        message["message_number"],
        local_time.strftime("%Y-%m-%d %H:%M:%S.%f %Z%z"),
        message.get("payload", {}).get("data", {}).get("code"),
        None if elapsed is None else round(elapsed.total_seconds() * 1000, 3),
    )
    previous = received
```

The source timestamp precision is microseconds. The payload's `timestamp` field is generally only whole seconds, so use `received_at_utc` for message-to-message latency.

## Important Interpretation Rules

- MQTT messages captured on `ExecuteControlCommand` were status/result messages, not the original HTTPS or app command.
- Do not publish arbitrary shower commands over MQTT. The confirmed write path remains the HTTPS `/platform/api/v1/commands/*` API.
- The MQTT client should acknowledge direct-method messages with the response topic if implementing a long-running client:

  ```text
  $iothub/methods/res/200/?$rid=N
  ```

- No MQTT message during an idle interval does not prove the device is offline. The channel is event-driven.
- Keep raw messages unchanged. Add a separate Markdown report for human interpretation.
- Never store access tokens, refresh tokens, SAS passwords, or full IoT Hub settings in the raw capture or Markdown report.

## Reference Documents

- [GCS valve hex reference](../gcs/valve_hex.md) — encode/decode of the valve
  command word: temperature, flow, outlet masks, preset byte order, and the
  `ValveMode` misreading to avoid.

## Existing Capture Artifacts

- ~~GCS MQTT report~~ `mqtt_capture_gcs-sio32343h7_20260806T181200Z.md`
- ~~GCS physical-controller raw capture~~ `mqtt_capture_physical_gcs-sio32343h7_20260806T202651.055917Z.json`
- ~~HUB raw capture~~ `mqtt_capture_hub_gcs-sious0103D_20260806T204431.714291Z.json`

  ⚠️ **These three 2026-08-06 files are no longer on disk** (checked 2026-08-20) — they went
  with the legacy trees removed in `1b77372`. They are also below the corpus floor, so they
  could not be used for analysis even if recovered. Named here only as the provenance of the
  findings above.

## Standalone Capture Script

`mqtt_capture.py` performs authentication, mobile-device registration, MQTT
subscription, local Mosquitto forwarding, and clean disconnect without
importing the Home Assistant integration. It reads the Kohler and MQTT config
entries from `/homeassistant/.storage/core.config_entries`.

Run a continuous capture from the scripts directory:

```sh
cd /root/homeassistant/scripts/kohler_konnect_custom
python3 mqtt_capture.py --listen-seconds 0
```

Use a positive `--listen-seconds` value for a bounded capture. The Home
Assistant Kohler integration starts a continuous instance when its config
entry loads and sends it `SIGTERM` when the entry unloads. Use one
`--device-id` per capture; the account-level direct-method subscription can
deliver status messages for both GCS and HUB devices.

## Home Assistant MQTT Bridge Topics

The capture script also reads the Home Assistant MQTT config entry and
publishes normalized state to the local broker. The bridge availability topic
is `kohler/bridge/availability`. Use `--no-local-mqtt` to disable this bridge
when running an isolated capture.

Live publishers, as of 2026-08-11:

| Source | Publishes |
|---|---|
| GCS `GCS_SOLO_STS` | valve hex, outlets 1-6, temperature, flow, last update |
| HUB `MUSIC_STS` | amplifier binary sensor |
| Bridge itself | availability, Kohler link, last message, started |

### Disabled publishers

Two publishers are commented out rather than deleted. Each is wrapped in
`===== ... DISABLED - START/END =====` markers in `mqtt_capture.py`; strip the
leading `# ` between a marker pair to restore it.

- **HUB `SHOWER_VALVE_STS`** — `publish_hub_valve_state()`, the
  `outlet_group()`/`outlet_state()` helpers, and the call in
  `publish_local_record()`. This covered `kohler/<device_id>/valve/<zone>/*`
  and `kohler/<device_id>/outlet/<n>/state` plus their discovery configs. The
  GCS decoder supersedes it and does not lag. HUB `MUSIC_STS` is unaffected.
- **Raw MQTT mirror** — `kohler/raw/<device_id>/<message_code>`. This was
  published unretained, so no broker state was left behind.

The per-run JSONL capture log is also off by default
(`ENABLE_TEMPORARY_RAW_MQTT_LOGGING = False`), but it is switched rather than
commented out: pass `--raw-log` to record a single run without editing the
script. Existing logs under `log/` are untouched and remain the evidence base
for the decode in [`gcs/valve_hex.md`](../gcs/valve_hex.md).

### Retained-payload cleanup

`publish_legacy_cleanup()` runs once after the local broker connects and
publishes an empty retained payload to every discovery and state topic the
bridge no longer maintains: the HUB valve and outlet entities above, and the
renamed GCS entities (`primary_valve1_hex`, `primary_valve2_hex`,
`message_received`). An empty retained discovery payload removes the entity
from Home Assistant; an empty retained state payload stops the broker
replaying a value nothing refreshes.

That GCS cleanup previously ran on every message; it is now startup-only.
Delete `publish_legacy_cleanup()` and its call once every broker has been
cleaned.

### Bridge health

The bridge publishes its own retained topics and discovers them under a
separate `Kohler MQTT Bridge` device:

```text
kohler/bridge/availability     online | offline   (last-will backed)
kohler/bridge/kohler_link      ON | OFF
kohler/bridge/last_message     ISO-8601 receipt time of the last envelope
kohler/bridge/started          ISO-8601 time the bridge announced itself
```

These are two different facts and both matter:

- `binary_sensor.kohler_bridge_connected` tracks **this process and its local
  broker connection**. It goes off via the last will if the process dies or the
  Mosquitto socket drops, and is retracted explicitly on clean shutdown,
  because a graceful disconnect suppresses the last will.
- `binary_sensor.kohler_cloud_connected` tracks the **Kohler IoT Hub TLS
  connection** on port 8883. This can go off while the bridge stays connected,
  which is the state where every Kohler entity silently holds stale retained
  values. Alert on this one.

`sensor.kohler_bridge_last_message` and `sensor.kohler_bridge_started` are
diagnostic timestamps. A quiet `last_message` does not by itself mean a
problem: the Kohler channel is event-driven and can be idle for hours.

For GCS `GCS_SOLO_STS` messages it publishes one retained JSON document:

```text
kohler/gcs-sio32343h7/gcs_solo_sts/state
```

Every GCS entity reads that topic through a `value_template`. Alongside the
existing `valve1_code`/`valve2_code`/`received_time_precise` fields, the
document now carries the decoded valve word: `outlet1`-`outlet6` (`ON`/`OFF`),
`valve1_temperature`/`valve2_temperature`, `valve1_flow`/`valve2_flow`,
`valve1_outlet_mask`/`valve2_outlet_mask`, and `valve1_paused`/`valve2_paused`.

The discovered entities are `binary_sensor.anthem_outlet_1` through
`binary_sensor.anthem_outlet_6`, `sensor.anthem_valve1_temperature`,
`sensor.anthem_valve2_temperature`, `sensor.anthem_valve1_flow`,
`sensor.anthem_valve2_flow`, and `sensor.anthem_gcs_last_update`, all on the
GCS device.

`sensor.anthem_gcs_last_update` is a `timestamp` sensor fed from the payload's
`received_at_iso`. Use it — not an entity's `last_changed` — for "when did this
last update" displays. `last_changed` and `last_updated` are stamped by Home
Assistant when it writes the state, so a restart resets them to the restart
time and no integration can backdate them. A timestamp carried in a retained
payload replays from the broker and comes back correct. The older HUB-sourced
outlet binary sensors under `kohler/gcs-sious0103D/outlet/<n>/state` are still
published unchanged so both sets can be compared before the HUB ones are
retired. `valve1_paused` and `valve2_paused` have no entity; read them from the
state topic if an automation needs to tell PAUSE from STOP.
