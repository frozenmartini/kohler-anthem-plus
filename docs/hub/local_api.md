# Kohler Anthem Plus — **LOCAL** Hub Web API Reference

> The **on-device** REST API served directly by the hub on the LAN. This is a
> *different* surface from the cloud Konnect API in `HUB_API_REFERENCE.md`
> (`/platform/api/v1/commands/...`, OAuth). No cloud, no internet required.
>
> Reverse-engineered from the hub's Angular web UI bundle (`main.*.js`) and
> live-probed against a real hub. Unofficial; may change with firmware.

- **Host:** `http://<HUB_IP>` (a.k.a. `http://kohler-myshower.local`) — plain HTTP, no TLS
- **API base:** `http://<hub>/web/api/v1/device/`
- **Server:** `Werkzeug/2.1.2 Python/3.8.3` (Flask dev server on the hub)
- **Web UI:** Angular SPA "Anthem+", static assets under `/web/*`
- **Probed hub firmware:** `2.88` (UI 3.23 / touch 5.7, amplifier 2.2, valve fw 10)

> **Firmware caveat.** The `nclpl/anthem_shower` HA integration was tested on
> **fw 2.72**. This hub runs **2.88**, and behaviour differs — notably water
> control and lighting (see §4, §5). Treat 2.72-era payloads as unverified here.

Unknown paths fall through to `index.html` (SPA catch-all), so a 200 returning
HTML means "not a real route" (e.g. `get_command` does this).

> ## ⚠️ Scope: this API is SETUP/CONFIG, not CONTROL
>
> **The `:80` local REST API cannot turn anything on or off.** It is a
> **setup / configuration / diagnostics** surface. Confirmed on fw 2.88 (field-verified):
>
> - **No live actuation.** You cannot start/stop the valve, lights, steam, or
>   music through it. `water_test_start` runs a **fixed plumbing self-test**
>   (zone1 / outlet 1, ~5 s, no parameters honoured) — it is *not* usable shower
>   control. `update_*_settings` writes **presets/config**, not live state.
> - **Favourites & experiences are launched CLOUD-SIDE.** The local
>   `add_experience` / `update_experiences` / `trigger_load_exp_click` commands
>   edit the *list/config*; the actual "run this scene now" trigger goes through
>   the **cloud Konnect API**, not this local API.
> - **Where real control lives:** (1) the **cloud** Konnect API
>   (`HUB_API_REFERENCE.md`, `/platform/api/v1/commands/...`), or (2) **Control4's
>   local certificate-authenticated channel** (see §7). Both bypass the plain
>   `:80` API for actuation.
>
> Treat everything below as "read state / write config / run setup routines /
> pair devices," **not** "control the shower."

---

## 1. Request conventions

Every request carries:

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `random_uuid` | a fresh `str(uuid.uuid4())` per request |
| `Authorization` | `Bearer <JWT>` (all endpoints except the pre-auth allow-list below) |

**Auth is enforced server-side.** Without a valid token every endpoint returns:

```json
HTTP 403  {"error":"Unauthorised token","message":"The request contains invalid token.","name":"Forbidden","status":"false"}
```

**Pre-auth allow-list** (interceptor lets these through with no token):
`get_hub_running_state`, `get_hub_version_info`, `hub_date_config_state`,
`set_hub_datetime`. Note `set_hub_datetime` / `hub_date_config_state` are
*mutating* yet reachable unauthenticated.

---

## 2. Authentication — PIN → JWT

**Endpoint:** `POST /web/api/v1/device/request_user_login`
**Body:** `{"req_command":"login","pin":"<enc>"}`
**Response:** `{"token":"<JWT>"}`  → store as `currentUser`; JWT payload is
`{"type":"response","exp":<unix>}` and is **short-lived** (~minutes). Re-login when it expires.

