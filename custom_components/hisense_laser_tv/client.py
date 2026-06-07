"""Local MQTT client for Hisense VIDAA / Laser TV devices."""

from __future__ import annotations

import json
import logging
import hashlib
import posixpath
import queue
import re
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

DEVICE_TOPIC = "XX:XX:XX:XX:XX:XY$vidaa_common"
VALID_SERVICES = {"platform_service", "remote_service", "ui_service"}


@dataclass(frozen=True)
class VidaaAuthIdentity:
    """Temporary identity used by the VIDAA mobile app pairing flow."""

    client_id: str
    username: str
    password: str
    mac_address: str


@dataclass(frozen=True)
class MqttConnectOptions:
    """MQTT connection options for firmware compatibility."""

    name: str
    client_id: str | None = None
    username: str | None = "hisenseservice"
    password: str | None = "multimqttservice"
    protocol: int = mqtt.MQTTv311
    clean_session: bool = False


class HisenseLaserTvError(Exception):
    """Base client error."""


class HisenseLaserTvTimeoutError(HisenseLaserTvError):
    """Raised when the TV does not respond in time."""


class HisenseLaserTvAuthorizationError(HisenseLaserTvError):
    """Raised when the TV rejects MQTT authorization."""


class HisenseLaserTvNotConnectedError(HisenseLaserTvError):
    """Raised when a command is sent before connection."""


