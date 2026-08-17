"""Authenticated REST client for the Kohler Konnect cloud API.

Wraps :class:`~.auth.KohlerAuth` with the headers every call needs, transparent token
refresh, and translation of Kohler's two error channels into exceptions.

Kohler reports failure in two places and you have to check both:

* the HTTP status, and
* a ``statusCode`` field **inside** a 200/400 body — ``900`` means the device is offline,
  ``902`` means it is running and refuses the edit.

A request can therefore "succeed" with HTTP 200 and still have done nothing.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import aiohttp

from .auth import AuthError, KohlerAuth
from .models import OutletStateSource, resolve_outlet_source
from .const import (
    API_BASE,
    APIM_SUBSCRIPTION_KEY,
    CUSTOMER_DEVICE,
    GCS_ADVANCE_STATE,
    GCS_PRESETS,
    HUB_CONFIGURATION,
    HUB_EXPERIENCES,
    HUB_FAVORITES,
    HUB_STATE,
    MOBILE_SETTINGS,
    SKU_GCS,
    SKU_HUB,
    STATUS_DEVICE_OFFLINE,
    STATUS_DEVICE_RUNNING,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class KohlerError(Exception):
    """A Kohler API call failed."""

    def __init__(self, message: str, payload: Any = None, status: int | None = None) -> None:
        super().__init__(message)
        self.payload = payload
        #: HTTP status when this came from a response, else None. Lets a caller tell apart
        #: failures that mean different things — a 404 on a collection endpoint is "empty",
        #: not "broken" — without parsing the message string.
        self.status = status


class DeviceOffline(KohlerError):
    """The device is powered off or has lost its cloud link (statusCode 900).

    Expected and transient — surface it gently rather than as a failure.
    """


class DeviceRunning(KohlerError):
    """The device is running and refuses the change (statusCode 902).

    Editing a HUB favourite requires the system to be stopped first. Activating one is
    allowed at any time, which is why the practical pattern is to pre-create a favourite
    per state and switch by activation rather than editing at runtime.
    """


class Device:
    """One device on the account."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.device_id: str = raw.get("deviceId") or raw.get("deviceid") or ""
        self.sku: str = raw.get("sku") or ""
        self.name: str = raw.get("logicalName") or raw.get("name") or self.device_id
        self.serial_number: str | None = raw.get("serialNumber")

    @property
    def is_gcs(self) -> bool:
        """True for the Anthem digital valve."""
        return self.sku == SKU_GCS

    @property
    def is_hub(self) -> bool:
        """True for the Anthem Plus system controller.

        Note this is decided by ``sku``, never by the device id — an Anthem Plus
        controller's id can begin with "gcs".
        """
        return self.sku == SKU_HUB

    def __repr__(self) -> str:
        return f"<Device {self.sku} {self.device_id} {self.name!r}>"


