# Kohler Anthem Plus

A Home Assistant integration for the **Kohler Anthem** digital shower valve and the
**Anthem Plus** controller. Unofficial, not affiliated with or endorsed by Kohler.

> ⚠️ **Placeholder README.** Structure and presentation still to be done.

## What it does

Controls the shower — outlets, temperature, flow, presets — and the Anthem Plus controller's
music, lighting and steam, from Home Assistant.

State arrives by **push**, not polling: the integration subscribes to Kohler's Azure IoT Hub
MQTT stream and updates when the device reports a change (`iot_class: cloud_push`,
`SCAN_INTERVAL = None`). REST is read once at setup and again on each reconnect, to reseed.

## Who it's for

Owners of a Kohler Anthem valve, an Anthem Plus controller, or both, who want them in Home
Assistant. It is aimed at people comfortable with a custom integration and an undocumented
cloud API — not a supported product.

## Requirements

* Home Assistant **2024.2** or later
* A Kohler Konnect account, and the shower already set up in the Konnect app
* **Internet access.** Control is cloud-only for both products: if Kohler's cloud is
  unreachable, nothing here can turn the shower on or off. The controller's local LAN API can
  read configuration but cannot actuate anything.

## Install

Add this repository to HACS as a custom repository, then install and restart Home Assistant.
Configure from **Settings → Devices & Services → Add Integration**.

## Tested against

**One installation** — a single K-28212 (6 outlets, two zones) plus an Anthem Plus controller
on firmware 2.88. Every finding in [`docs/`](docs/) is derived from and verified against that
one system. Other models and other configurations are supported on the basis of what the
protocol says, not on the basis of anyone having run them. Reports from different hardware are
genuinely useful.

The API is undocumented and Kohler can change it without notice.

## Documentation

[`docs/`](docs/) is the protocol reference — both cloud APIs, the MQTT message catalogue, the
valve command word, and case studies working through real showers message by message.
[`docs/prior_art.md`](docs/prior_art.md) credits the projects this one started from and
records where their readings differ.

## Licence

MIT — see [LICENSE](LICENSE).