class HisenseLaserTvClient:
    """Small paho-mqtt 2.x compatible client for the Hisense local API."""

    def __init__(
        self,
        host: str,
        *,
        port: int = 36669,
        timeout: int | float = 8,
        ssl_context: ssl.SSLContext | None = None,
        client_id: str | None = None,
        device_topic: str | None = None,
        username: str | None = "hisenseservice",
        password: str | None = "multimqttservice",
        protocol: int = mqtt.MQTTv311,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.client_id = client_id
        self.device_topic = device_topic or DEVICE_TOPIC
        self.username = username
        self.password = password
        self.protocol = protocol
        self.connected = False
        self._connection_error: str | None = None
        self._queue: queue.Queue[Any] = queue.Queue()
        self._client: mqtt.Client | None = None

    def connect(self) -> None:
        """Connect to the TV MQTT broker."""
        if self.connected:
            return

        client_id = self.client_id or f"{self.__class__.__name__}/{uuid.uuid4()!s}"
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=False,
            protocol=self.protocol,
        )
        if self.username is not None:
            self._client.username_pw_set(
                username=self.username,
                password=self.password,
            )
        if self.ssl_context is not None:
            self._client.tls_set_context(context=self.ssl_context)
            self._client.tls_insecure_set(True)

        self._client.on_connect = self._on_connect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.connect(self.host, self.port)
        self._client.loop_start()
        _LOGGER.debug("Hisense MQTT socket opened to %s:%s", self.host, self.port)

        start_time = time.monotonic()
        while not self.connected:
            time.sleep(0.01)
            if self._connection_error and "not authorized" in self._connection_error.lower():
                connection_error = self._connection_error
                self.disconnect()
                raise HisenseLaserTvAuthorizationError(connection_error)
            if time.monotonic() - start_time > self.timeout:
                connection_error = self._connection_error
                self.disconnect()
                if connection_error:
                    raise HisenseLaserTvTimeoutError(
                        f"failed to connect in {self.timeout:.3f}s: {connection_error}"
                    )
                raise HisenseLaserTvTimeoutError(
                    f"failed to connect in {self.timeout:.3f}s"
                )

    def disconnect(self) -> None:
        """Disconnect from the TV MQTT broker."""
        self.connected = False
        if self._client is None:
            return
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._client = None

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if not _is_successful_reason_code(reason_code):
            self._connection_error = f"connect returned {reason_code}"
            _LOGGER.warning("Hisense MQTT connect returned %s", reason_code)
            return
        client.subscribe(posixpath.join("/", "remoteapp", "mobile", "broadcast", "#"))
        client.subscribe(
            posixpath.join("/", "remoteapp", "mobile", self.device_topic, "#")
        )
        self.connected = True
        self._connection_error = None

    def _on_connect_fail(
        self,
        client: mqtt.Client,
        userdata: Any,
    ) -> None:
        self._connection_error = "connect failed"

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: mqtt.Properties | None,
    ) -> None:
        self.connected = False
        if not _is_successful_reason_code(reason_code):
            self._connection_error = f"disconnect returned {reason_code}"

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        if not message.payload:
            self._queue.put_nowait(None)
            return
        raw_payload = message.payload.decode("utf-8")
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            payload = raw_payload
        self._queue.put_nowait(
            {
                "topic": message.topic,
                "payload": payload,
            }
        )

    def _wait_for_response(self) -> Any:
        try:
            return self._queue.get(block=True, timeout=self.timeout)
        except queue.Empty as err:
            raise HisenseLaserTvTimeoutError(
                f"failed to receive a response in {self.timeout:.3f}s"
            ) from err

    def _wait_for_payload(self, predicate: Any, description: str) -> Any:
        """Wait until a queued payload matches a predicate."""
        deadline = time.monotonic() + float(self.timeout)
        while time.monotonic() < deadline:
            try:
                message = self._queue.get(block=True, timeout=0.25)
            except queue.Empty:
                continue
            payload = _message_payload(message)
            if predicate(payload):
                return payload
        raise HisenseLaserTvTimeoutError(
            f"failed to receive {description} in {self.timeout:.3f}s"
        )

    def _call_service(
        self,
        *,
        service: str,
        action: str,
        payload: str | dict[str, Any] | None = None,
    ) -> None:
        if not self.connected or self._client is None:
            raise HisenseLaserTvNotConnectedError("you must be connected")
        if service not in VALID_SERVICES:
            raise ValueError(f"invalid service: {service}")
        if isinstance(payload, dict):
            payload = json.dumps(payload)

        topic = posixpath.join(
            "/",
            "remoteapp",
            "tv",
            service,
            self.device_topic,
            "actions",
            action,
        )
        message = self._client.publish(topic=topic, payload=payload)
        message.wait_for_publish()

    def initialise_vidaa_1140(self) -> None:
        """Send the same first requests as the legacy VIDAA app on protocol 1140."""
        self._call_service(service="ui_service", action="gettvstate")
        self._call_service(service="ui_service", action="capability")

    def _publish_topic(self, topic: str, payload: str | dict[str, Any] | None) -> None:
        if not self.connected or self._client is None:
            raise HisenseLaserTvNotConnectedError("you must be connected")
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        message = self._client.publish(topic=topic, payload=payload)
        message.wait_for_publish()

    def _subscribe_topic(self, topic: str) -> None:
        if not self.connected or self._client is None:
            raise HisenseLaserTvNotConnectedError("you must be connected")
        self._client.subscribe(topic)

    def start_vidaa_pairing(self) -> None:
        """Ask the TV to show the VIDAA mobile-app authentication code."""
        mobile_base = posixpath.join("/", "remoteapp", "mobile", self.device_topic)
        tv_ui_base = posixpath.join(
            "/", "remoteapp", "tv", "ui_service", self.device_topic
        )
        broadcast_base = posixpath.join("/", "remoteapp", "mobile", "broadcast")
        for topic in (
            posixpath.join(mobile_base, "ui_service", "data", "authentication"),
            posixpath.join(mobile_base, "ui_service", "data", "authenticationcode"),
            posixpath.join(mobile_base, "platform_service", "data", "tokenissuance"),
            posixpath.join(broadcast_base, "ui_service", "state"),
        ):
            self._subscribe_topic(topic)

        self._call_service(service="ui_service", action="gettvstate")
        self._call_service(service="ui_service", action="capability")
        self._publish_topic(
            posixpath.join(tv_ui_base, "actions", "vidaa_app_connect"),
            {"app_version": 2, "connect_result": 0, "device_type": "Mobile App"},
        )

    def finish_vidaa_pairing(self, auth_code: str) -> dict[str, Any]:
        """Send the TV authentication code and return issued token data."""
        digits = re.sub(r"\D", "", str(auth_code))
        if not digits:
            raise HisenseLaserTvAuthorizationError("empty VIDAA authentication code")

        mobile_base = posixpath.join("/", "remoteapp", "mobile", self.device_topic)
        tv_ui_base = posixpath.join(
            "/", "remoteapp", "tv", "ui_service", self.device_topic
        )
        tv_platform_base = posixpath.join(
            "/", "remoteapp", "tv", "platform_service", self.device_topic
        )
        self._subscribe_topic(
            posixpath.join(mobile_base, "ui_service", "data", "authenticationcode")
        )
        self._subscribe_topic(
            posixpath.join(mobile_base, "platform_service", "data", "tokenissuance")
        )
        self._publish_topic(
            posixpath.join(tv_ui_base, "actions", "authenticationcode"),
            f'{{"authNum":{digits}}}',
        )
        auth_result = self._wait_for_payload(
            lambda payload: isinstance(payload, dict) and "result" in payload,
            "VIDAA authentication result",
        )
        if auth_result.get("result") != 1:
            raise HisenseLaserTvAuthorizationError(
                f"VIDAA authentication code was rejected: {auth_result}"
            )

        self._publish_topic(
            posixpath.join(tv_ui_base, "actions", "authenticationcodeclose"),
            None,
        )
        return auth_result

    def get_volume(self) -> dict[str, Any]:
        """Get volume state."""
        self._call_service(service="platform_service", action="getvolume")
        return self._wait_for_payload(
            lambda payload: isinstance(payload, dict)
            and (
                "volume_value" in payload
                or "volume_type" in payload
                or "volume" in payload
            ),
            "volume state",
        )

    def set_volume(self, volume: int) -> None:
        """Set volume from 0 to 100."""
        self._call_service(
            service="platform_service",
            action="changevolume",
            payload=str(max(0, min(100, int(volume)))),
        )

    def get_sources(self) -> list[dict[str, Any]]:
        """Get input source list."""
        self._call_service(service="ui_service", action="sourcelist")
        return self._wait_for_payload(
            lambda payload: isinstance(payload, list)
            or (
                isinstance(payload, dict)
                and any(key in payload for key in ("sources", "source_list", "sourcelist"))
            ),
            "source list",
        )

    def set_source(self, source_id: int | str, source_name: str) -> None:
        """Set input source."""
        self._call_service(
            service="ui_service",
            action="changesource",
            payload={"sourceid": str(int(source_id)), "sourcename": source_name},
        )

    def send_key(self, key_name: str) -> None:
        """Send a raw key name."""
        self._call_service(
            service="remote_service",
            action="sendkey",
            payload=key_name,
        )