class Customer:
    """The account record, which is also where the device list lives.

    Devices are nested under ``customerHome[].devices[]`` — note the singular key, which is
    easy to guess wrong. The account also decides the units the API reports in.
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        # "Fahrenheit" or "Celsius". Kohler's REST API and the GCS valve byte both report
        # Celsius regardless; this is the account's *display* preference, which the mobile
        # app converts to locally. The HUB's favourite temperatures, however, ARE in this
        # unit — so it decides how HUB writes are encoded.
        self.temperature_unit: str = raw.get("temperatureUnit") or "Fahrenheit"
        self.water_units: str = raw.get("waterUnits") or "Standard"
        self.devices: list[Device] = [
            Device(device)
            for home in _as_list(raw.get("customerHome") or raw.get("homes"))
            if isinstance(home, dict)
            for device in _as_list(home.get("devices"))
            if isinstance(device, dict)
        ]

    def device(self, sku: str) -> Device | None:
        """The first device with the given SKU, or None."""
        return next((d for d in self.devices if d.sku == sku), None)

    def devices_of(self, sku: str) -> list[Device]:
        """Every device with the given SKU."""
        return [d for d in self.devices if d.sku == sku]

    @property
    def gcs_devices(self) -> list[Device]:
        """Anthem digital valves on the account."""
        return self.devices_of(SKU_GCS)

    @property
    def hub_devices(self) -> list[Device]:
        """Anthem Plus system controllers on the account."""
        return self.devices_of(SKU_HUB)

    @property
    def has_gcs(self) -> bool:
        """Whether the account has at least one Anthem digital valve."""
        return bool(self.gcs_devices)

    @property
    def has_hub(self) -> bool:
        """Whether the account has at least one Anthem Plus controller."""
        return bool(self.hub_devices)

    @property
    def other_devices(self) -> list[Device]:
        """Devices this integration does not support.

        The Konnect app covers many Kohler product lines (DTV, Numi, Blade, faucets, and
        more). They appear on the same account and must be ignored rather than treated as
        a malformed Anthem device.
        """
        return [d for d in self.devices if d.sku not in (SKU_GCS, SKU_HUB)]

    @property
    def supported_devices(self) -> list[Device]:
        """Anthem devices this integration can drive."""
        return self.gcs_devices + self.hub_devices

    @property
    def outlet_source(self) -> OutletStateSource | None:
        """Which channel should feed outlet, temperature, and flow entities.

        GCS wins whenever it is present — see
        :func:`~.models.resolve_outlet_source` for why HUB-sourced outlets would go stale
        rather than merely lag on a both-devices account.
        """
        return resolve_outlet_source(self.has_gcs, self.has_hub)

    def describe(self) -> str:
        """A short human summary of what was found, for logs and the config flow.

        Note a GCS and a HUB on one account are often the SAME physical shower, reached
        through two different touchscreen interfaces — see :mod:`.models` for why. They are
        still presented as two separate devices: they behave differently, and the HUB's
        state consistently trails the valve's.
        """
        parts = []
        if self.has_gcs:
            parts.append(f"{len(self.gcs_devices)} Anthem valve(s)")
        if self.has_hub:
            parts.append(f"{len(self.hub_devices)} Anthem Plus controller(s)")
        if not parts:
            return "no Anthem devices found on this account"
        summary = " and ".join(parts)
        if self.other_devices:
            skus = ", ".join(sorted({d.sku for d in self.other_devices}))
            summary += f" (ignoring other Kohler devices: {skus})"
        return summary


class KohlerClient:
    """Authenticated access to the Kohler Konnect cloud API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: KohlerAuth,
        tenant_id: str | None = None,
    ) -> None:
        self._session = session
        self._auth = auth
        self._tenant_id = tenant_id

    @property
    def auth(self) -> KohlerAuth:
        """The underlying auth handler, for persisting a rotated refresh token."""
        return self._auth

    @property
    def tenant_id(self) -> str | None:
        """The account id every device call is keyed on."""
        return self._tenant_id or self._auth.tenant_id

    async def async_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_retry: bool = True,
    ) -> Any:
        """Make an authenticated request, refreshing the token once on a 401."""
        token = await self._auth.async_get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Key": APIM_SUBSCRIPTION_KEY,
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                f"{API_BASE}{path}",
                json=json_body,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                text = await resp.text()
                status = resp.status
        except aiohttp.ClientError as err:
            raise KohlerError(f"Network error calling {path}: {err}") from err

        # A 401 usually means the access token aged out mid-flight; one retry with a
        # freshly minted token is enough. Retrying more would mask a real auth failure.
        if status == 401 and allow_retry:
            # INFO, not DEBUG. This is rare, it costs a token refresh plus a second round
            # trip — seconds, not milliseconds — and it is the only thing in this client that
            # can make a single call take that long. A 5.05 s valve restore on 2026-08-15
            # could not be explained afterwards precisely because this line was invisible
            # under default logging. See the session 8 handoff.
            _LOGGER.info(
                "401 from %s — the access token aged out mid-request; refreshing it and "
                "retrying once. Expect this call to take a few seconds longer than usual",
                path,
            )
            await self._auth.async_refresh()
            return await self.async_request(
                method, path, json_body=json_body, allow_retry=False
            )

        payload: Any = None
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = text

        self._raise_for_payload(status, path, payload)
        return payload

    @staticmethod
    def _raise_for_payload(status: int, path: str, payload: Any) -> None:
        """Translate Kohler's HTTP status and in-body statusCode into exceptions."""
        inner = payload.get("statusCode") if isinstance(payload, dict) else None
        if inner == STATUS_DEVICE_OFFLINE:
            raise DeviceOffline(
                "The Kohler device is offline. Check that it is powered on and "
                "connected to Wi-Fi.",
                payload,
            )
        if inner == STATUS_DEVICE_RUNNING:
            raise DeviceRunning(
                "The system is running, so this change was rejected. Stop it first "
                "(stopall), then retry.",
                payload,
            )
        if status >= 400:
            detail = payload if isinstance(payload, str) else repr(payload)
            raise KohlerError(
                f"{path} failed with HTTP {status}: {detail}", payload, status
            )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def async_get_customer(self) -> Customer:
        """Read the account: its devices plus the units the API reports in."""
        tenant_id = self.tenant_id
        if not tenant_id:
            raise AuthError("No tenant id available; sign in first.")
        payload = await self.async_request(
            "GET", CUSTOMER_DEVICE.format(tenant_id=tenant_id)
        )
        if not isinstance(payload, dict):
            raise KohlerError("Unexpected customer-device response", payload)
        return Customer(payload)

    async def async_get_devices(self) -> list[Device]:
        """List every device on the account, across all homes."""
        return (await self.async_get_customer()).devices

    async def async_register_mobile_device(
        self, mobile_device_id: str | None = None
    ) -> dict[str, Any]:
        """Register a mobile client and return Azure IoT Hub credentials.

        This is how the real-time MQTT status stream is reached. The returned settings
        carry ``ioTHub`` (hostname), ``deviceId`` (the MQTT client id to use), ``username``
        and ``password`` (a short-lived SAS token).

        The credentials are per-session and must NEVER be persisted or logged — obtain
        them fresh on each connect.

        ``mobile_device_id`` **should** be persisted and reused, though: it is the identity,
        not a credential. Omitting it generates a throwaway one, which registers what Kohler
        sees as another phone on every single connect.
        """
        tenant_id = self.tenant_id
        if not tenant_id:
            raise AuthError("No tenant id available; sign in first.")
        device_id = mobile_device_id or uuid.uuid4().hex[:16]
        payload = {
            "tenantId": tenant_id,
            "mobileDeviceId": device_id,
            "username": "HomeAssistant",
            "os": "Android",
            "devicePlatform": "FirebaseCloudMessagingV1",
            "deviceHandle": f"ha_{device_id}",
            "tags": ["FirmwareUpdate"],
        }
        data = await self.async_request("POST", MOBILE_SETTINGS, json_body=payload)
        settings = (data or {}).get("ioTHubSettings") or {}
        if not settings.get("ioTHub"):
            raise KohlerError("Kohler returned no IoT Hub settings", data)
        return settings

    async def async_get_gcs_settings(self, device_id: str) -> dict[str, Any]:
        """Read the valve's own settings block, including its outlet topology.

        This is the authoritative source for how many outlets sit on each valve — it comes
        from the valve itself, so it works without an Anthem Plus controller. Note the path
        is ``gcs-state/gcsadvancestate/…``, NOT the plain ``gcs-configuration/…``, which
        returns null for every structural field on a controller-attached valve.
        """
        payload = await self.async_request(
            "GET", GCS_ADVANCE_STATE.format(device_id=device_id)
        )
        if not isinstance(payload, dict):
            return {}
        return payload.get("setting") or {}

    async def async_get_hub_state(self, device_id: str) -> dict[str, Any]:
        """Live HUB status: per-zone shower, steam, music, light."""
        return await self.async_request("GET", HUB_STATE.format(device_id=device_id))

    async def async_get_gcs_presets(self, device_id: str) -> dict[str, Any]:
        """The valve's stored presets, as ``gcsPresetExperienceDetails[]``.

        Only needed to seed and as a backstop: the device pushes ``GCS_PRESET_STS`` on every
        create, edit, rename, and delete, so preset changes do not need polling.
        """
        return await self.async_request("GET", GCS_PRESETS.format(device_id=device_id))

    async def async_get_hub_favorites(self, device_id: str) -> dict[str, Any]:
        """The HUB's saved favourites — the unit of control for this device."""
        return await self.async_request("GET", HUB_FAVORITES.format(device_id=device_id))

    async def async_get_hub_experiences(self, device_id: str) -> dict[str, Any]:
        """The HUB's firmware experience programs, grouped by category."""
        return await self.async_request(
            "GET", HUB_EXPERIENCES.format(device_id=device_id)
        )

    async def async_get_hub_configuration(self, device_id: str) -> dict[str, Any]:
        """Zones, outlets, installed parts, and capability flags."""
        return await self.async_request(
            "GET", HUB_CONFIGURATION.format(device_id=device_id)
        )


def _as_list(value: Any) -> list[Any]:
    """Coerce a possibly-missing API list field into a list."""
    return value if isinstance(value, list) else []
