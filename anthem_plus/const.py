"""Protocol constants for the Kohler Anthem Plus cloud and local APIs.

Values here are app-global — baked into the Konnect Android app (3.0.1) and identical
across accounts. Nothing in this module is a per-user secret.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cloud API
# ---------------------------------------------------------------------------
API_BASE = "https://api-kohler-us.kohler.io"

# The APIM subscription key identifies the app to Kohler's API gateway. It is app-global and
# stable (verified identical across sessions and accounts), not a per-user credential.
# api-kohler-us.kohler.io does NOT require mTLS — the client certificate in the APK is only
# for the alternate *.kohlerkonnect-apim.azure-api.net gateway, which this client never uses.
APIM_SUBSCRIPTION_KEY = "429ecb1d0b5e4258aa0a2bfadd82a493"

# ---------------------------------------------------------------------------
# Azure AD B2C auth
# ---------------------------------------------------------------------------
# Writes to /commands/* are only accepted for tokens issued by the B2C_1A_signin policy.
# ROPC-policy tokens get HTTP 403 on writes; reads accept either. That is why sign-in is
# interactive rather than username/password.
CLIENT_ID = "8caf9530-1d13-48e6-867c-0f082878debc"
API_RESOURCE = "f5d87f3d-bdeb-4933-ab70-ef56cc343744"
B2C_TENANT = "konnectkohler.onmicrosoft.com"
B2C_SIGNIN_POLICY = "B2C_1A_signin"
B2C_AUTHORITY = f"https://konnectkohler.b2clogin.com/tfp/{B2C_TENANT}/{B2C_SIGNIN_POLICY}"
B2C_AUTHORIZE_URL = f"{B2C_AUTHORITY}/oauth2/v2.0/authorize"
B2C_TOKEN_URL = f"{B2C_AUTHORITY}/oauth2/v2.0/token"
B2C_SCOPE = f"openid offline_access https://{B2C_TENANT}/{API_RESOURCE}/apiaccess"

# The registered redirect URI. Probed against B2C 2026-08-11: this exact value is accepted
# and near misses are not (msauth.com.example.fake://auth, msauth.com.kohler.hermoth://other
# and .../auth/extra all return AADB2C90006), so validation is strict and this is a genuine
# registration rather than loose scheme matching.
#
# The older APK-derived URI "msauth://com.kohler.hermoth/2DuDM2vGmcL4bKPn2xKzKpsy68k%3D" is
# NO LONGER REGISTERED — B2C rejects it outright. Any flow still using it is broken before
# the browser is even involved.
#
# Nothing ever navigates here. The sign-in runs server-side and reads the code out of the
# 302 Location header, so the unresolvable custom scheme never reaches a browser.
B2C_REDIRECT_URI = "msauth.com.kohler.hermoth://auth"

# Server-side sign-in endpoints (B2C custom-policy "SelfAsserted" flow).
B2C_POLICY_BASE = (
    f"https://konnectkohler.b2clogin.com/{B2C_TENANT}/{B2C_SIGNIN_POLICY}"
)
B2C_SELF_ASSERTED_URL = f"{B2C_POLICY_BASE}/SelfAsserted"
B2C_CONFIRMED_URL = f"{B2C_POLICY_BASE}/api/CombinedSigninAndSignup/confirmed"

# B2C error codes worth distinguishing for the UI.
ERROR_BAD_CREDENTIALS = "AADB2C90053"
ERROR_REDIRECT_NOT_REGISTERED = "AADB2C90006"

# B2C rotates the refresh token on every silent refresh; dropping the new one strands the
# account until the next interactive sign-in. Refresh tokens last up to ~90 days.
TOKEN_EXPIRY_MARGIN_SECONDS = 300

# ---------------------------------------------------------------------------
# SKUs
# ---------------------------------------------------------------------------
# GCS is the Anthem digital valve body (built-in Wi-Fi, addressed directly).
# HUB is the Anthem Plus Linux system controller (drives valves, music, light, steam).
# Device IDs are NOT a reliable discriminator — an Anthem Plus controller's id can begin
# with "gcs". Always branch on the sku field.
SKU_GCS = "GCS"
SKU_HUB = "HUB"

# ---------------------------------------------------------------------------
# Reads — /devices/api/v1/device-management/
# ---------------------------------------------------------------------------
DEVICE_API = "/devices/api/v1/device-management"
CUSTOMER_DEVICE = f"{DEVICE_API}/customer-device/{{tenant_id}}"
HUB_STATE = f"{DEVICE_API}/hub-state/{{device_id}}"
HUB_FAVORITES = f"{DEVICE_API}/hub-experience/{{device_id}}/favorites"
HUB_EXPERIENCES = f"{DEVICE_API}/hub-experience/{{device_id}}/experiences"
HUB_CONFIGURATION = f"{DEVICE_API}/hub-configuration/{{device_id}}"
HUB_DIAGNOSTICS = f"{DEVICE_API}/hub-diagnostics/{{device_id}}"
HUB_DIAGNOSTICS_ACTIVE = f"{DEVICE_API}/hub-diagnostics/{{device_id}}/active"
HUB_USAGE = f"{DEVICE_API}/hub-usage/{{device_id}}"
GCS_PRESETS = f"{DEVICE_API}/gcs-preset/{{device_id}}"
GCS_STATE = f"{DEVICE_API}/gcs-state/{{device_id}}"
# The valve's settings block — the only source of outlet topology that does not need a
# controller. Distinct from gcs-configuration, which is null on a controller-attached valve.
GCS_ADVANCE_STATE = f"{DEVICE_API}/gcs-state/gcsadvancestate/{{device_id}}"

# ---------------------------------------------------------------------------
# Commands — /platform/api/v1/commands/
# ---------------------------------------------------------------------------
COMMANDS = "/platform/api/v1/commands"

# GCS: no bare on/off exists. Every start specifies the full valve state.
GCS_SOLOWRITESYSTEM = f"{COMMANDS}/gcs/solowritesystem"
GCS_CONTROL_PRESET = f"{COMMANDS}/gcs/controlpresetorexperience"
GCS_START_PRESET = f"{COMMANDS}/gcs/startpreset"
GCS_WRITE_PRESET = f"{COMMANDS}/gcs/writepreset"
GCS_CREATE_PRESET = f"{COMMANDS}/gcs/createpreset"
GCS_WARMUP = f"{COMMANDS}/gcs/warmup"
GCS_VALVE_RESET = f"{COMMANDS}/gcs/valvereset"

# HUB: favourite-centric. There is no direct "set outlet/temp/flow now" command.
HUB_VALVE_CONTROL = f"{COMMANDS}/hub/valvecontrol"
HUB_STEAM_CONTROL = f"{COMMANDS}/hub/steamcontrol"
HUB_FAVORITE_CONTROL = f"{COMMANDS}/hub/favorite/control"
HUB_FAVORITE = f"{COMMANDS}/hub/favorite"
HUB_STOP_ALL = f"{COMMANDS}/hub/stopall"
HUB_SHOWER_EXPERIENCE = f"{COMMANDS}/hub/shower/experience/control"
HUB_STEAM_EXPERIENCE = f"{COMMANDS}/hub/steam/experience/control"
HUB_ICESHOWER_EXPERIENCE = f"{COMMANDS}/hub/iceshower/experience/control"

# All three experience endpoints share one body; the path is chosen by the category the
# experience came from in the experiences read. Sending a shower experience to the steam
# path does not work.
EXPERIENCE_ENDPOINTS = {
    "showerExperiences": HUB_SHOWER_EXPERIENCE,
    "steamExperiences": HUB_STEAM_EXPERIENCE,
    "iceShowerExperiences": HUB_ICESHOWER_EXPERIENCE,
}

# ---------------------------------------------------------------------------
# Response status codes
# ---------------------------------------------------------------------------
# Kohler returns these inside the response body, not only as HTTP status.
STATUS_DEVICE_OFFLINE = 900
# Editing a favourite while the system is running is rejected. Activating one is not.
STATUS_DEVICE_RUNNING = 902

# ---------------------------------------------------------------------------
# GCS warmup modes
# ---------------------------------------------------------------------------
# Warmup is a mode toggle, not a run-now command: the command IS the enable/disable. Once
# enabled it runs automatically per the chosen mode. The library this replaces sent no
# warmUp field at all, so the device accepted the request (200) and ignored it.
WARMUP_DISABLED = "warmUpDisabled"
WARMUP_ALL_OUTLETS_NOW = "warmUpAllOutletsWithNoStartDelay"
WARMUP_ALL_OUTLETS = "warmUpAllOutlets"
WARMUP_SELECTED_OUTLETS_NOW = "warmUpSelectedOutletsWithNoStartDelay"
WARMUP_SELECTED_OUTLETS = "warmUpSelectedOutlets"

#: The three the **current** Konnect app offers, and the only ones anything should write.
#: Owner-established 2026-08-20 against the app in their hands. A 2026-08-20 decompile of
#: Konnect Android 3.0.1 had reported only two — disabled and all-outlets — and called
#: selected-outlets unverified; this install's own captures settle it, because the valve
#: held `warmUpSelectedOutletsWithNoStartDelay` three separate times on 2026-08-13 with no
#: other client in play. **The app moved on; the decompile was of an older build.**
WARMUP_MODES_CURRENT = (
    WARMUP_DISABLED,
    WARMUP_ALL_OUTLETS_NOW,
    WARMUP_SELECTED_OUTLETS_NOW,
)

#: The two delayed-start variants, kept because the firmware still parses them and a valve
#: could be holding one. **Decodable, not writable**: nothing defines what their delay is —
#: the app has no control that sets one, and "delay" appears nowhere in its string
#: resources. See `docs/gcs/api.md` §3e.
WARMUP_MODES_LEGACY = (WARMUP_ALL_OUTLETS, WARMUP_SELECTED_OUTLETS)

#: Every value the firmware recognises.
WARMUP_MODES = WARMUP_MODES_CURRENT + WARMUP_MODES_LEGACY

# warmUpState carries two independent axes: `warmUp` is the mode above, `state` is whether
# it is running right now.
WARMUP_IN_PROGRESS = "warmUpInProgress"
WARMUP_NOT_IN_PROGRESS = "warmUpNotInProgress"

# Registering a "mobile device" is how a client obtains Azure IoT Hub credentials for the
# real-time status stream. The returned SAS password is short-lived and per-session: obtain
# it per run and never persist it.
MOBILE_SETTINGS = "/platform/api/v1/mobile/settings"

# ---------------------------------------------------------------------------
# MQTT — Azure IoT Hub
# ---------------------------------------------------------------------------
# Status arrives as direct-method messages. The app never publishes control here, and
# neither does this client: the confirmed write path is HTTPS /commands/*.
MQTT_PORT = 8883
MQTT_METHOD_TOPIC = "$iothub/methods/POST/#"
MQTT_RESPONSE_TOPIC = "$iothub/methods/res/200/?$rid={rid}"

# ONE topic carries everything. Across 856 messages in 20 capture logs, 100% arrived on
# `$iothub/methods/POST/ExecuteControlCommand/?$rid=N` and none on any other topic. The
# device-scoped topics some clients also subscribe to (devices/<id>/messages/events/# and
# .../devicebound/#) are acknowledged but have never delivered anything.
MQTT_SUBSCRIBE_TOPIC = "$iothub/methods/POST/#"

# A fresh registration receives NOTHING for roughly the first minute, despite a clean
# CONNECT and granted SUBACKs. Register once, hold the connection, and treat early silence
# as meaningless. Reconnecting per command guarantees receiving nothing at all.
MQTT_WARMUP_SECONDS = 60

# The direct-method subscription is account-level, so a session opened for one device
# receives messages for both. Filter on payload deviceid and sku.
MSG_GCS_SOLO_STATUS = "GCS_SOLO_STS"
MSG_GCS_PRESET_STATUS = "GCS_PRESET_STS"
MSG_GCS_WARMUP_STATUS = "GCS_WARM_STS"
MSG_GCS_EXPERIENCE_STATUS = "READ_GCS_EXPERIENCE_STS"
MSG_GCS_OUTLET_CONFIG = "READ_GCS_OUTLET_CONFIG_CFG"
MSG_GCS_UI_CONFIG = "READ_GCS_UI_CFG"
MSG_GCS_REBOOT = "DEVICE_REBOOT_STS"
MSG_FIRMWARE_VERSIONS = "READ_ALL_INTERFACES_FIRMWARE_VERSION_STATUS_INFO"

MSG_HUB_SHOWER_VALVE = "SHOWER_VALVE_STS"
MSG_HUB_STEAM = "STEAM_STS"
MSG_HUB_MUSIC = "MUSIC_STS"
MSG_HUB_LIGHT = "LIGHT_STS"
MSG_HUB_FAVORITE = "FAVORITE_STS"
MSG_HUB_SYSTEM = "SYSTEM_STS"
# Carries the whole favourites list rather than a delta. Pushed after **every** create,
# edit, and delete (9 of 9 in the captures) as well as on reboot, so it is the favourite
# refresh mechanism and no polling is needed.
#
# The CREATE_FAVORITE_STS / UPDATE_FAVORITE_STS / DELETE_FAVORITE_STS acknowledgements are
# deliberately not modelled: each is followed 1-3 s later by this snapshot carrying the full
# list, so handling them would be work for a delta we are about to receive in full.
MSG_HUB_FAVORITES_SNAPSHOT = "FAVORITES_SNAPSHOT"

# ---------------------------------------------------------------------------
# HUB local LAN API
# ---------------------------------------------------------------------------
# Setup, configuration, and diagnostics only — this surface cannot actuate anything on
# firmware 2.88. water_test_start runs a fixed zone1/outlet1 ~5s plumbing self-test and
# ignores any temperature/flow/outlet fields. Real control is cloud-side.
LOCAL_API_BASE = "http://{host}/web/api/v1/device"
LOCAL_LOGIN = "request_user_login"
LOCAL_COMMAND = "req_update_command"

# The hub's JWT is short-lived (minutes) and obtained from a PIN. These endpoints are
# reachable with no token at all, and two of them mutate state.
LOCAL_PREAUTH_ENDPOINTS = frozenset(
    {
        "get_hub_running_state",
        "get_hub_version_info",
        "hub_date_config_state",
        "set_hub_datetime",
    }
)

# Baked into the hub's Angular bundle. Used to encrypt the PIN as
# base64(RSA_PKCS1v15(sha256(pin).hexdigest_ascii)).
LOCAL_RSA_PUBLIC_KEY_B64 = (
    "MIGJAoGBAOBnPtJlU6y62vyrcHgqZPAlr+FM10BpUxBvRx5u0fXNEjXcda4y3WSU"
    "2ECzf9HcmDU5r6fD2jiFPyTuXu7jY2qzAI7QME6eoaJd2q+QLKpcUVq5MTeFo9b6"
    "zpZlGHUiiy0NrFdKPjD+UdPXi/t1oEKaj/loWiZ7p0P02paUoI41AgMBAAE="
)