def _is_successful_reason_code(reason_code: Any) -> bool:
    """Return whether a paho-mqtt v1/v2 reason code means success."""
    if reason_code == 0:
        return True
    value = getattr(reason_code, "value", None)
    if value == 0:
        return True
    name = getattr(reason_code, "name", "")
    if str(name).lower() in {"success", "connection accepted"}:
        return True
    return str(reason_code).lower() in {"0", "success", "connection accepted"}


def _message_payload(message: Any) -> Any:
    if isinstance(message, dict) and "payload" in message:
        return message["payload"]
    return message


def build_vidaa_auth_identity(mac_address: str | None = None) -> VidaaAuthIdentity:
    """Build the credentials used by the VIDAA common mobile app handshake."""
    mac = _normalise_mac_address(mac_address)
    return VidaaAuthIdentity(
        client_id=f"{mac}$vidaa_common",
        username="hisenseservice",
        password="multimqttservice",
        mac_address=mac,
    )


def _normalise_mac_address(mac_address: str | None) -> str:
    if mac_address:
        hex_digits = re.sub(r"[^0-9A-Fa-f]", "", mac_address)
    else:
        hex_digits = f"{uuid.getnode():012x}"
    if len(hex_digits) != 12:
        raise ValueError("VIDAA pairing MAC must contain 12 hex digits")
    return ":".join(
        hex_digits[index : index + 2] for index in range(0, 12, 2)
    ).upper()


def _md5_upper(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest().upper()
