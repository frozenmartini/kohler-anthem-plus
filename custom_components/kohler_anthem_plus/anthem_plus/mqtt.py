"""Azure IoT Hub status stream for Kohler Anthem devices.

Kohler pushes device status as IoT Hub **direct methods**, all of them on one account-level
topic. A single connection therefore carries every device on the account — GCS and HUB
alike — and callers filter by ``sku`` and ``device_id``.

Three behaviours drive the design, each learned the hard way:

* **Hold the connection, and reuse the identity.** A connect-per-command client receives
  nothing, ever. The identity is registered once and persisted by the caller rather than
  generated per connect, which previously left a dead registration behind on every restart.
  A *newly* registered identity may not receive for a short while; a reused one is already
  provisioned. See :attr:`AnthemMqttStream.warming_up` for how thin that evidence is.
* **One topic.** Only ``$iothub/methods/POST/#`` delivers. Device-scoped topics are
  acknowledged and stay silent.
* **Acknowledgement.** Direct methods must be answered on
  ``$iothub/methods/res/200/?$rid=N`` or the service will consider them unhandled.

The transport is paho-mqtt, which runs its own network thread. Callbacks are marshalled
onto the owning event loop so consumers never touch that thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import paho.mqtt.client as mqtt

from .auth import AuthError, AuthUnavailable
from .connectivity import RecoveryBackoff, error_label
from .client import KohlerClient
from .const import (
    MQTT_PORT,
    MQTT_RESPONSE_TOPIC,
    MQTT_SUBSCRIBE_TOPIC,
    MQTT_WARMUP_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

_RID = re.compile(r"\$rid=([^&]+)")

KEEPALIVE_SECONDS = 60


class MqttCredentialRejected(ConnectionError):
    """Broker rejected SAS credentials, not proof that OAuth reauth is needed."""

# Building an SSL context reads the system CA bundle from disk. That is blocking file I/O,
# so it must never happen on an event loop — paho's `tls_set()` does exactly that
# internally, which stalls every other task while it runs. Build the context once in a
# worker thread and hand paho the finished object via `tls_set_context()` instead.
_ssl_context: ssl.SSLContext | None = None
_ssl_lock = asyncio.Lock()


async def async_default_ssl_context() -> ssl.SSLContext:
    """Return a shared TLS context, created off the event loop on first use."""
    global _ssl_context
    async with _ssl_lock:
        if _ssl_context is None:
            _ssl_context = await asyncio.to_thread(ssl.create_default_context)
        return _ssl_context


@dataclass(frozen=True)
class Envelope:
    """One decoded status message."""

    sku: str
    device_id: str
    code: str
    attributes: list[dict[str, Any]]
    received_at: float
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def attribute(self, code: str | None = None, **match: Any) -> dict[str, Any] | None:
        """First attribute matching ``code`` and any extra field equalities."""
        for item in self.attributes:
            if not isinstance(item, dict):
                continue
            if code is not None and item.get("code") != code:
                continue
            if all(item.get(k) == v for k, v in match.items()):
                return item
        return None


class AnthemMqttStream:
    """Holds one long-lived IoT Hub connection and dispatches decoded envelopes.

    Usage::

        stream = AnthemMqttStream(client, on_envelope)
        await stream.async_start()
        ...
        await stream.async_stop()
    """

    def __init__(
        self,
        client: KohlerClient,
        on_envelope: Callable[[Envelope], None],
        *,
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        on_event: Callable[..., None] | None = None,
        on_auth_error: Callable[[AuthError], None] | None = None,
        mobile_device_id: str | None = None,
        raw_sinks: list[Any] | None = None,
        expect_warmup: bool = True,
        loop: asyncio.AbstractEventLoop | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._client = client
        self._on_envelope = on_envelope
        # Called on the owning loop after every successful connect, including reconnects.
        #
        # This exists because **the broker replays nothing on connect**. Measured across 27
        # sessions: the first message is always a change event, never a state dump — 6
        # sessions received nothing at all, and the worst wait was 11.9 hours. Without a
        # read triggered from here, a consumer is blind from connect until somebody next
        # uses the shower.
        self._on_connect_cb = on_connect
        self._on_disconnect_cb = on_disconnect
        self._on_event = on_event
        self._recovery = RecoveryBackoff()
        self._connection_waiter: asyncio.Future | None = None
        # Called on the owning loop when a reconnect fails because the stored credential was
        # *rejected* — not merely because Kohler was unreachable.
        #
        # Without this the reconnect loop is a silent trap: every connect needs a fresh SAS
        # token, minting one needs a valid access token, and a dead refresh token therefore
        # fails every attempt forever while logging at WARNING. Nothing else in the push-only
        # design ever exercises the credential, so there is no other moment at which a
        # consumer could notice and prompt the user.
        self._on_auth_error_cb = on_auth_error
        # Latched so one outage produces one notification rather than one per retry.
        self._auth_error_reported = False
        self._loop = loop
        self._ssl_context = ssl_context
        self._mqtt: mqtt.Client | None = None
        self._closing = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._connected_at: float | None = None
        # Reuse one registered identity instead of a throwaway per connect. None falls back
        # to the old behaviour of generating a fresh one.
        self._mobile_device_id = mobile_device_id
        # RAW SINKS: everything that wants each message exactly as it arrived, before the
        # decode — `write(topic, payload, *, qos, retain)` on the paho thread, `close()` at
        # teardown. In a release the list holds the user's Report Log (a no-op until its
        # switch is on); the author's development capture adds itself on one machine.
        self._raw_sinks: list[Any] = list(raw_sinks or ())
        # Only a *newly registered* identity can plausibly need warm-up; one that has
        # connected before is already provisioned. Cleared for good by the first message —
        # data arriving is proof the channel works, whatever the clock says.
        self._warmup_pending = expect_warmup
        self.connected = False
        self.last_message_at: float | None = None
        self.last_error: str | None = None
        self.next_retry_at: float | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def async_start(self) -> None:
        """Register, connect, and subscribe. Returns once the socket is up."""
        self._closing = False
        self._loop = self._loop or asyncio.get_running_loop()
        try:
            await self._async_connect()
        except AuthError as err:
            if isinstance(err, AuthUnavailable):
                self._start_reconnect_task()
            else:
                self._report_auth_error(err)
            raise
        except Exception:
            self._start_reconnect_task()
            raise

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._closing = True
        self.next_retry_at = None
        if self._reconnect_task is not None:
            task = self._reconnect_task
            task.cancel()
            self._reconnect_task = None
            await asyncio.gather(task, return_exceptions=True)
        client, self._mqtt = self._mqtt, None
        if client is not None:
            client.disconnect()
            await asyncio.to_thread(client.loop_stop)
        self.connected = False
        # Release every sink's file on unload. For the Report Log this is the handle only —
        # `close()` does not end the episode, so a reload resumes the same file.
        for sink in self._raw_sinks:
            await asyncio.to_thread(sink.close)

    @property
    def warming_up(self) -> bool:
        """True while the connection is too young to expect messages.

        Silence during this window means nothing — do not infer device state from it.

        Only ever true for a **freshly registered** identity that has not yet received
        anything, and the first message clears it permanently. A reused identity is already
        provisioned, so it never warms up.

        The 60 s figure is a conservative upper bound, not a measurement, and the evidence
        for it is thin: the original test confounded "too soon after connect" with
        "disconnected immediately after", and five capture sessions on fresh identities
        received their first message inside the window, the earliest at **37 s**. Treat it
        as a cap on how long silence stays uninformative, nothing more.
        """
        if not self._warmup_pending:
            return False
        if self._connected_at is None:
            return True
        return (time.monotonic() - self._connected_at) < MQTT_WARMUP_SECONDS

    async def _async_connect(self) -> None:
        """Obtain fresh credentials and bring up the connection."""
        # The SAS password is short-lived and single-use in practice, so every connect
        # fetches fresh credentials — but for the *same* identity when one was supplied.
        settings = await self._client.async_register_mobile_device(
            self._mobile_device_id
        )
        host = settings["ioTHub"]
        device_id = settings["deviceId"]

        kwargs: dict[str, Any] = {
            "client_id": device_id,
            "protocol": mqtt.MQTTv311,
            "transport": "tcp",
            "reconnect_on_failure": False,
        }
        # paho-mqtt 2.x requires an explicit callback API version; 1.x has no such
        # argument and rejects it. Home Assistant has shipped both.
        if hasattr(mqtt, "CallbackAPIVersion"):
            kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION1
        client = mqtt.Client(**kwargs)
        client.username_pw_set(settings["username"], settings["password"])
        # Never `tls_set()` here: it loads CA certificates from disk on the calling thread.
        context = self._ssl_context or await async_default_ssl_context()
        client.tls_set_context(context)
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        self._mqtt = client
        self._connection_waiter = asyncio.get_running_loop().create_future()
        client.connect_async(host, MQTT_PORT, keepalive=KEEPALIVE_SECONDS)
        client.loop_start()
        _LOGGER.debug("Kohler MQTT connecting to %s as %s", host, device_id[-16:])
        await asyncio.wait_for(self._connection_waiter, timeout=30)

    def _finish_connect(self, client: mqtt.Client, error: Exception | None = None) -> None:
        if self._closing or client is not self._mqtt:
            return
        waiter = self._connection_waiter
        if waiter is not None and not waiter.done():
            if error:
                waiter.set_exception(error)
            else:
                waiter.set_result(None)

    # ------------------------------------------------------------------ #
    # paho callbacks — these run on paho's network thread
    # ------------------------------------------------------------------ #
    def _on_connect(
        self, client: mqtt.Client, _userdata: Any, _flags: Any, rc: int, *_: Any
    ) -> None:
        if self._closing or client is not self._mqtt:
            return
        if rc != 0:
            error = MqttCredentialRejected("MQTT SAS credential rejected") if rc in (4, 5) else ConnectionError("MQTT connection refused")
            self._loop.call_soon_threadsafe(self._finish_connect, client, error)
            return
        client.subscribe(MQTT_SUBSCRIBE_TOPIC, qos=1)

    def _on_subscribe(self, client: mqtt.Client, _userdata: Any, _mid: int, granted_qos: Any, *_: Any) -> None:
        if self._closing or client is not self._mqtt:
            return
        if not granted_qos or any(int(qos) >= 128 for qos in granted_qos):
            self._loop.call_soon_threadsafe(self._finish_connect, client, ConnectionError("MQTT subscription rejected"))
            return
        self.connected = True
        self._connected_at = time.monotonic()
        # Credentials demonstrably work again; re-arm for the next outage.
        self._auth_error_reported = False
        # Only mention warm-up when one can actually apply. A reused identity is already
        # provisioned, so saying "expect no messages for 60s" would send anyone reading the
        # log looking for a delay that is not there.
        if self._warmup_pending:
            _LOGGER.info(
                "Kohler MQTT connected on a new identity; expect no messages for ~%ss "
                "while it provisions",
                MQTT_WARMUP_SECONDS,
            )
        else:
            _LOGGER.info(
                "Kohler MQTT connected (identity %s, already provisioned — no warm-up)",
                (self._mobile_device_id or "generated")[-8:],
            )
        self._dispatch_connected(client)
        self._loop.call_soon_threadsafe(self._finish_connect, client)

    def _on_disconnect(
        self, _client: mqtt.Client, _userdata: Any, rc: int, *_: Any
    ) -> None:
        if self._closing or _client is not self._mqtt:
            return
        self.connected = False
        self._connected_at = None
        self.last_error = "MQTT disconnected"
        if self._closing:
            return
        self._loop.call_soon_threadsafe(self._disconnected, _client)

    def _disconnected(self, client: mqtt.Client) -> None:
        if self._closing or client is not self._mqtt:
            return
        self._finish_connect(client, ConnectionError("MQTT disconnected before setup completed"))
        if self._recovery.since is None:
            _LOGGER.warning("Kohler MQTT disconnected; reconnecting")
        if self._on_disconnect_cb:
            self._on_disconnect_cb()
        self._start_reconnect_task()

    def _on_message(
        self, client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        if self._closing or client is not self._mqtt:
            return
        # Acknowledge first: the service treats an unanswered direct method as unhandled,
        # and a decode failure should not suppress the acknowledgement.
        match = _RID.search(message.topic)
        if match:
            client.publish(
                MQTT_RESPONSE_TOPIC.format(rid=match.group(1)),
                b'{"status":"received"}',
                qos=1,
            )
        # --- RAW SINKS call site — see anthem_plus/report_log.py -------------------
        # Before the decode, deliberately: everything below this point is lossy, and the
        # payloads that fail to parse are dropped entirely. Those are the ones worth having.
        for sink in self._raw_sinks:
            sink.write(
                message.topic,
                message.payload,
                qos=message.qos,
                retain=message.retain,
            )
        # --- end RAW SINKS call site -------------------------------------------------

        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _LOGGER.debug("Ignoring non-JSON MQTT payload on %s", message.topic)
            return
        if not isinstance(payload, dict):
            return

        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        attributes = data.get("attributes")
        envelope = Envelope(
            sku=str(payload.get("sku") or ""),
            device_id=str(payload.get("deviceid") or ""),
            code=str(data.get("code") or ""),
            attributes=[a for a in (attributes or []) if isinstance(a, dict)],
            received_at=time.time(),
            raw=payload,
        )
        self.last_message_at = envelope.received_at
        # Proof the channel delivers. Ends the warm-up for good, not just for this
        # connection: once an identity has received anything it is provisioned, and a
        # reconnect cannot un-provision it.
        self._warmup_pending = False
        self._dispatch(envelope, client)

    # ------------------------------------------------------------------ #
    # Thread hand-off
    # ------------------------------------------------------------------ #
    def _dispatch(self, envelope: Envelope, client: mqtt.Client) -> None:
        """Hand an envelope to the consumer on the owning event loop."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._safe_callback, envelope, client)

    def _safe_callback(self, envelope: Envelope, client: mqtt.Client) -> None:
        if self._closing or not self.connected or client is not self._mqtt:
            return
        try:
            self._on_envelope(envelope)
        except Exception:  # noqa: BLE001 - a bad consumer must not kill the stream
            _LOGGER.exception("Kohler MQTT consumer raised on %s", envelope.code)

    def _dispatch_connected(self, client: mqtt.Client) -> None:
        """Notify the consumer of a connect, on the owning loop.

        Runs on paho's network thread, so it hands off the same way envelopes do.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._safe_connected, client)

    def _safe_connected(self, client: mqtt.Client) -> None:
        if self._closing or not self.connected or client is not self._mqtt:
            return
        if self._recovery.since is not None:
            # WARNING to match the "disconnected" onset; see the note in `coordinator.py`.
            _LOGGER.warning("Kohler MQTT connection recovered")
        self._recovery.reset()
        self.last_error = None
        self.next_retry_at = None
        try:
            if self._on_connect_cb is not None:
                self._on_connect_cb()
        except Exception:  # noqa: BLE001 - a bad consumer must not kill the stream
            _LOGGER.exception("Kohler MQTT connect consumer raised")

    def _report_auth_error(self, err: AuthError) -> None:
        """Hand a rejected credential to the consumer, once per outage.

        No loop hop, unlike :meth:`_dispatch_connected`: the only caller is
        :meth:`_async_reconnect`, which is already a task on the owning loop.
        """
        if self._auth_error_reported or self._on_auth_error_cb is None:
            return
        self._auth_error_reported = True
        self.last_error = "Reauthentication required"
        self.next_retry_at = None
        try:
            self._on_auth_error_cb(err)
        except Exception:  # noqa: BLE001 - a bad consumer must not kill the stream
            _LOGGER.exception("Kohler MQTT auth-error consumer raised")

    def _schedule_reconnect(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or self._closing:
            return
        loop.call_soon_threadsafe(self._start_reconnect_task)

    def _start_reconnect_task(self) -> None:
        if self._closing or (
            self._reconnect_task is not None and not self._reconnect_task.done()
        ):
            return
        self._reconnect_task = asyncio.create_task(self._async_reconnect())

    async def _async_reconnect(self) -> None:
        """One reconnect owner: immediate, 1/2/5 minutes, then long-outage backoff."""
        delay = 0.0
        while not self._closing:
            await asyncio.sleep(delay)
            self.next_retry_at = None
            if self._closing:
                return
            old, self._mqtt = self._mqtt, None
            if old is not None:
                try:
                    old.disconnect()
                    await asyncio.to_thread(old.loop_stop)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Error tearing down old MQTT client", exc_info=True)
            try:
                await self._async_connect()
                if self.connected:
                    return
            except AuthError as err:
                # OAuth rejection requires reauth; a network failure does not. Broker
                # SAS rejection is a separate ConnectionError: retry with newly minted
                # SAS credentials without incorrectly declaring the user's login dead.
                if not isinstance(err, AuthUnavailable):
                    self._report_auth_error(err)
                    return
                self._mqtt_failure(err)
            except Exception as err:  # noqa: BLE001 - keep retrying on any failure
                self._mqtt_failure(err)
            delay = self._recovery.fail(minimum=getattr(self._client, "cloud_retry_delay", 0))
            self.next_retry_at = time.time() + delay
            if self._on_event:
                self._on_event("mqtt_retry_scheduled", retry_in=delay)
            if not self._recovery.long_reported and time.monotonic() - self._recovery.since >= 86400:
                self._recovery.long_reported = True
                _LOGGER.info("Kohler MQTT remains unavailable; retrying hourly")

    def _mqtt_failure(self, err: BaseException) -> None:
        self.last_error = error_label(err)
        _LOGGER.debug("Kohler MQTT reconnect failed: %s", error_label(err))
        if self._on_event:
            self._on_event("mqtt_retry_failed", error=error_label(err))
