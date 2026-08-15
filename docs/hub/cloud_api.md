# Kohler Konnect — Anthem Plus **HUB** REST API Reference

Reverse-engineered from the Konnect Android app **3.0.1** (`com.kohler.hermoth`) and
**live-verified** against a real Hub (`gcs-sious0103D`, "Anthem Plus") on 2026-08-10.

Target use: **Home Assistant** via `rest_command` / `shell_command` (curl).

> SKU note: the Hub is a Linux **system controller** ("Anthem+") that drives the valves,
> steam, amplifier (music) and lights. It is a **different product from GCS** (the Wi‑Fi
> digital valve). GCS uses `/commands/gcs/*` with raw valve hex; the Hub uses
> `/commands/hub/*` and is controlled almost entirely through **favourites**.

---

## 1. Connection basics

- **Base URL:** `https://api-kohler-us.kohler.io`
- **SKU string:** `HUB` (always)
- **Required headers on every call:**
  ```
  Authorization: Bearer <ACCESS_TOKEN>
  Ocp-Apim-Subscription-Key: 429ecb1d0b5e4258aa0a2bfadd82a493
  Content-Type: application/json
  Accept: application/json
  ```
  - `Ocp-Apim-Subscription-Key` is an **app-global, non-secret** APIM key (stable; verified identical across sessions).
  - **`api-kohler-us.kohler.io` does NOT require mTLS** (the APIM mTLS cert is only for the alternate `*.kohlerkonnect-apim.azure-api.net` gateway, which we don't use).

### 1.1 Auth — getting `ACCESS_TOKEN`

`/commands/*` writes are only accepted for tokens issued by the **`B2C_1A_signin`** Azure AD B2C
policy. (ROPC tokens = HTTP 403 on writes; reads accept either.)

- **Client ID:** `8caf9530-1d13-48e6-867c-0f082878debc`
- **Authority:** `https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin`
- **Scope:** `openid offline_access https://konnectkohler.onmicrosoft.com/f5d87f3d-bdeb-4933-ab70-ef56cc343744/apiaccess`
- **Redirect URI (registered):** `msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D`

One-time interactive sign-in (browser OAuth **authorization-code + PKCE**) yields a
`refresh_token`. Thereafter, mint short-lived access tokens with the refresh grant:

```bash
curl -s -X POST \
  "https://konnectkohler.b2clogin.com/tfp/konnectkohler.onmicrosoft.com/B2C_1A_signin/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "client_id=8caf9530-1d13-48e6-867c-0f082878debc" \
  --data-urlencode "grant_type=refresh_token" \
  --data-urlencode "refresh_token=$KOHLER_B2C_REFRESH_TOKEN" \
  --data-urlencode "scope=openid offline_access https://konnectkohler.onmicrosoft.com/f5d87f3d-bdeb-4933-ab70-ef56cc343744/apiaccess"
# -> JSON with access_token (expires_in ~3600s) and a ROTATED refresh_token (persist it!)
```

> The refresh token **rotates** on every refresh — save the new one each time.
> B2C refresh tokens last up to ~90 days; when it finally expires you must re-run the
> interactive sign-in. The helper `kohler_hub_music.py authurl|exchange` performs the
> one-time browser flow and stores tokens in `D:\kohler-work\state\token.json`.

### 1.2 IDs you need

- **`tenantId`** (a.k.a. customerId) = the `oid` claim of the access-token JWT.
  Example here: `<TENANT_ID>`.
- **`deviceId`** = the Hub's device id (SKU `HUB`), from the customer-device read.
  Example here: `gcs-sious0103D`.

---

## 2. Endpoint map

Legend: **[LIVE]** = exercised live this session; **[STATIC]** = derived from the decompile
(interface + models), not yet exercised live.

### 2.1 Reads — `GET`  (host + `…`)

| Purpose | Path (`{}` = substitute) | Notes |
|---|---|---|
| Customer + devices | `/devices/api/v1/device-management/customer-device/{tenantId}` | **[LIVE]** homes[].devices[] with `sku`,`deviceId`,`logicalName` |
| **Hub live state** | `/devices/api/v1/device-management/hub-state/{deviceId}` | **[LIVE]** see §5.1 |
| **Hub favourites** | `/devices/api/v1/device-management/hub-experience/{deviceId}/favorites` | **[LIVE]** see §5.2 |
| Hub experiences | `/devices/api/v1/device-management/hub-experience/{deviceId}/experiences` | [STATIC] `ExperienceModel` |
| **Hub configuration** | `/devices/api/v1/device-management/hub-configuration/{deviceId}` | **[LIVE]** zones/outlets/parts, see §5.3 (also `…/{version}/…`) |
| Hub diagnostics | `/devices/api/{version}/device-management/hub-diagnostics/{deviceId}` | [STATIC] |
| Hub diagnostics (active errors) | `/devices/api/v1/device-management/hub-diagnostics/{deviceId}/active` | [STATIC] |
| Hub water usage | `/devices/api/{version}/device-management/hub-usage/{deviceId}` | [STATIC] `AnthemHubWaterUsageModel` |
| Hub firmware version | `/platform/api/v1/firmware/hub/{deviceId}?releasetarget=Public` | [STATIC] |

### 2.2 Commands — `/platform/api/v1/commands/hub/…`

| Purpose | Method + Path | Body model (§3) | Verified |
|---|---|---|---|
| **Simple start** (default shower on/off) | `POST …/valvecontrol` | `ValveControl` (`valveOnOff`) | [STATIC] |
| **Default steam** on/off | `POST …/steamcontrol` | `ValveControl` (`steamOnOff`) | [STATIC] |
| **Favourite start/stop** | `POST …/favorite/control` | `FavouriteControl` | **[LIVE] 200** |
| **Create favourite** | `POST …/favorite` | `Favourite` (no `id`) | **[LIVE] 201** |
| **Edit favourite** | `PATCH …/favorite` | `Favourite` (with `id`) | **[LIVE] 200** (⚠ 902 if running) |
| **Delete favourite** | `DELETE …/favorite` | `RemoveFavourite` | **[LIVE] 202** |
| **Stop all** (full idle) | `POST …/stopall` | `StopAll` | **[LIVE] 201** |
| Shower experience start/stop | `POST …/shower/experience/control` | `Experience` | [STATIC] |
| Steam experience start/stop | `POST …/steam/experience/control` | `Experience` | [STATIC] |
| Ice-bath/ice-shower experience | `POST …/iceshower/experience/control` | `Experience` | [STATIC] |
| Factory reset ⚠ | `POST …/factoryreset` | `FaucetFactoryReset` | [STATIC] — destructive |
| Firmware update | `POST /platform/api/v1/firmware/hub/{deviceId}` | — | [STATIC] |

---

## 3. Request bodies + value options

All bodies are JSON. `sku` is always `"HUB"`.

### 3.1 `ValveControl` — simple shower / steam on-off
`POST …/valvecontrol` (uses `valveOnOff`) and `POST …/steamcontrol` (uses `steamOnOff`).
Model: `AnthemHubValveControlRequestModel`. **No temperature/flow/outlet** — the Hub runs
its own stored **default** zone config.

```json
{ "deviceId": "gcs-sious0103D", "sku": "HUB", "tenantId": "<oid>", "valveOnOff": "ON" }
```
```json
{ "deviceId": "gcs-sious0103D", "sku": "HUB", "tenantId": "<oid>", "steamOnOff": "ON" }
```
- `valveOnOff` / `steamOnOff`: **`"ON"` | `"OFF"`** (Gson omits the other/null field).

### 3.2 `FavouriteControl` — start/stop a favourite  **[LIVE]**
`POST …/favorite/control`. Model: `AnthemHubFavouriteRequestModel`.
```json
{ "deviceId":"gcs-sious0103D", "tenantId":"<oid>", "sku":"HUB",
  "id":"3", "name":"Music Only", "state":"ON" }
```
- `id`: favourite id **as string**; `name`: favourite title; `state`: **`"ON"` | `"OFF"`**.
- Response `200` `{correlationId, timestamp}`.

### 3.3 `Favourite` — create (`POST`) / edit (`PATCH`) a favourite  **[LIVE]**
Model: `AnthemHubUpdateFavoriteRequestModel`. A favourite bundles **independent** components:
`water`, `steam`, `music`, `light`. **Omit `id` to create; include `id` to edit.**

```json
{
  "deviceId": "gcs-sious0103D",
  "tenantId": "<oid>",
  "sku": "HUB",
  "id": 3,                       // EDIT only (integer). OMIT for create.
  "name": "My Favourite",
  "water": {
    "zone1": { "temperature": 104, "flowrate": 100, "outlets": [0] },
    "zone2": null
  },
  "steam": { "temperature": 0, "time": 0 },
  "music": { "source": "Aux", "songID": "", "musicRepeat": "", "volume": 70 },
  "light": []
}
```

**Component value options:**

- **water** = `{ zone1, zone2 }`. Each zone = `AnthemHubZoneRequestModel`:
  - `temperature`: integer in the **account's unit** (this account = **Fahrenheit**, e.g. `104`).
    The app converts only if the unit is Celsius; for °F it's sent as-is. Device limits come
    from config (this Hub: default `102`, per-outlet min/max in `hub-configuration`).
  - `flowrate`: integer **0–100** (percent; config `flowcapacity=100`).
  - `outlets`: **array of 0-based outlet positions to OPEN** within that valve/zone:
    `[0]` = outlet1, `[1]` = outlet2, `[2]` = outlet3 (each valve has 3 outlets).
    `[]` = no water for that zone. `[0,1]` opens outlets 1 & 2.
  - **Unused zone:** set `zone2` to `null` (what the app sends) — or a zone with `outlets: []`.
    A favourite for a **NotConnected** valve is accepted (201) but **silently not persisted**.
- **steam** = `{ temperature, time }` integers. `{ "temperature":0, "time":0 }` = no steam.
- **music** = `AnthemHubAmplifierRequestModel` `{ source, songID, musicRepeat, volume }`:
  - `source`: **`"Aux"`** (line-in) | **`"SdCard"`** (SD card). (Stored/returned lower-cased:
    `"aux"`/`"sdcard"`.) **Kohler Playlist** is a streaming mode (flag `isKohlerPlaylist`);
    **there is NO Bluetooth audio source.**
  - `volume`: integer (observed 50, 70; `maxVolume` in config). `songID`/`musicRepeat`: `""` for Aux/SD.
  - **To include NO music: OMIT the `music` key entirely.** Sending an all-`null` music object
    (`{"source":null,...}`) makes the **whole request fail with HTTP 400**.
- **light** = array of `AnthemHubLightRequestModel` `{ name, color, hue, brightness }` (strings).
  `[]` = no light. **Like music, lighting is favourite-only (no dedicated light command).** Details
  (decompile-complete; NOT live-verified — this Hub has `light: NotConnected`):
  - `name` = light group/module — Hub exposes up to 3 (`hub-configuration.lightModuleType` = `light1`/`light2`/`light3`).
  - `color` = one of **11** (`hub_light_color` array): `warmwhite, neutralwhite, coolwhite, red, orange,
    yellow, green, lightblue, blue, purple, pink`. The 3 whites are color-temperature based (hue disabled).
  - `hue` = shade **step 1–5** within a color (each color has 5 hex steps `step1Hex…step5Hex`; `hueMax=5`).
  - `brightness` = level string (percentage/level — exact range unconfirmed).
  - **State:** `hub-state.state.light[]` = `{status:"ON"/"OFF", name, state:{colorInfo, brightness, colorTemperature}}`;
    MQTT `LIGHT_STS` (`MqttHubLightStatus`) carries the same `LightState{colorInfo, brightness, colorTemperature}`
    — light state **does** report color/brightness/temperature (unlike music = on/off only).
  - Read favourite `light` = `List<LightGroupModel>` (rich: `colorGroupList[]` of `ColorItem` w/ per-color hue range + 5 hex steps).

> **Outlet type sets the flow envelope on this device.** The controller computes each
> outlet's min/max flow from its **outlet type × the flow calibration figure** — multiple
> showerheads, multiple body sprays, and tub filler permit more than a single head. The GCS
> valve does none of this, so the two devices may hold different types for the same fixture
> on purpose. On firmware **2.88** the calculation is buggy and the recommended workaround is
> to disable flow control system-wide. See
> [`../architecture.md`](../architecture.md#outlet-types-mean-different-things-on-the-two-devices).

**Outlet position → physical outlet** is defined per install in `hub-configuration`
(`zoneone.outletone/outlettwo/outletthree` = **type codes**). On this device:
`zone1 = [62, 52, 1]`, `zone2 = [11, 38, 21]`. (Type codes resemble GCS: `1`=handshower,
`11`=showerhead, `21`=tub filler; others are install-specific.) **Always read config to map.**

### 3.4 `RemoveFavourite` — delete a favourite  **[LIVE]**
`DELETE …/favorite`. Model: `AnthemHubRemoveFavoriteRequestModel`.
```json
{ "deviceId":"gcs-sious0103D", "tenantId":"<oid>", "sku":"HUB", "name":"My Favourite", "id":5 }
```
- `id`: **integer**. Response `202`.

### 3.5 `StopAll` — full stop / idle  **[LIVE]**
`POST …/stopall`. Model: `AnthemHubStopAllRequestModel`.
```json
{ "deviceId":"gcs-sious0103D", "sku":"HUB", "tenantId":"<oid>" }
```
- Response `201`. **Fully idles** the system (see §4 vs an all-off favourite).

### 3.6 `Experience` — start/stop an experience  **[control STATIC; read + limits LIVE]**
`POST …/shower|steam|iceshower/experience/control`. Model: `AnthemHubExperienceRequestModel`.
```json
{ "deviceId":"gcs-sious0103D", "sku":"HUB", "tenantId":"<oid>", "name":"Warm Up", "status":"ON" }
```
**All three experience endpoints share the identical body** — only the path differs, chosen by the
experience's **category**. Verified from the builder `p645tj\g.J()` + router (switch on `experienceType`):
- `name` = the experience **TITLE** string (e.g. `"Warm Up"`, `"Beginner Ice Shower"`) — **not** the numeric id.
- `status` = `"ON"` / `"OFF"` (the app sends a *toggle* of the current `state`: `OFF→ON`, else `OFF`).
- **Route by category** (the list the experience came from in the experiences read):

  | Category (read list) | Endpoint |
  |---|---|
  | `showerExperiences` (Warm Up, Cool Down, Sleep Simple, Wake Up, Shine) | `…/hub/shower/experience/control` |
  | `steamExperiences` | `…/hub/steam/experience/control` |
  | `iceShowerExperiences` (Beginner Ice Shower) | `…/hub/iceshower/experience/control` |

  A shower experience sent to the steam/ice path won't work — match the endpoint to the category.
  (Status ON/OFF not live-fired this session, but the body/routing are decompile-confirmed.)

**Experiences are firmware temperature programs — the API exposes NO outlet/valve/curve data.**
`GET …/hub-experience/{deviceId}/experiences` returns only metadata per experience:
```json
{ "experiences": {
    "showerExperiences": [
      { "id":17, "title":"Warm Up", "duration":10.0, "isActive":true, "state":"OFF",
        "description":"Water starts at a comfortable temperature and then slowly increases…" },
      { "id":18, "title":"Cool Down", … }, { "id":19,"title":"Sleep Simple",… },
      { "id":20,"title":"Wake Up",… }, { "id":21,"title":"Shine",… } ],
    "iceShowerExperiences": [ { "id":22, "title":"Beginner Ice Shower", "duration":4.75, … } ],
    "steamExperiences": [] } }
```
- **No `outlets`, `zone`, `water`, or temperature-curve fields** — not in the experience read, not in
  `hub-configuration` (`showerExperiences`/`steamExperiences`/`userPreset` are all `null`), and not in
  the control command. The curve + outlet are **internal to the Hub firmware.**
- **Consequence (live-observed):** every experience runs the curve on the Hub's **default outlet
  (zone1/outlet1)** and **cannot be redirected to another outlet via the API**. For specific-outlet
  control, use a **favourite** (picks outlets/temp/flow) — but favourites hold a *static* temp, not a curve.

---

## 4. Behavioural findings (live-verified)

1. **Music/valve/steam/favourites are all favourite- or on/off-driven.** There is **no direct
   "set outlet/temp/flow now" command** on the Hub. To control specific outlets/temperature/flow
   you **create/edit a favourite** with the `water.zone` config, then activate it.
2. **The app UI forces valve selection when creating favourites, but the API does not** — a
   **music-only** favourite (water `outlets: []`, `music` set) is accepted and works.
3. **Editing a favourite is BLOCKED while the device is running** →
   `HTTP 400`, **`statusCode 902`, `"… is running."`**. You must **stop first**, then edit.
   (Activating a favourite is allowed anytime.)
4. **All-off favourite vs `stopall`:** activating a favourite whose components are all empty
   (music omitted) **stops water + music BUT the system reports that favourite as ON/running**
   (favourite session stays active, nothing flowing). **`stopall` fully idles** the system
   (`state.shower[].status = OFF`, no active favourite).
5. **A favourite for a NotConnected valve doesn't persist:** create returns `201` but the
   favourite silently does not appear (this Hub: `valve2 = NotConnected`).
6. **Outlet encoding:** WRITE `outlets` = list of **0-based positions**; READ `outletState` =
   6-slot bitmask (first 3 slots used = the valve's 3 outlets); READ `outlets` = active count.
7. **`music` all-null object → 400**; omit the key instead.
8. **Music telemetry is on/off only** for device-initiated playback (see §5.4): source / volume /
   track are **not** reliably readable. `amplifierSettings.monoVolume` is a **stored** value (it did
   not track a live touchscreen volume change); `music`/`sdCard` are **presence flags**
   (`present`/`notpresent`), identical whether music is playing or not.

### Status codes seen
`200` favourite-control/edit OK · `201` create / stopall (and warmup) · `202` delete ·
`400` bad data/format · `400 + statusCode 902` device is running · `900` device offline
(from the HA integration) · `403` wrong-policy token on `/commands/*`.

---

## 5. Read response shapes (for HA sensors)

> **State strategy (important):** the REST reads below are **poll-only, not event-driven**, and
> some cloud values **lag or are cached** — e.g. `amplifierSettings.monoVolume` did **not** reflect
> a live touchscreen volume change. For **real-time state, use the MQTT direct-method stream**
> (`$iothub/methods/POST/ExecuteControlCommand`; codes `SHOWER_VALVE_STS`, `STEAM_STS`, `MUSIC_STS`,
> `LIGHT_STS`, `FAVORITE_STS`) — see the **MQTT Capture Runbook**. Use REST for on-demand reads and
> for config/capabilities (`hub-configuration`), not as a live event source.

### 5.1 `hub-state`  (live status)  **[LIVE]**
```json
{
  "state": {
    "shower": [
      { "status":"OFF", "zone":"1", "temperature":"", "flowRate":null, "outlets":[0,0,0,0,0,0] },
      { "status":"OFF", "zone":"2", "temperature":"", "flowRate":null, "outlets":[0,0,0,0,0,0] }
    ],
    "hubSteamState": { "status":"OFF", "totalTime":"0", "temperature":"0", "startTime":"0" },
    "musicStateModel": { "status":"OFF" },
    "light": []
  },
  "connectionState": "Connected",
  "sku": "HUB", "deviceId": "gcs-sious0103D", "tenantId": "<oid>",
  "lastConnected": 1786395174, "showerWarmUp": "0"
}
```
- Per-zone `shower[].status` = `ON`/`OFF`; `outlets` = live 6-slot bitmask; `temperature`,`flowRate` when running.
- `musicStateModel.status`, `hubSteamState.status` = `ON`/`OFF`.
- `showerWarmUp` sits at the **top level, beside `state` rather than inside it**, as `"0"`/`"1"`.
  MQTT carries the same fact as `data.showerwarmup` on `SHOWER_VALVE_STS` — note the casing
  differs between the two transports, and MQTT puts it on `data`, *not* in `attributes`.

#### The controller has no "paused" state

Verified across **466 HUB messages in 32 capture sessions**, plus the in-integration capture:

| Check | Result |
|---|---|
| Attribute keys ever seen | `active audio code component description duration errorcode errorstate flowrate id light lumiwave music name outlets starttime status steam temperature totaltime water zone` |
| Anything matching pause / hold / suspend | **none, anywhere** |
| Distinct `shower[].status` values | exactly two — `ON` (264), `OFF` (256) |
| Distinct `showerwarmup` values | `0` (251), `1` (9) |

Pause is a **GCS concept** — bit `0x40` of the valve command word — with no HUB equivalent. A
paused session is reported by the controller as `OFF`, indistinguishable from idle. So a
controller-derived status sensor can offer **Water Running / Warming Up / Idle and nothing
more**; only `sensor.anthem_valve_status` can say `Paused`.

Every one of the 9 `showerwarmup: 1` messages also had **both zones `ON`** — warm-up runs
water, exactly as on the valve. Anything deriving a status must therefore test warm-up
*before* running, or it will never report warm-up at all.

### 5.2 `…/favorites`
```json
{ "deviceId":"gcs-sious0103D", "sku":"HUB", "tenantId":"<oid>",
  "favorites": [
    { "id":"2", "title":"Flush Cold", "logicalName":"Flush Cold", "state":"OFF",
      "isExperience":false,
      "water": { "zone1": {"temperature":107,"flowrate":100,"outlets":2,"outletState":[1,1,0,0,0,0]},
                 "zone2": {"temperature":107,"flowrate":100,"outlets":2,"outletState":[1,1,0,0,0,0]} },
      "steam": {"temperature":0,"time":0},
      "music": {"volume":70,"source":"aux","trackId":null,"repeatMode":null},
      "light": [] }
  ] }
```
> READ `music` uses `trackId`/`repeatMode`; WRITE uses `songID`/`musicRepeat`. READ `water.zone.outlets`
> is a **count** + `outletState` bitmask; WRITE `water.zone.outlets` is the **position list**.

#### ⚠️ REST says `title`; MQTT says `name` — same field, same favourites

The favourites list arrives from two sources and they **disagree on the name key**:

```text
REST  …/favorites          title="Soap Pause"   name absent
MQTT  FAVORITES_SNAPSHOT   name="Soap Pause"    title absent
```

Same ids, same favourites. Because a client seeds from REST and then has that list
**replaced wholesale** by the first snapshot, reading only one key works at startup and then
silently empties. Always accept both:

```python
name = favorite.get("name") or favorite.get("title") or ""
```

`isExperience` is likewise **REST-only** — the snapshot omits it, so a filter that requires
it will drop every favourite once a snapshot lands. Treat a missing flag as "not an
experience".

#### `FAVORITES_SNAPSHOT` is the refresh mechanism — do not poll

Measured over 33 occurrences:

* **Every** favourite create / edit / delete is followed by a full snapshot within 1-3 s —
  9 of 9, no exceptions. This is why the `CREATE_FAVORITE_STS` / `UPDATE_FAVORITE_STS` /
  `DELETE_FAVORITE_STS` acknowledgements can be ignored: the complete list is right behind
  them.
* It also arrives in the controller's post-boot burst (~3 min after `DEVICE_REBOOT_STS`),
  and in a recurring full-snapshot burst whose trigger is unidentified — it always comes
  last, after `LUMIWAVE_EXP_SNAPSHOT`.
* Timing is irregular (6 s to 21 h between occurrences), so it is **event-driven, not
  periodic**.

Seed once over REST for cold start, then let the snapshot keep the list current. Nothing
needs a timer.

### 5.3 `hub-configuration` (zones/outlets/parts)  **[LIVE]** — abridged
```json
{ "configuration": {
    "parts": { "valve1":"Connected", "valve2":"NotConnected", "amplifier":"Connected",
               "steam":"NotConnected", "control1":"Connected", "hub":"Connected", "light":"NotConnected" },
    "systemConfiguration": { "showerConfiguration":"Custom", "valveMaxTemperature":null },
    "zoneone": { "configuredoutlets":"3", "portsavailable":"3", "defaulttemperature":"102",
                 "flowcapacity":"100", "outletone":62, "outlettwo":52, "outletthree":1 },
    "zonetwo": { "configuredoutlets":"3", "outletone":11, "outlettwo":38, "outletthree":21,
                 "defaultoutlets":[1] },
    "about": { "hub": { "hubname":"http://kohler-myshower.local", "firmware":"2.88",
                        "wlan": {"ip":"<HUB_IP>","ssid":"..."} }, "name":"Anthem Plus",
               "model":"Anthem+ System Controller" } } }
```

#### `parts` is the ONLY way to know what hardware exists

Nothing over MQTT reports installed hardware, and **message arrival does not imply
presence**. On the tested system `parts` reports `light: NotConnected` and
`steam: NotConnected`, yet the captures contain **12 `LIGHT_STS`** and **10 `STEAM_STS`**
messages — the controller happily reports `OFF` forever for accessories nobody owns.
`STATUS_SNAPSHOT` does the same, listing every subsystem regardless.

So a client that creates entities from "we received a `LIGHT_STS`" invents lighting that
does not exist. Gate on `parts`, read once at setup — it is installation-time data, nothing
pushes it, and nothing can.

**Check two keys per accessory, not one.** The presence flags are split across alternate
names and only one is populated:

| Accessory | Keys to check | On this system |
|---|---|---|
| Amplifier | `amplifier`, `music` | `Connected`, **`null`** |
| Lighting | `light`, `lightBridge` | `NotConnected`, `null` |
| Steam | `steam` | `NotConnected` |
| Valve | `valve1`, `valve2`, `valveOne`, `valveTwo` | `Connected`, `NotConnected`, `null`, `null` |

Checking `music` alone reports **no amplifier** on a system that has one.

Also note `parts.valve1`/`valve2` count physical valve **units**, not zones — see
[`../architecture.md`](../architecture.md#valve-means-different-things-on-the-two-apis).
Never gate zone-2 entities on `parts.valve2`; use `zoneone`/`zonetwo` `configuredoutlets`.

> **Distinguish "unread" from "none".** An empty or failed configuration read leaves every
> flag false, which is indistinguishable from a genuine no-accessory system. Track whether
> the read succeeded and prefer creating an entity that reads `unknown` over silently
> omitting one.

### 5.4 Music state — where to read it (and its limits)  **[LIVE-VERIFIED]**

Music telemetry is **thin** across every read. Verified live while SD-card music was playing
(started from the Hub touchscreen):

| Music info | Available? | Source |
|---|---|---|
| **On / Off** | ✅ live & reliable | `hub-state.state.musicStateModel.status` (`ON`/`OFF`); MQTT `MUSIC_STS` `attributes[].status` |
| Amp present / SD present / amp error | ✅ capability flags (static) | `hub-configuration.amplifierSettings.music` / `.sdCard` (`present`/`notpresent`), `.isAmplifierError` |
| **Volume** | ⚠️ **NOT live** | `hub-configuration.amplifierSettings.monoVolume` — a **stored** value; did **not** follow a live touchscreen change |
| **Current source** (`aux`/`sdcard`) | ❌ only if started via a favourite | active favourite's `music.source` (favourite with `state:"ON"`) — **empty when music is started on the Hub touchscreen** (no favourite active) |
| Now-playing track / song / artist | ❌ never exposed | — (`songID`/`trackId` exist only in the **write/favourite** models, for selecting a Kohler-Playlist track) |

**Gotchas confirmed live:**
- `amplifierSettings` read **identically** (`{"monoVolume":50,"stereoVolume":null,"music":"present","sdCard":"present"}`)
  with music OFF and with SD music ON — so `music`/`sdCard` are **presence flags only**, and `monoVolume` did not change.
- When music is played **from the device touchscreen** (not a Konnect favourite), **no favourite is
  `state:"ON"`**, so there is **no readable current source**. Net: for device-initiated playback the
  API gives you **on/off only**.

**MQTT `MUSIC_STS` payload** (model `ValveDataMusic` → `MqttHubMusicStatus[]`):
```json
{ "type": "", "code": "MUSIC_STS", "favoriteid": "0", "experienceid": "0",
  "attributes": [ { "status": "ON", "code": "…", "errorcode": "…", "errorstate": "…", "component": "…" } ] }
```
- `favoriteid` / `experienceid` = which favourite/experience is driving the music (`"0"` = none / direct device control).
- `attributes[].status` = `ON`/`OFF`; **no source/volume/track** here either.

> **Recommended (per user's setup):** treat **MQTT as the primary event-driven state source** and use
> REST reads for config/capabilities and on-demand snapshots. Music, over both channels, is
> effectively **on/off** (+ which favourite/experience, via MQTT `favoriteid`).

---

## 6. Home Assistant snippets

Store `KOHLER_TOKEN` (access token) and refresh it (§1.1) on a schedule; access tokens last ~1h.
Simplest robust pattern: a `shell_command` that refreshes the token to a file, and `rest_command`s
that read it. Example `rest_command`s (assuming `!secret kohler_token` holds a current access token):

```yaml
rest_command:
  hub_favourite_on:
    url: "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/favorite/control"
    method: POST
    headers:
      Authorization: "Bearer {{ states('sensor.kohler_access_token') }}"
      Ocp-Apim-Subscription-Key: "429ecb1d0b5e4258aa0a2bfadd82a493"
      Content-Type: "application/json"
    payload: >-
      {"deviceId":"gcs-sious0103D","tenantId":"{{ states('sensor.kohler_tenant') }}",
       "sku":"HUB","id":"{{ fav_id }}","name":"{{ fav_name }}","state":"ON"}

  hub_stop_all:
    url: "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/stopall"
    method: POST
    headers:
      Authorization: "Bearer {{ states('sensor.kohler_access_token') }}"
      Ocp-Apim-Subscription-Key: "429ecb1d0b5e4258aa0a2bfadd82a493"
      Content-Type: "application/json"
    payload: '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"{{ states(''sensor.kohler_tenant'') }}"}'

  # Simple start = turn the Hub's DEFAULT shower on/off (valveOnOff). No temp/flow/outlet
  # (the Hub uses its own stored default zone config). [STATIC — not live-tested this session]
  hub_simple_start_on:
    url: "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/valvecontrol"
    method: POST
    headers:
      Authorization: "Bearer {{ states('sensor.kohler_access_token') }}"
      Ocp-Apim-Subscription-Key: "429ecb1d0b5e4258aa0a2bfadd82a493"
      Content-Type: "application/json"
    payload: '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"{{ states(''sensor.kohler_tenant'') }}","valveOnOff":"ON"}'

  hub_simple_start_off:
    url: "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/valvecontrol"
    method: POST
    headers:
      Authorization: "Bearer {{ states('sensor.kohler_access_token') }}"
      Ocp-Apim-Subscription-Key: "429ecb1d0b5e4258aa0a2bfadd82a493"
      Content-Type: "application/json"
    payload: '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"{{ states(''sensor.kohler_tenant'') }}","valveOnOff":"OFF"}'

  # Default steam on/off (same model, steamOnOff instead of valveOnOff). [STATIC]
  hub_steam_on:
    url: "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/steamcontrol"
    method: POST
    headers:
      Authorization: "Bearer {{ states('sensor.kohler_access_token') }}"
      Ocp-Apim-Subscription-Key: "429ecb1d0b5e4258aa0a2bfadd82a493"
      Content-Type: "application/json"
    payload: '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"{{ states(''sensor.kohler_tenant'') }}","steamOnOff":"ON"}'
```

`shell_command` + curl equivalents (bash):
```bash
# music ON = start a music-only favourite
curl -s -X POST "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/favorite/control" \
  -H "Authorization: Bearer $KOHLER_TOKEN" -H "Ocp-Apim-Subscription-Key: 429ecb1d0b5e4258aa0a2bfadd82a493" \
  -H "Content-Type: application/json" \
  -d '{"deviceId":"gcs-sious0103D","tenantId":"'$OID'","sku":"HUB","id":"3","name":"Music Only","state":"ON"}'

# everything OFF
curl -s -X POST "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/stopall" \
  -H "Authorization: Bearer $KOHLER_TOKEN" -H "Ocp-Apim-Subscription-Key: 429ecb1d0b5e4258aa0a2bfadd82a493" \
  -H "Content-Type: application/json" \
  -d '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"'$OID'"}'

# SIMPLE START = default shower ON (valveOnOff). [STATIC — not live-tested]
curl -s -X POST "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/valvecontrol" \
  -H "Authorization: Bearer $KOHLER_TOKEN" -H "Ocp-Apim-Subscription-Key: 429ecb1d0b5e4258aa0a2bfadd82a493" \
  -H "Content-Type: application/json" \
  -d '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"'$OID'","valveOnOff":"ON"}'

# SIMPLE START = default shower OFF
curl -s -X POST "https://api-kohler-us.kohler.io/platform/api/v1/commands/hub/valvecontrol" \
  -H "Authorization: Bearer $KOHLER_TOKEN" -H "Ocp-Apim-Subscription-Key: 429ecb1d0b5e4258aa0a2bfadd82a493" \
  -H "Content-Type: application/json" \
  -d '{"deviceId":"gcs-sious0103D","sku":"HUB","tenantId":"'$OID'","valveOnOff":"OFF"}'
```

**Recommended HA control model** (given the 902 running-guard):
- Pre-create one favourite **per state** you want (music-only, shower-preset-A, etc.), then
  switch by **activating** (`favorite/control ON`) — no editing at runtime.
- Use **`stopall`** for a true off. Use an **all-off favourite** only if you want "outputs off
  but session still shown as active".
- To reconfigure a favourite (temp/outlets), **`stopall` first**, then `PATCH`, then activate.

---

## 7. This device's current favourites (reference)

Re-read live 2026-08-11:

| id | title | water | music |
|----|-------|-------|-------|
| 1 | Soap Pause | zone1 outlet3 @103°F | — |
| 2 | Flush Cold | zone1 outlets1,2 @107°F | aux |
| 3 | Music Only | none | aux |
| 4 | SD music | none | sdcard |
| 5 | AllOff-omit | none | — |

The 2026-08-10 session recorded six, with `V1Z1O1` at id 5 and `AllOff-omit` at id 6.
`V1Z1O1` has since been deleted and `AllOff-omit` now occupies id 5 — so **favourite ids
are reassigned rather than stable**. Never hardcode one; resolve it by title at runtime.
