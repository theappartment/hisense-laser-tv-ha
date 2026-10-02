"""Media player platform for Hisense Laser TV."""

from __future__ import annotations

import json
import logging
import hashlib
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature

try:
    from homeassistant.components.media_player.const import MediaPlayerState
except ImportError:
    from homeassistant.const import STATE_OFF, STATE_ON

    class MediaPlayerState:
        """Compatibility fallback for older Home Assistant versions."""

        OFF = STATE_OFF
        ON = STATE_ON
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CERTFILE,
    CONF_KEYFILE,
    CONF_SSL_MODE,
    CONF_VIDAA_ACCESS_TOKEN,
    CONF_VIDAA_CLIENT_ID,
    CONF_VIDAA_USERNAME,
    DEFAULT_CERTFILE,
    DEFAULT_KEYFILE,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SSL_MODE,
    DEFAULT_TIMEOUT,
    CONF_PAIRED_UUID,
    DOMAIN,
    REMOTE_KEYS,
    SSL_MODE_AUTO,
    SSL_MODE_INSECURE,
    SSL_MODE_PLAIN,
)
from .client import (
    HisenseLaserTvAuthorizationError,
    HisenseLaserTvClient,
    MqttConnectOptions,
)
from .wake import (
    can_wake_from_standby,
    configured_mac_address,
    send_wake_packets_for_entry,
)

_LOGGER = logging.getLogger(__name__)
FEATURE_NAMES = (
    "TURN_ON",
    "TURN_OFF",
    "VOLUME_SET",
    "VOLUME_STEP",
    "VOLUME_MUTE",
    "SELECT_SOURCE",
    "PLAY",
    "PAUSE",
    "STOP",
    "SEND_COMMAND",
)


def _supported_features() -> MediaPlayerEntityFeature:
    features = MediaPlayerEntityFeature(0)
    for name in FEATURE_NAMES:
        feature = getattr(MediaPlayerEntityFeature, name, None)
        if feature is not None:
            features |= feature
    return features


@dataclass
class SourceInfo:
    """Input source metadata."""

    source_id: str
    source_name: str
    display_name: str
    has_signal: bool


def _client_ssl_context(certfile: str, keyfile: str) -> ssl.SSLContext | None:
    cert_path = _existing_cert_path(certfile)
    key_path = _existing_cert_path(keyfile)
    if cert_path is None or key_path is None:
        return None
    context = ssl._create_unverified_context()
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


def _existing_cert_path(path: str) -> str | None:
    """Return an existing cert path, accepting HA OS and HA Container layouts."""
    component_dir = Path(__file__).parent
    bundled_name = {
        "rcm_certchain_pem.cer": DEFAULT_CERTFILE,
        "rcm_pem_privkey.pkcs8": DEFAULT_KEYFILE,
    }.get(Path(path).name, path)
    candidates = [component_dir / "certs" / bundled_name, Path(path)]
    if path.startswith("/ssl/"):
        candidates.append(Path("/config") / path.removeprefix("/"))
    elif not path.startswith("/"):
        candidates.extend(
            (
                Path("/ssl") / path,
                Path("/config") / path,
                Path("/config/ssl") / path,
            )
        )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _ssl_contexts_to_try(
    certfile: str,
    keyfile: str,
    ssl_mode: str,
) -> tuple[tuple[str, ssl.SSLContext | None], ...]:
    if ssl_mode == SSL_MODE_PLAIN:
        return ((SSL_MODE_PLAIN, None),)
    if ssl_mode == SSL_MODE_INSECURE:
        return ((SSL_MODE_INSECURE, ssl._create_unverified_context()),)

    context = _client_ssl_context(certfile, keyfile)
    if context is not None:
        return (("tls_client_cert", context), (SSL_MODE_PLAIN, None))
    return ((SSL_MODE_PLAIN, None),)


def _mqtt_options_to_try() -> tuple[MqttConnectOptions, ...]:
    return (
        MqttConnectOptions(name="VIDAA-legacy-app"),
    )


def _token_mqtt_option(data: dict[str, Any]) -> MqttConnectOptions | None:
    client_id = data.get(CONF_VIDAA_CLIENT_ID)
    username = data.get(CONF_VIDAA_USERNAME)
    access_token = data.get(CONF_VIDAA_ACCESS_TOKEN)
    if not client_id or not username or not access_token:
        return None
    return MqttConnectOptions(
        name="VIDAA-token",
        client_id=client_id,
        username=username,
        password=access_token,
    )


