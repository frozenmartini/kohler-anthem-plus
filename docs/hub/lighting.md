# Kohler Anthem Plus — **Zigbee lighting**: pairing investigation

> Everything about the HUB's lighting subsystem: the Zigbee coordinator, the pairing
> API, and the **live-tested conclusion that a third-party bulb cannot be joined
> through the local API on fw 2.88**.
>
> Extends [`local_api.md`](local_api.md) §5, which documents the endpoints. This file
> documents what happens when you actually *use* them against real hardware.
>
> Tested 2026-08-15 against hub fw **2.88** with a Philips Hue bulb. One installation,
> one bulb — see [Limits of this result](#limits-of-this-result).

---

## ❌ Bottom line

**A Philips Hue Zigbee 3.0 bulb could not be joined to the hub's Zigbee coordinator,
under conditions where every failure mode on our side had been eliminated.** The same
bulb, factory-reset and sitting beside the hub, joined Zigbee2MQTT in **13 seconds**
while the hub's own pairing window was still open.

The bulb is not the problem. The hub's coordinator simply never admits it.

**What is proven:** the join does not happen, and the cause is not the documented web-UI
bug, not the payload shape, not the radio being off, not the join window being too short,
not the bulb's reset state, not range, and not a competing coordinator stealing it.

**What is NOT proven:** *why*. The local API exposes no error surface whatsoever
(§6), so "the coordinator never opened permit-join" and "the coordinator rejected the
bulb" are indistinguishable from outside. A firmware guard is the owner's working
hypothesis and is consistent with everything observed, but it is **not established** —
see [What would actually settle it](#what-would-actually-settle-it).

---

## 1. The system under test

| Item | Value |
|---|---|
| Hub | fw **2.88**, `http://<HUB_IP>/web/api/v1/device/` |
| Coordinator | System Controller's **lighting card** — `get_lightcard_info` → `channel: 11`, `status: "Connected"`, `errorCode: null` |
| Not a bridge | `connected_dev_info.lightbridge: false` — there is no separate Hue-style bridge |
| Network mode | `connected_dev_info.zigbeeconnection: **"secured"**` |
| Joined bulbs | `pairedlights: []`, `get_connected_light_count → {"devices": 0}` — **zero, throughout** |
| Groups | A / B / C, all `{connected: 0, disconnected: 0}`; **12 bulbs max** |
| Test bulb | Philips/Signify **LTA008** (`9290022267A`, "Hue white ambiance E27 with Bluetooth"), EUI64 `0x001788010daad238` |

**⚠️ The Zigbee radio had switched itself off.** At the start of this session
`get_zigbee_status → {"status":"false"}` and `get_hub_settings.zigbeeEnabled → false`,
even though [`../handoff/2026-08-10_hub_local.md`](../handoff/2026-08-10_hub_local.md) §2
recorded it as enabled on 2026-08-10. Something turned it back off in between — plausibly
the controller reboots documented in
[`../gcs/valve_reboot_fault.md`](../gcs/valve_reboot_fault.md), which were frequent in that
window. **Always check the radio state before concluding anything about pairing**; it was
re-enabled here with `toggle_zigbee` (which is a *toggle*, not a set — read the state
first).

---

## 2. The two controlled experiments

Both used the same bulb, with the hub's scan driven directly via
[`zigbee_pair.py`](#tooling) rather than the web UI.

### 2a. Experiment 1 — touchlink reset

| Time | Event |
|---|---|
| 10:15:28 | Zigbee2MQTT touchlink: `Reset to factory new '0x001788010daad238'`, `status: ok` |
| — | Kohler scan run, bulb beside the hub, **Z2M permit-join closed** → no join |
| 10:30:22 | Z2M permit-join opened (254 s) |
| 10:32:47 | Bulb `device_announce` to Z2M |
| 10:32:50 | `Successfully interviewed … device has successfully been paired` |

### 2b. Experiment 2 — Hue app Bluetooth reset ⭐

The stronger of the two: the reset used the Hue app over **Bluetooth**, so neither Zigbee
coordinator was involved in it at all.

| Time | Kohler hub | Zigbee2MQTT |
|---|---|---|
| 11:00:40 | `zigbee_scan_init` — window **open** | permit-join **closed** |
| 11:00:43 – 11:06:19 | open continuously, re-armed ×6, 24 polls, all `devices: []` | closed |
| | **← 5.5 minutes, Kohler the only open network, no join** | |
| 11:06:19 | **still open** | permit-join **opened** |
| **11:06:32** | **still open**, `devices: []` | **bulb announces — 13 s later** |
| 11:06:34 | `devices: []` | **paired** |
| 11:08:24 | 29th poll, `devices: []` | — |
| 11:08:43 | `scan_stop`, `pairedlights: []` | — |

Two features make this decisive:

1. **For 5.5 minutes the hub's window was the only one open** — bulb factory-fresh,
   actively searching, physically beside the hub — and nothing joined.
2. **From 11:06:19 to 11:06:32 both windows were open simultaneously**, and the bulb chose
   Z2M within 13 seconds. Its network address changed `61928 → 50544`, confirming a genuine
   fresh join rather than a cached reconnect.

### 2c. What these rule out

| Hypothesis | Eliminated by |
|---|---|
| The fw 2.88 web-UI bug (§5.6) | Bypassed entirely — API driven directly |
| Wrong `bulbs` payload shape | All three tested: `[]`, `["001788010daad238"]`, `["0x001788010daad238"]` |
| Zigbee radio off | Verified `true` before each run |
| Join window too short | 8 minutes, `scan_init` re-armed every 60 s |
| Bulb not actually reset | Disproved — it joined Z2M seconds later, twice |
| Bulb out of range | It reached Z2M's mesh *from beside the Kohler hub* |
| Z2M stealing the bulb | Its permit-join was **closed** for the first 5.5 minutes |

---

## 3. Live JS bundle analysis (fw 2.88)

Pulled from the running hub: `/web/main.3d1b487f7045d010.js`, 4,932,796 bytes.

### 3a. §5.6's bug is real and unchanged in shipping code

Confirmed verbatim — the scan loop hardcodes the **secured** list on both calls:

```js
for (let i = 0; i < 9; i++) {
  let r = { req_command: "zigbee_scan_status", bulbs: t.detectedBulbs, initcall: "false" };
  if (0 == i) r = { req_command: "zigbee_scan_init", bulbs: t.detectedBulbs, initcall: "true" };
  const p = yield t.zigbeeService.scanLighting(r).toPromise();
  t.scannedData = p.devices;
}
```

…while the caller empties that same list whenever unsecured bulbs are queued:

```js
this.unscuredBulbs.length > 0 && (this.detectedBulbs = []);
this.executeApiSequentially();
```

### 3b. ⭐ The "accept the risk" prompt is **purely client-side**

This is new, and it closes a question the earlier session left open. The dialog is opened
by `pairingscreen()`:

```js
pairingscreen(t) {
  this.unscuredBulbs.length > 0
    ? this.dialog.open(Xdt, {...}).afterClosed().subscribe(i => {
        this.dialog.closeAll();
        "y" == i.data && (t.next(), this.title = "Pair",
                          this.titletext = "Set Lightning Device Into Pairing Mode and Scan");
        "n" == i.data && (this.unscuredBulbs = []);
      })
    : (this.title = "Pair", this.titletext = "Turn ON Zigbee Lights",
       "unsecured" === this.previousConnection && (this.detectedBulbs = []), t.next());
}
```

Accepting the risk calls `t.next()` and changes a title. **It makes no API call.** So
nothing the user does in that dialog can flip the network from `"secured"` to
`"unsecured"` — the transition, if it exists, is entirely hub-side.

### 3c. There is no security-mode command at all

All **61** `req_command` strings in the bundle were enumerated. **None** changes Zigbee
security mode. The complete Zigbee set is only:

```
zigbee_scan_init   zigbee_scan_status   zigbee_scan_stop   toggle_zigbee   ble_on
```

Also found: **`update_gcs_ui_settings`**, which is missing from
[`local_api.md`](local_api.md) §8's inventory.

### 3d. The warning text argues *against* an install-code-only coordinator

```
UNSECURED BULBS
Adding unsecured Zigbee light bulbs can compromise the network's security.
To continue with the pairing process, please accept the associated risk when
prompted or remove the bulb(s) from your setup.
```

A warning phrased this way only makes sense if unsecured bulbs *can* join. The UI also
carries a full `previousConnection === "unsecured"` branch whose heading is **"Turn ON
Zigbee Lights"** and which sends `bulbs: []` — i.e. in unsecured mode an **empty list is
the intended payload**, not a degenerate one. That variant was tested and also failed.

### 3e. Undocumented response fields

`zigbee_scan_init` / `zigbee_scan_status` return fields not in §5.2:

| `bulbs` sent | Response |
|---|---|
| `[]` | `{"devices":[], "old_entries":[], "removed_later":[]}` |
| `["001788010daad238"]` | `{"bulbs":[…], "devices":[], "old_entries":[], "removed_later":[], "reset": false}` |

A non-empty list is **echoed back** and gains a `reset` field, so the hub does register the
identifier — the request is not being discarded. `old_entries` and `removed_later` are
always empty here and their meaning is unknown.

---

## 4. ⚠️ "Hue is the wrong kind of bulb" is not a coherent theory

Worth stating plainly, because it is the intuitive explanation and it does not hold up.

- **Hue is standard Zigbee.** Modern Hue bulbs, including this LTA008, are **Zigbee 3.0**,
  which merged the old ZLL and Zigbee-HA profiles in 2016. The bulb joined Zigbee2MQTT — a
  generic stack — in ~2 seconds, twice. Its Z2M definition exposes ordinary ZCL clusters:
  on/off `0x0006`, level `0x0008`, colour temp `0x0300`. The only Philips-specific item is
  an **opt-in, off-by-default** option Z2M describes as using "a Philips-specific protocol
  *instead of* standard Zigbee commands".
- **Sengled and Hue are in the same security class.** Kohler's only documented bulb family,
  **Sengled Element**, has **no install code** — it is a default-link-key bulb, exactly like
  Hue. An install-code-only coordinator would reject Kohler's own supported hardware.
- **Coordinator silicon is irrelevant.** Whatever chip the lighting card uses (the API
  exposes no EUI64, module id or vendor — only `zigbee.firmware: "1.31"` and node name
  `gcs_zigbee`), Zigbee certification exists so certified devices interoperate. What gates a
  join is *firmware policy*: whether permit-join is truly opened, Trust Center install-code
  policy, and any vendor whitelist.

**Therefore:** if a Sengled joins where a Hue does not, the only remaining explanation is a
**manufacturer/model whitelist in Kohler's firmware** — not the protocol, not the profile,
not the silicon.

**A corollary worth noting.** A Sengled QR decodes *without* `$I`, so it lands in
`unscuredBulbs` and hits the §3a bug — meaning **on fw 2.88 Kohler's own supported bulb
almost certainly cannot be added through the web UI either.** If that is right, the
unsecured path is broken for everyone on this firmware and this was never Hue-specific.
Untested — it needs a Sengled.

---

## 5. Zigbee join stages — why the failure is ambiguous

A join has three stages, and failure at any of them yields an identical empty result:

1. **Beacon.** The bulb broadcasts a beacon request per channel; coordinators reply with a
   beacon carrying a *permit-joining* flag. The bulb only proceeds where it is true.
2. **Association.** If permitted, it associates and is assigned a 16-bit network address.
3. **Trust Center key transport.** The network key is sent, encrypted under either the
   default link key (`ZigBeeAlliance09`) or an install-code-derived key. **Install-code
   policy and whitelists bite here.**

Failing at stage 1 means the hub never saw the bulb at all. Failing at stage 3 means it saw
it, addressed it, and dropped it. From the API both are `devices: []`.

One weak signal: hub HTTP latency roughly **doubled** during an active scan (~8 s idle
→ ~15–20 s per poll cycle), suggesting the coordinator is tasked with *something* by
`zigbee_scan_init`. Suggestive only — not proof that permit-join opens.

---

## 6. ❌ There is no error surface — all diagnostics exhausted

| Surface | Result |
|---|---|
| `zigbee_scan_status` | **No error field exists** — only `devices`, `old_entries`, `removed_later`, `reset` |
| `get_lightcard_info.errorCode` | `null` throughout, including immediately after each failed attempt |
| `get_error_log` | **Times out.** Hangs and never responds — tested at 12 s, 90 s and **170 s**, on both `{"req_command":"get_error_log"}` and `{…,"data":{}}`. Effectively dead on fw 2.88, despite §8 listing it as a diagnostic |
| `get_error_log` as a GET | Returns HTML — SPA catch-all, not a real route |
| Port 9000 internal backend | Localhost-only, unreachable from the LAN |

**No hub-side visibility into the radio layer exists.** This is the single biggest obstacle
to progressing further.

---

## 7. What would actually settle it

| Test | Cost | Answers |
|---|---|---|
| **A genuine Sengled Element bulb** (E11/E12 series) | ~$10–15 | *Whether local pairing can ever work.* Joins → firmware whitelist, and Hue is simply out. Fails too → the pairing path is broken/gated on fw 2.88 and no bulb will join locally |
| **Zigbee sniffer on channel 11** (spare CC2531/CC2652 + Wireshark) | ~$10–20 | *Why.* Does the hub's beacon advertise permit-join after `scan_init` (stage 1)? Does the bulb send an association request and does the hub ACK it (stage 2)? Does a transport-key follow (stage 3)? Also reveals the coordinator's EUI64, hence its module vendor |

The Sengled is the cheaper and more directly useful of the two. **Note the sniffer must be a
*second* radio** — an in-use coordinator cannot sniff.

---

## 8. ⚠️ Operational trap: touchlink can freeze your whole Zigbee network

Discovered the hard way during this session. **Touchlink switches the coordinator's radio
into InterPAN mode** — raw, unencrypted, cross-network frames on endpoint 254 / cluster
`0x1000`, hopping channel to channel. While in that mode the radio **cannot carry normal
network traffic**, by design.

A healthy sweep ends with `Restore InterPAN channel` and releases the lock. If it is
interrupted, the restore never runs and two locks stay held in zigbee-herdsman:

```
Touchlink operation already in progress    (Touchlink.lock)
Cannot execute command, in Inter-PAN mode  (ZStackAdapter.checkInterpanLock)
```

Zigbee2MQTT then rejects **every** command — including `permit_join`, the one needed here —
and the entire Zigbee network is frozen until cleared. Observed: 83 InterPAN failures in one
log. **Restarting Zigbee2MQTT clears it**; if it survives that, reboot the coordinator
itself (a network coordinator over TCP holds radio state independently of Z2M).

**Prefer a non-touchlink reset.** Z2M's plain **Remove** (not *Force remove* — that only
deletes the database row and leaves the bulb bound) sends an ordinary in-network leave
request, factory-resetting the bulb without ever entering InterPAN mode. The Hue app's
Bluetooth reset is better still: it touches no Zigbee coordinator at all.

**Also note:** this house's Zigbee2MQTT runs on **channel 11 — the same channel as the
Kohler coordinator**. Not a blocker, but it means a freshly reset bulb inside the Z2M mesh
has a well-connected rival for its attention. Keep Z2M's permit-join **closed** during any
Kohler pairing attempt.

---

## Tooling — how to reproduce this

The script used here (`kohler-work/zigbee_pair.py`) was **shredded after the session**, along
with the PIN file it read, because it held a working path to the hub's authenticated API.
Rebuilding it is short — the login is the stdlib recipe in [`local_api.md`](local_api.md) §2,
and the scan is three calls on top of it:

```python
cmd(tok, "zigbee_scan_init",   bulbs=["001788010daad238"], initcall="true")
cmd(tok, "zigbee_scan_status", bulbs=["001788010daad238"], initcall="false")   # poll
cmd(tok, "zigbee_scan_stop")
```

Four things the throwaway version got right and a rebuild should keep:

- **Never take the PIN through a chat window.** Read it from a file the owner writes from
  their own terminal, or from an environment variable — the convention `fresh_token.sh` uses.
- **`zigbee_scan_init` is mutating** — it opens permit-join on the coordinator. Always issue
  `zigbee_scan_stop` in a `finally`. A killed process skips that, so send it manually
  afterwards.
- **Re-issue `zigbee_scan_init` every ~60 s** on runs longer than a couple of minutes. A
  single init may let the join window lapse silently, which is a failure mode
  indistinguishable from a rejected bulb.
- **Timestamp every poll.** The entire conclusion in §2b rests on aligning the hub's log
  against Zigbee2MQTT's to the second.

Check the radio first (`get_zigbee_status`, `get_hub_settings.zigbeeEnabled`) — see §1's
warning — and remember `toggle_zigbee` is a *toggle*, not a set.

---

## Limits of this result

- **One hub, one firmware (2.88), one bulb, one installation.** Nothing here has been
  reproduced on other hardware or other firmware.
- **Only Philips Hue was tested.** No Sengled — the officially supported family — was ever
  tried, so the whitelist hypothesis in §4 is untested in both directions.
- **"Firmware guarded" is a hypothesis, not a finding.** It fits the evidence and the owner
  reports no known case of anyone adding third-party lighting to this product, but §6 means
  we cannot see the coordinator's decision, so no mechanism has been demonstrated.
- **The 2.72-era behaviour is unknown.** `nclpl/anthem_shower` was built against fw 2.72;
  whether pairing worked there has not been checked.

## Even on success, local control does not follow

Per [`local_api.md`](local_api.md) §5: on fw 2.88 `update_lighting_settings` is **scene/preset
config**, not live per-bulb control. There is no "bulb on/off/dim now" command in the local
API. A paired bulb becomes part of group A/B/C and only lights when a favourite or experience
runs — and those are triggered **cloud-side**. Pairing a bulb locally would not yield locally
controllable lights.