**PIN encryption** (mirrors the web UI's `forge` code exactly):

```
enc = base64( RSA_PKCS1v15_encrypt( public_key, sha256(pin).hexdigest_ascii ) )
```

i.e. SHA-256 the PIN, take its **64-char lowercase hex string as ASCII bytes**,
RSA-encrypt those bytes with **RSAES-PKCS1-v1_5**, base64 the ciphertext.

**Hardcoded public key** (baked into the JS bundle, 1024-bit, PKCS#1):

```
-----BEGIN RSA PUBLIC KEY-----
MIGJAoGBAOBnPtJlU6y62vyrcHgqZPAlr+FM10BpUxBvRx5u0fXNEjXcda4y3WSU
2ECzf9HcmDU5r6fD2jiFPyTuXu7jY2qzAI7QME6eoaJd2q+QLKpcUVq5MTeFo9b6
zpZlGHUiiy0NrFdKPjD+UdPXi/t1oEKaj/loWiZ7p0P02paUoI41AgMBAAE=
-----END RSA PUBLIC KEY-----
```

### Working login (pure stdlib, no deps)

```python
import hashlib, base64, json, uuid, urllib.request, os

PEM_B64 = ("MIGJAoGBAOBnPtJlU6y62vyrcHgqZPAlr+FM10BpUxBvRx5u0fXNEjXcda4y3WSU"
           "2ECzf9HcmDU5r6fD2jiFPyTuXu7jY2qzAI7QME6eoaJd2q+QLKpcUVq5MTeFo9b6"
           "zpZlGHUiiy0NrFdKPjD+UdPXi/t1oEKaj/loWiZ7p0P02paUoI41AgMBAAE=")

def _parse_pkcs1(der):
    def rl(b, i):
        l = b[i]; i += 1
        if l & 0x80:
            k = l & 0x7f; l = int.from_bytes(b[i:i+k], "big"); i += k
        return l, i
    _, i = rl(der, 1)                    # SEQUENCE
    i += 1; ln, i = rl(der, i); n = int.from_bytes(der[i:i+ln], "big"); i += ln
    i += 1; le, i = rl(der, i); e = int.from_bytes(der[i:i+le], "big")
    return n, e

N, E = _parse_pkcs1(base64.b64decode(PEM_B64))
K = (N.bit_length() + 7) // 8            # 128

def _rsa_pkcs1v15(msg: bytes) -> bytes:
    ps = b""
    while len(ps) < K - 3 - len(msg):
        b = os.urandom(1)
        if b != b"\x00": ps += b
    m = int.from_bytes(b"\x00\x02" + ps + b"\x00" + msg, "big")
    return pow(m, E, N).to_bytes(K, "big")

def login(host: str, pin: str) -> str:
    digest_hex = hashlib.sha256(pin.encode()).hexdigest()
    enc = base64.b64encode(_rsa_pkcs1v15(digest_hex.encode())).decode()
    body = json.dumps({"req_command": "login", "pin": enc}).encode()
    req = urllib.request.Request(
        f"http://{host}/web/api/v1/device/request_user_login",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "random_uuid": str(uuid.uuid4())})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())["token"]

def call(host, token, path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"http://{host}/web/api/v1/device/{path}", data=data, method=method,
        headers={"Content-Type": "application/json",
                 "random_uuid": str(uuid.uuid4()),
                 "Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

# t = login("<HUB_IP>", "<HUB_PIN>")
# print(call("<HUB_IP>", t, "get_hub_running_state"))
```

Related PIN commands: `POST change_user_pin` `{req_command:"change_user_pin",originalpsk,changedpsk}`
(both PINs same-encrypted), `POST generate_pin`.

---

## 3. The control endpoint: `req_update_command`

**Almost every action posts to one endpoint** and is discriminated by the
`req_command` field in the body:

```
POST /web/api/v1/device/req_update_command
Body: {"req_command":"<action>", ...action-specific fields}
```

(A handful of actions have their own routes: `request_user_login`,
`change_user_pin`, `generate_pin`, `set_hub_datetime`, `factory_reset`,
`rmt_btn_start_pairing`, `update_showroom_settings`, `update_load_exp_click`,
`ack_update_error`, `hub_date_config_state`. All others funnel through
`req_update_command`.)

> The interceptor also fires a `get_hub_running_state` check before **every**
> POST, so commands may be gated on the hub actually being reachable/idle.

---

## 4. WATER / VALVE — setup & self-test only (NOT control)

> **This section does not control the shower.** (See the Scope callout up top.)
> The local API has **no live valve control** on fw 2.88 — no command here turns
> water on at a chosen outlet/temperature. Real "run the shower" happens
> **cloud-side** (Konnect) or via **Control4** (§7). What's below is a fixed
> plumbing self-test, outlet identification, and calibration.

> **fw 2.88 behaviour (field-verified).** `water_test_start` runs a **fixed**
> self-test — **zone1, outlet 1, ~5 seconds only** — and ignores any
> temperature/flow/outlet fields in the body. It's a plumbing check, not control.

| Command | Body | Effect |
|---|---|---|
| `water_test_start` | `{"req_command":"water_test_start","data":{"state":"start"}}` | **fw 2.88:** fixed zone1/outlet1 ~5 s self-test (no config honoured) |
| `water_test_stop` | `{"req_command":"water_test_stop","data":{"state":"stop"}}` | Stop the self-test |
| `find_outlet` | `{"req_command":"find_outlet","data":{"zone":"<zoneN>","outlet":"<outletN>"}}` | Pulse one physical outlet to identify it (`zone`/`outlet` are numeric suffixes, e.g. `"1"`) |
| `valve_calibration_start` | `{"req_command":"valve_calibration_start", ...}` | Begin valve flow-rate calibration |
| `valve_calibration_stop` | `{"req_command":"valve_calibration_stop", ...}` | End calibration |
| `valve_settings_calibration` | `{"req_command":"valve_settings_calibration", ...}` | Apply calibration values |

**Does NOT work on 2.88 (kept only as a negative result).** The
`nclpl/anthem_shower` (fw 2.72) integration documents a per-outlet payload for
`water_test_start`; on 2.88 the extra fields are ignored (fixed self-test runs
regardless):

```json
{"req_command":"water_test_start",
 "zone1":{"temperature":38.0,"flowRate":100,"outletState":[1,0,0,0,0,0]}}
```

(The per-outlet temperature/flow/outlet-mask still *exists* as data — it lives
**inside favourite/experience objects**, keyed `water.zone1{temperature,flowRate,
outlets,outletState}` / `zone2` — but running those is cloud-side, below.)

### Favourites & experiences are launched CLOUD-SIDE

The local commands below only **edit the list/config** of favourites/experiences.
They do **not** start a scene running — the actual "run now" trigger goes through
the **cloud Konnect API** (`HUB_API_REFERENCE.md`). `trigger_load_exp_click` is a
LumiWave UI helper (arms/loads an exp for display), not a shower-start.

| Command | Body | Notes (config only) |
|---|---|---|
| `add_experience` | `{"req_command":"add_experience","id":<id>}` | Add experience to the active set |
| `remove_experience` | `{"req_command":"remove_experience","id":<id>}` | Remove experience |
| `update_experiences` | `{"req_command":"update_experiences","data":<obj>}` | Reorder/edit experiences |
| `update_favorite` | `{"req_command":"update_favorite", ...}` | Edit a favourite's stored state |
| `delete_favorite` | `{"req_command":"delete_favorite","id":<id>}` | Delete a favourite |
| `trigger_load_exp_click` | `{"req_command":"trigger_load_exp_click"}` | LumiWave: arm/load an exp for display (not a shower-start) |

Reference ids seen on this hub — favourites: `Soap Pause(1) Flush Cold(2)
Music Only(3) SD music(4) V1Z1O1(5) AllOff-omit(6)`; water experiences:
`Warm Up(17) Cool Down(18) Sleep Simple(19) Wake Up(20) Shine(21)`;
ice-shower: `Beginner Ice Shower(22) Advanced Ice Shower(23)`.

---

## 5. LIGHTING — pairing & control

> ## ❌ Pairing was live-tested 2026-08-15 and it does not work — see [`lighting.md`](lighting.md)
>
> Everything in this section is accurate as an *endpoint* reference, but bypassing the
> §5.6 bug is **not** sufficient to pair a bulb. A Philips Hue Zigbee 3.0 bulb was never
> admitted by the coordinator across two controlled experiments, while the same bulb
> joined Zigbee2MQTT in 13 seconds with the hub's own scan window still open.
>
> Three corrections to §5.5's open unknowns, from reading the live JS bundle:
> the "accept the risk" prompt is **client-side only and makes no API call**, so it cannot
> flip the network to unsecured; **no `req_command` anywhere in the bundle changes Zigbee
> security mode**; and in unsecured mode the UI's intended payload is an **empty** `bulbs`
> list, which was tested and also failed.
>
> The local API exposes **no error surface** for the radio layer, and `get_error_log`
> times out at 170 s, so the cause cannot be determined from the hub. Full evidence,
> ruled-out hypotheses and next steps: [`lighting.md`](lighting.md).

Bulbs are **Zigbee**, joined to a coordinator on the **System Controller's
lighting card** (`get_lightcard_info` → `channel:11, status:"Connected"`; this is
*not* a separate "light bridge" — `connected_dev_info.lightbridge:false`).
Organised into three groups **A / B / C**, max **12 bulbs** total.

> **fw 2.88 note.** `update_lighting_settings` is **scene/preset config**, not
> live per-bulb control — it saves the default brightness/colour/dimming a group
> uses when a scene/experience runs. There is **no direct "bulb on/off/dim now"
> command** in this local API on 2.88; live lighting happens by triggering
> favourites/experiences (or from the touchscreen).

### 5.1 Supported bulbs (the real blocker)

Kohler lists **Sengled** Zigbee bulbs as supported — the **Sengled Element /
"ZigBee HA"** series (model numbers starting with `E`, e.g. `E11-*`, `E12-*`,
`E1x-*`). These are Zigbee HA 1.2 / Zigbee 3.0 bulbs that **join with the default
Trust Center link key — no per-bulb install code**.

- **Sengled has wound down as a company, but the bulbs are still sold** (Home
  Depot, Amazon, secondary market). A defunct manufacturer doesn't brick already-
  made Zigbee bulbs — they still join fine. Sourcing a genuine Sengled Element
  bulb is the most reliable path.
- **The web UI contains NO brand/manufacturer/model whitelist** (grepped the
  whole bundle — 0 references to `sengled`/`manufacturercode`/`modelid`). The only
  gate in the browser is the QR `$I` check (below). Any brand-locking, if it
  exists at all, lives in the **coordinator firmware**, not the web app — so
  another default-link-key Zigbee HA/3.0 bulb *might* pair, but that's untested.

### 5.2 Pairing state machine (from the bundle)

The "add light" screen is **QR-driven**. You upload one image per bulb; the app
decodes it **client-side** (`ngx-scanner-qrcode` → `result[0].value`) and buckets
each decoded string:

- value **contains `$I`** → **secured** install-code bulb → `detectedBulbs[]`
- value **without `$I`** → **unsecured** (default link key) bulb → `unscuredBulbs[]`
  ← *this is the Sengled path*

The batch is **mutually exclusive**: queuing unsecured bulbs clears the secured
list (`unscuredBulbs.length>0 ⇒ detectedBulbs=[]`), and if the network's current
mode (`connected_dev_info.zigbeeconnection`) is `"unsecured"` the secured list is
also cleared. On the probed hub the mode is **`"secured"`**.

Then:

1. `POST req_update_command {"req_command":"zigbee_scan_init","bulbs":<detected|unscured>,"initcall":"true"}`
2. Poll `POST req_update_command {"req_command":"zigbee_scan_status","bulbs":<same>,"initcall":"false"}`
   → returns `{"devices":[ {deviceid, ...} ]}` (each gets `.selected=false`, `.group="A"`)
3. Optionally `identify_light_device` (below) to blink-confirm each found bulb
4. Commit: `POST req_update_command {"req_command":"save_light_settings","devices":<selected>,"groupAicon":<int|null>,"groupBicon":…,"groupCicon":…}`
5. `POST req_update_command {"req_command":"zigbee_scan_stop"}` to end scanning

### 5.3 `identify_light_device` — what it actually does

```json
{"req_command":"identify_light_device","deviceid":"<id>"}
```

- Takes a `deviceid` **from an already-scanned bulb** (`scannedData[i].deviceid`),
  and makes that bulb **blink** so you can tell which physical fixture it is.
- Returns `{"status":"error"}` if the bulb doesn't respond → UI offers retry/reload.
- **It cannot discover bulbs.** It only pings something `zigbee_scan_status`
  already returned. So it will *not* help find a bulb that never joined — if
  `zigbee_scan_status` yields `devices:[]`, there's no `deviceid` to identify.

### 5.4 Other light commands

| Command | Body | Effect |
|---|---|---|
| `update_light` | `{"req_command":"update_light","deviceid":"<id>","devicename":"<name>"}` | Rename a bulb |
| `delete_light` | `{"req_command":"delete_light","deviceid":"<id>"}` | Remove a bulb |
| `toggle_zigbee` | `{"req_command":"toggle_zigbee"}` | Enable/disable the Zigbee radio |
| `update_lighting_settings` | `data.{groupA,groupB,groupC}` each `{brightness 0–100, colour:"Neutral White", dimmingspeed:"Slow\|Medium\|Fast", icon}` | Save group scene presets (see note above) |

### 5.5 Why nothing pairs right now (live diagnosis, this hub)

- **Zigbee radio:** was `zigbeeEnabled:false` / `get_zigbee_status:"false"` at
  discovery; **user enabled it 2026-08-10** → now `zigbeeEnabled:true`,
  `get_zigbee_status:"true"`. (Toggle via `toggle_zigbee`.)
- `get_connected_light_count: {"devices":0}`, `connected_dev_info.pairedlights: []`
  → nothing joined yet; coordinator (lightcard) is present on channel 11.
- Network mode is `"secured"` — a Sengled (unsecured/default-link-key) bulb must
  go through the **unsecured** QR path (§5.2), i.e. its QR must decode to a value
  **without** `$I` — **but that path is bugged (§5.6)**.

**"Secured" cannot be spoofed.** Secured join is a Zigbee **install-code**
handshake: the QR carries a per-bulb factory secret the coordinator uses to derive
a unique encrypted link key with *that* bulb. Feeding a fake/foreign install code
makes the key derivation mismatch → join fails. Default-link-key bulbs (Sengled
Element, most generic Zigbee) have **no** install code, so they can only use the
unsecured path — there's nothing to present as "secure."
- **Open unknowns:** whether the coordinator firmware filters by manufacturer;
  whether an arbitrary non-`$I` QR is accepted or must encode the bulb's own
  EUI64/MAC; whether the "secured" network will admit an unsecured bulb without
  a mode switch. These need a live pairing experiment to answer.

### 5.6 fw 2.88 web-UI bug: unsecured bulbs are never sent to the hub

The scan loop (`executeApiSequentially`) is hardcoded to send the **secured**
list on *both* calls:

```js
for (let i = 0; i < 9; i++) {
  let r = { req_command: "zigbee_scan_status", bulbs: t.detectedBulbs, initcall: "false" };
  if (i === 0) r = { req_command: "zigbee_scan_init", bulbs: t.detectedBulbs, initcall: "true" };
  const p = await t.zigbeeService.scanLighting(r).toPromise();  // POST req_update_command
  t.scannedData = p.devices;
}
```

But the caller **clears `detectedBulbs` whenever unsecured bulbs are queued**:

```js
this.unscuredBulbs.length > 0 && (this.detectedBulbs = []);
this.executeApiSequentially();
```

`unscuredBulbs` (your uploaded unsecured QR values) is used only for on-screen
display — it is **never placed in the `bulbs` field of any request**. So on the
unsecured path the hub receives:

```json
POST req_update_command  {"req_command":"zigbee_scan_init","bulbs":[],"initcall":"true"}
POST req_update_command  {"req_command":"zigbee_scan_status","bulbs":[],"initcall":"false"}   // ×8
```

i.e. an **empty** scan. That explains the field symptom: you confirm "continue
adding unsecured", the scan runs, and `devices:[]` comes back every time — the
bulb you scanned was thrown away before the request. The loop is only 9 iterations
with no inter-poll delay, so the effective join window is short (~seconds).

**Work-around (bypass the UI):** drive the endpoint directly, putting the bulb's
identifier in `bulbs` yourself, with the Sengled bulb freshly reset into pairing
mode (power-toggle 10×, end ON):

```
POST /web/api/v1/device/req_update_command
{"req_command":"zigbee_scan_init","bulbs":["<decoded-QR-value-or-EUI64>"],"initcall":"true"}
then poll:
{"req_command":"zigbee_scan_status","bulbs":["<same>"],"initcall":"false"}   # watch .devices
```

Verify with `get_connected_light_count` / `connected_dev_info.pairedlights`.
(Enable Zigbee first if `zigbeeEnabled:false` — `toggle_zigbee`.) Whether the
coordinator admits it still depends on the firmware's manufacturer handling.

---

## 6. MUSIC / AMPLIFIER control

The hub's music surface is **amplifier config + SD-card library**, not
transport control. There is **no play/pause/next/track** command in the hub web
API — transport lives on the shower touchscreen / mobile app. What the hub
exposes:

| Command | Body | Effect |
|---|---|---|
| `update_amp_settings` | see below | Set source, per-channel volume / balance / bass / treble, speaker mode |
| `update_amp_setup` | same shape as above | Same payload, used during first-time amp setup |
| `update_radio` | `{"req_command":"update_radio"}` | Turn the amplifier's Bluetooth/radio ON (no payload; UI reloads after) |
| `re_scan_sdcard` | `{"req_command":"re_scan_sdcard"}` | Rescan the SD card for songs |
| `index_sdcard` | `{"req_command":"index_sdcard"}` | Re-index the SD music library |
| `re_scan` | `{"req_command":"re_scan"}` | Generic device rescan |

**`update_amp_settings` payload:**

```json
{"req_command":"update_amp_settings",
 "data":{
   "musicSource":"sdcard",          // "sdcard" | "radio"
   "name":"Kohler Amplifier",
   "pin":"0000",                     // amplifier's own pairing PIN
   "stereo":{"active":false,"volume":50,"balance":0,"bass":0,"treble":0},
   "mono":{"active":true,"volume":50,"bass":0,"treble":0}
 }}
```

- `musicSource`: `"sdcard" | "radio"`
- `volume` / `bass` / `treble` / `balance`: integer levels (UI sliders)
- `stereo.active` / `mono.active`: which speaker mode is engaged
- SD library state is read via `get_sdcard_state` → `{sdcardfound,songs}`.
- These are **amp configuration only** — no local play/pause/on-off. Audio is
  actually started by running a "Music Only(3)" / "SD music(4)" **favourite**,
  which is a **cloud-side** trigger (§4), not a local command.

---

## 7. HOME CONTROLLER (Control4) integration

The web UI's only Control4 knob is an enable toggle + system selector; the
dropdown offers **Control4** (the bundle also contains `RTI` / `eLan` strings, but
only `[{value:"Control4",text:"Control4"}]` is wired in).

| Command | Body | Effect |
|---|---|---|
| `save_home_automation` | `{"req_command":"save_home_automation","state":<bool>,"system":"Control4"}` | Enable/disable the integration + select the system (config flag only) |

Read-back: `GET get_home_automation_info` → `{"connected":<bool>,"state":<bool>,"system":"Control4"}`
(`connected` = a Control4 controller is currently talking to the hub). The hub
also stores a full record, exposed **read-only** in `gcs_system_profile` →
`homeautomation.control4.{controller_name, controller_ip, controller_mac,
driver_version, director_ip, director_version, common_name}`. The web UI never
*writes* these — the Control4 side registers them over its own channel (below).

### 7.1 Control4 does NOT use the `:80` REST API

Correction to an earlier assumption: the `:80` PIN/JWT REST API is **setup/config
only** (see Scope callout) and **cannot actuate** the shower — so Control4 cannot
be "just a REST client" of it. Control4 provides **local, real-time control**,
which this API can't do. That control travels over a **separate, certificate-
authenticated channel**, not `/web/api/v1/device/*`.

### 7.2 Hub service/port map (live-probed 2026-08-10)

| Port | Proto | Observed | Role |
|---|---|---|---|
| **80** | HTTP (Werkzeug/Flask) | web UI + `/web/api/v1/device/*` | setup/config/diagnostics API (this doc) |
| **443** | HTTPS (Werkzeug/Flask) | 404 on `/` and on the device-API path | a **different** Flask app (separate routes; provisioning/cloud-facing?) |
| **8080** | HTTPS | **500 on every path** without the right handshake | cert-gated **machine-to-machine** endpoint — prime suspect for the Control4 channel |
| 9000 | HTTP (localhost) | `http://127.0.0.1:9000/` | internal backend the `:80` app proxies to; not remotely reachable |

Both `:443` and `:8080` present a **Kohler-issued device cert**:
`CN=gcs-sious0103D`, issuer **"Kohler Company Issuing CA"** (`O=Kohler Co.`,
`ST=Wisconsin`), valid 2025→2035. That's Kohler's own PKI — the same infrastructure
that would issue a **client** cert to a Control4 controller for mutual TLS. The
uniform 500 on `:8080` regardless of path is consistent with a service that
rejects anything lacking the expected client cert / protocol.

### 7.3 Control4 driver = Lua (`.c4z`)

Control4 drivers are **Lua**, packaged as a **`.c4z`** file (a ZIP of `driver.xml`
+ Lua modules). The controller runs a Linux-based OS; a runtime called **Director**
loads drivers. The on-wire protocol to the hub is whatever the driver implements —
here, TLS to the hub (the `:8080`/`:443` cert channel), *not* the `:80` API.

### 7.4 Can Control4's commands be sifted / replicated without Control4?

- **By probing alone: no.** The integration channel is mutual-TLS behind Kohler
  PKI, and with no Control4 controller attached there is **no live traffic** to
  capture. Probing tops out at "a cert-locked M2M service exists here."
- **Authoritative route: read the `.c4z` driver.** Obtain the Kohler Anthem Plus
  Control4 driver (Control4 driver DB / third-party mirrors / extracted from a
  Control4 OS image) and read its Lua — it reveals the exact host, port, auth
  (client cert and/or PIN), endpoints, and command formats.
- **Replicating local control without Control4** would then require speaking that
  cert-authenticated protocol (and likely holding a Kohler-issued client cert) —
  materially harder than the `:80` API. The alternative for real control remains
  the **cloud Konnect API** (`HUB_API_REFERENCE.md`).

**Open items:** confirm `:8080` is the Control4 ingress (vs cloud/app); determine
whether it requires a client cert (mutual TLS) or just the device server cert;
obtain and decompile the `.c4z` to enumerate the actual command set.

---

## 8. Full command inventory (req_command values)

All `req_command` strings found in the bundle, grouped. **Bold = state-changing.**
Reads/settings-config omitted per focus, but listed for completeness.

- **Water/valve:** `water_test_start`, `water_test_stop`, `find_outlet`,
  `valve_calibration_start`, `valve_calibration_stop`, `valve_settings_calibration`,
  `update_valve`, `update_valve_settings`
- **Experiences/favourites:** `trigger_load_exp_click`, `add_experience`,
  `remove_experience`, `update_experiences`, `update_favorite`, `delete_favorite`,
  `remove_experience`
- **Lighting:** `update_lighting_settings`, `update_light`, `save_light_settings`,
  `identify_light_device`, `delete_light`
- **Music/amp:** `update_amp_settings`, `update_amp_setup`, `update_radio`,
  `re_scan_sdcard`, `index_sdcard`, `re_scan`
- **Home automation:** `save_home_automation`
- **LumiWave/steam:** `update_lumiwave_settings`, `update_steam_settings`,
  `steam_power_clean`, `trigger_load_exp_click`
- **Remote button:** `update_rmt_btn_action`, `remote_btn_start_pairing`,
  `remote_btn_stop_pairing`, `unpair_remote_button`
- **Zigbee:** `zigbee_scan_init`, `zigbee_scan_status`, `zigbee_scan_stop`,
  `toggle_zigbee`, `ble_on`
- **Device mgmt:** `remove_device`, `reset_device`, `identify_light_device`
- **Network/hub:** `wifi_profile_details` (`data:{ssid,psk}`), `dns_name_change`,
  `extend_ap_mode`, `increase_setup_timeout`, `date_time_set`, `hub_date_config_state`,
  `hub_config_init`, `update_hub_settings`, `user_selected_config`
- **Firmware:** `install_update_request`, `autoupdate_time`, `update_auto_toggle`,
  `acknowledge_updateerror`
- **Logging/diag:** `get_error_log`, `clear_error_log`, `user_selected_logging`
- **Showroom/hospitality:** `update_showroom_settings`, `update_hospitality_settings`
- **Auth/setup:** `login`, `change_user_pin`, `user_pin_generate`, `generate_pin`
- **Danger:** `factory_reset`

---

## 9. Security notes

- Plain **HTTP only** — no TLS; tokens, PINs (encrypted) and data cross the LAN in clear.
- The RSA public key is **static and shipped in the JS**, so the PIN scheme
  stops passive plaintext-PIN replay but not an attacker who can read the bundle
  and capture one login. JWT is short-lived, which limits token replay.
- `set_hub_datetime` / `hub_date_config_state` are reachable **without auth**.
- Runs on a **Flask dev server** (`Werkzeug/2.1.2`, Python 3.8.3).
- Data behind the token includes MACs (`<MAC_1>`, `<MAC_2>`),
  serials, SSID, neighbouring-WiFi scan, and the amplifier PIN (`0000`).

---

*Live-probed 2026-08-10 against hub fw 2.88. Only read/`GET` endpoints were
exercised during discovery; no control command in §4–§7 was fired.*