def _device_topic_from_paired_uuid(paired_uuid: str | None) -> str | None:
    """Return the remoteapp topic suffix for a paired VIDAA app identity."""
    if paired_uuid is None:
        return None
    paired_uuid = paired_uuid.strip()
    if not paired_uuid:
        return None
    if "$" in paired_uuid:
        return paired_uuid
    return f"{paired_uuid}$vidaa_common"


def _generated_vidaa_app_id(entry: ConfigEntry) -> str:
    """Return a stable MAC-like app identity matching the legacy VIDAA client."""
    seed = f"{entry.entry_id}:{entry.data.get(CONF_HOST, '')}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()
    mac = ":".join(digest[index : index + 2] for index in range(0, 12, 2))
    return f"{mac}$vidaa_common"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hisense Laser TV media player."""
    async_add_entities([HisenseLaserTvEntity(hass, entry)], True)


class HisenseLaserTvEntity(MediaPlayerEntity):
    """Representation of a Hisense Laser TV."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = _supported_features()

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "Hisense",
            "name": entry.data.get(CONF_NAME) or DEFAULT_NAME,
            "model": "Laser TV / VIDAA",
        }

        self._tv: Any | None = None
        self._working_ssl_mode: str | None = None
        self._last_error: str | None = None
        self._available = False
        self._state = MediaPlayerState.OFF
        self._volume_level: float | None = None
        self._is_volume_muted: bool | None = None
        self._sources: list[SourceInfo] = []
        self._source: str | None = None

    @property
    def available(self) -> bool:
        """Return if the device is available."""
        return self._available

    @property
    def state(self) -> MediaPlayerState:
        """Return the media player state."""
        return self._state

    @property
    def volume_level(self) -> float | None:
        """Return the volume level from 0..1."""
        return self._volume_level

    @property
    def is_volume_muted(self) -> bool | None:
        """Return mute status."""
        return self._is_volume_muted

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        return self._source

    @property
    def source_list(self) -> list[str]:
        """Return available input sources."""
        return [source.display_name for source in self._sources]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "host": self.entry.data[CONF_HOST],
            "mac_address": configured_mac_address(self.entry) or None,
            "wifi_wake_configured": can_wake_from_standby(self.entry),
            "volume_level_percent": (
                round(self._volume_level * 100)
                if self._volume_level is not None
                else None
            ),
            "is_volume_muted": self._is_volume_muted,
            "ssl_mode": self.entry.data.get(CONF_SSL_MODE, DEFAULT_SSL_MODE),
            "certfile": self.entry.data.get(CONF_CERTFILE, DEFAULT_CERTFILE),
            "keyfile": self.entry.data.get(CONF_KEYFILE, DEFAULT_KEYFILE),
            "paired_uuid": self.entry.data.get(CONF_PAIRED_UUID) or None,
            "vidaa_client_id": (
                self.entry.data.get(CONF_VIDAA_CLIENT_ID)
                or self.entry.data.get(CONF_PAIRED_UUID)
                or _generated_vidaa_app_id(self.entry)
            ),
            "vidaa_token_configured": bool(self.entry.data.get(CONF_VIDAA_ACCESS_TOKEN)),
            "working_ssl_mode": self._working_ssl_mode,
            "last_error": self._last_error,
            "client_version": "0.5.0",
        }

    def _create_tv(
        self,
        ssl_context: ssl.SSLContext | None,
        options: MqttConnectOptions,
    ) -> Any:
        """Create the synchronous API client."""
        configured_identity = (
            self.entry.data.get(CONF_VIDAA_CLIENT_ID)
            or self.entry.data.get(CONF_PAIRED_UUID)
            or ""
        ).strip()
        paired_uuid = configured_identity or _generated_vidaa_app_id(self.entry)
        device_topic = _device_topic_from_paired_uuid(paired_uuid) or paired_uuid
        return HisenseLaserTvClient(
            self.entry.data[CONF_HOST],
            port=self.entry.data.get(CONF_PORT, DEFAULT_PORT),
            timeout=min(2, self.entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
            ssl_context=ssl_context,
            client_id=paired_uuid or options.client_id,
            device_topic=device_topic,
            username=options.username,
            password=options.password,
            protocol=options.protocol,
        )

    def _connection_options_to_try(
        self,
    ) -> tuple[tuple[str, ssl.SSLContext | None, MqttConnectOptions], ...]:
        certfile = self.entry.data.get(CONF_CERTFILE, DEFAULT_CERTFILE)
        keyfile = self.entry.data.get(CONF_KEYFILE, DEFAULT_KEYFILE)
        configured_ssl_mode = self.entry.data.get(CONF_SSL_MODE, DEFAULT_SSL_MODE)
        token_option = _token_mqtt_option(self.entry.data)
        mqtt_options_to_try = (
            (token_option,) if token_option is not None else _mqtt_options_to_try()
        )
        options = [
            (f"{mode}:{mqtt_options.name}", ssl_context, mqtt_options)
            for mode, ssl_context in _ssl_contexts_to_try(
                certfile, keyfile, configured_ssl_mode
            )
            for mqtt_options in mqtt_options_to_try
        ]
        if self._working_ssl_mode is not None:
            options.sort(key=lambda item: item[0] != self._working_ssl_mode)
        return tuple(options)

    def _get_tv(self) -> Any:
        """Create the synchronous API client lazily."""
        if self._tv is None:
            mode, context, options = self._connection_options_to_try()[0]
            self._tv = self._create_tv(context, options)
            self._tv.connect()
            self._working_ssl_mode = mode
        return self._tv

    async def async_will_remove_from_hass(self) -> None:
        """Close the TV connection when Home Assistant removes the entity."""
        if self._tv is not None:
            await self.hass.async_add_executor_job(self._tv.disconnect)
        self._tv = None

    async def async_update(self) -> None:
        """Fetch state from the projector."""
        try:
            await self.hass.async_add_executor_job(self._sync_update)
        except Exception as err:
            self._last_error = f"{type(err).__name__}: {err}"
            _LOGGER.warning("Hisense Laser TV update failed: %s", self._last_error)
            self._available = can_wake_from_standby(self.entry)
            self._state = MediaPlayerState.OFF
            self._volume_level = None
            self._is_volume_muted = None

    def _sync_update(self) -> None:
        last_error: Exception | None = None
        for ssl_mode, ssl_context, options in self._connection_options_to_try():
            try:
                if self._tv is None or self._working_ssl_mode != ssl_mode:
                    self._tv = self._create_tv(ssl_context, options)
                    self._tv.connect()
                    self._tv.initialise_vidaa_1140()
                volume = self._tv.get_volume()
                sources = self._tv.get_sources()
                self._working_ssl_mode = ssl_mode
                break
            except Exception as err:
                last_error = err
                if self._tv is not None:
                    self._tv.disconnect()
                self._tv = None
                if isinstance(err, HisenseLaserTvAuthorizationError):
                    raise RuntimeError(
                        "TV rejected MQTT authorization. This firmware requires "
                        "valid VIDAA mobile app credentials or a paired app ID."
                    ) from err
        else:
            certfile = self.entry.data.get(CONF_CERTFILE, DEFAULT_CERTFILE)
            keyfile = self.entry.data.get(CONF_KEYFILE, DEFAULT_KEYFILE)
            if _existing_cert_path(certfile) is None or _existing_cert_path(keyfile) is None:
                raise RuntimeError(
                    "Could not connect with plain MQTT and TLS client certificate "
                    f"files were not found at {certfile!r}/{('/config' + certfile) if certfile.startswith('/ssl/') else certfile!r} "
                    f"and {keyfile!r}/{('/config' + keyfile) if keyfile.startswith('/ssl/') else keyfile!r}"
                ) from last_error
            if last_error is not None:
                raise last_error
            raise RuntimeError("Could not connect to Hisense Laser TV")

        self._volume_level = _parse_volume(volume)
        self._is_volume_muted = _parse_muted(volume)
        self._sources = _parse_sources(sources)
        self._source = _best_current_source(self._sources, self._source)
        self._last_error = None
        self._available = True
        self._state = MediaPlayerState.ON

    async def async_turn_on(self) -> None:
        """Turn on the projector."""
        mac_address = configured_mac_address(self.entry)
        if mac_address:
            await self.hass.async_add_executor_job(
                send_wake_packets_for_entry,
                self.entry,
            )
            self._available = True
            self._state = MediaPlayerState.ON
            return
        await self._send_remote_key("power")
        self._available = True
        self._state = MediaPlayerState.ON

    async def async_turn_off(self) -> None:
        """Turn off the projector."""
        await self._send_remote_key("power")
        self._state = MediaPlayerState.OFF

    async def async_media_play(self) -> None:
        """Send play."""
        await self._send_remote_key("play")

    async def async_media_pause(self) -> None:
        """Send pause."""
        await self._send_remote_key("pause")

    async def async_media_stop(self) -> None:
        """Send stop."""
        await self._send_remote_key("stop")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level."""
        level = max(0, min(100, round(volume * 100)))
        await self.hass.async_add_executor_job(self._get_tv().set_volume, level)
        self._volume_level = level / 100

    async def async_volume_up(self) -> None:
        """Volume up."""
        await self._send_remote_key("volume_up")

    async def async_volume_down(self) -> None:
        """Volume down."""
        await self._send_remote_key("volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute volume."""
        if self._is_volume_muted is None or self._is_volume_muted != mute:
            await self._send_remote_key("mute")
        self._is_volume_muted = mute

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        source_info = next(
            (item for item in self._sources if item.display_name == source),
            None,
        )
        if source_info is None:
            raise ValueError(f"Unknown source: {source}")

        await self.hass.async_add_executor_job(
            self._get_tv().set_source,
            source_info.source_id,
            source_info.source_name,
        )
        self._source = source_info.display_name

    async def async_send_command(self, command: list[str], **kwargs: Any) -> None:
        """Send remote commands to the projector."""
        for item in command:
            key = item.lower().replace(" ", "_")
            if key not in REMOTE_KEYS:
                raise ValueError(f"Unsupported command: {item}")
            await self._send_remote_key(key)

    async def _send_remote_key(self, key: str) -> None:
        key_name = REMOTE_KEYS[key]
        await self.hass.async_add_executor_job(self._get_tv().send_key, key_name)


def _parse_volume(volume: dict[str, Any]) -> float | None:
    raw_volume = _find_payload_value(
        volume,
        (
            "volume_value",
            "volumevalue",
            "volume",
            "vol",
            "volume_level",
            "volumelevel",
            "current_volume",
            "currentvolume",
        ),
    )
    if raw_volume is None:
        return None
    if isinstance(raw_volume, dict):
        raw_volume = _find_payload_value(raw_volume, ("value", "level", "current"))
    if isinstance(raw_volume, str) and raw_volume.strip().endswith("%"):
        raw_volume = raw_volume.strip()[:-1]
    try:
        parsed = float(raw_volume)
    except (TypeError, ValueError):
        return None
    if 0 <= parsed <= 1:
        return parsed
    return max(0, min(100, parsed)) / 100


def _parse_muted(volume: dict[str, Any]) -> bool | None:
    raw_type = _find_payload_value(
        volume,
        ("volume_type", "volumetype", "mute", "muted", "is_mute", "ismute"),
    )
    if raw_type is None:
        return None
    if isinstance(raw_type, bool):
        return raw_type
    return str(raw_type).strip().lower() in {"1", "true", "yes", "on", "muted"}


def _find_payload_value(payload: Any, keys: tuple[str, ...]) -> Any:
    """Find the first matching value in a nested VIDAA payload."""
    normalised_keys = {_normalise_payload_key(key) for key in keys}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _normalise_payload_key(key) in normalised_keys:
                return value
        for value in payload.values():
            found = _find_payload_value(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_payload_value(value, keys)
            if found is not None:
                return found
    return None


def _normalise_payload_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _parse_sources(sources: list[dict[str, Any]]) -> list[SourceInfo]:
    if isinstance(sources, dict):
        for key in ("sources", "source_list", "sourcelist"):
            value = sources.get(key)
            if isinstance(value, list):
                sources = value
                break
        else:
            sources = []

    parsed: list[SourceInfo] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("sourceid", ""))
        source_name = str(source.get("sourcename") or source.get("displayname") or "")
        display_name = str(source.get("displayname") or source_name)
        if not source_id or not source_name or not display_name:
            continue
        parsed.append(
            SourceInfo(
                source_id=source_id,
                source_name=source_name,
                display_name=display_name,
                has_signal=str(source.get("is_signal", "0")).lower() in {"1", "true"},
            )
        )
    return parsed


def _best_current_source(
    sources: list[SourceInfo], previous_source: str | None
) -> str | None:
    signalled = next((source for source in sources if source.has_signal), None)
    if signalled is not None:
        return signalled.display_name
    if previous_source in {source.display_name for source in sources}:
        return previous_source
    if sources:
        return sources[0].display_name
    return None
