"""Config flow for Hisense Laser TV."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

from .const import (
    CONF_CERTFILE,
    CONF_MAC_ADDRESS,
    CONF_KEYFILE,
    CONF_SSL_MODE,
    CONF_VIDAA_ACCESS_TOKEN,
    CONF_VIDAA_ACCESS_TOKEN_DURATION,
    CONF_VIDAA_ACCESS_TOKEN_TIME,
    CONF_VIDAA_CLIENT_ID,
    CONF_VIDAA_REFRESH_TOKEN,
    CONF_VIDAA_REFRESH_TOKEN_DURATION,
    CONF_VIDAA_REFRESH_TOKEN_TIME,
    CONF_VIDAA_USERNAME,
    DEFAULT_CERTFILE,
    DEFAULT_KEYFILE,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SSL_MODE,
    DEFAULT_TIMEOUT,
    CONF_PAIRED_UUID,
    DOMAIN,
    SSL_MODE_AUTO,
    SSL_MODE_INSECURE,
    SSL_MODE_PLAIN,
    SUPPORTED_SSL_MODES,
)
from .client import (
    HisenseLaserTvAuthorizationError,
    HisenseLaserTvClient,
    MqttConnectOptions,
    VidaaAuthIdentity,
    build_vidaa_auth_identity,
)


DISCOVERY_KEYS = (
    "friendlyName",
    "friendly_name",
    "modelName",
    "model_name",
    "modelNumber",
    "model_number",
    "manufacturer",
)
DEFAULT_SCAN_CIDR = "192.168.1.0/24"
CONF_SCAN_CIDR = "scan_cidr"
CONF_SELECTED_HOST = "selected_host"
CONF_PAIRING_CODE = "pairing_code"


def _client_ssl_context(data: dict[str, Any]) -> ssl.SSLContext | None:
    certfile = data.get(CONF_CERTFILE) or DEFAULT_CERTFILE
    keyfile = data.get(CONF_KEYFILE) or DEFAULT_KEYFILE
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


def _ssl_contexts_to_try(data: dict[str, Any]) -> tuple[ssl.SSLContext | None, ...]:
    context = _client_ssl_context(data)
    if context is not None:
        return (context, None)
    return (None,)


def _mqtt_options_to_try() -> tuple[MqttConnectOptions, ...]:
    return (
        MqttConnectOptions(name="VIDAA-legacy-app"),
    )


def _create_entry(flow: config_entries.ConfigFlow, data: dict[str, Any]) -> FlowResult:
    """Create a config entry using the configured friendly name."""
    title = data.get(CONF_NAME) or DEFAULT_NAME
    return flow.async_create_entry(title=title, data=data)


async def _begin_pairing_flow(
    flow: "HisenseLaserTvConfigFlow",
    data: dict[str, Any],
    errors: dict[str, str],
) -> FlowResult | None:
    """Start pairing and move to the code entry step."""
    try:
        tv, identity = await _start_pairing(flow.hass, data)
    except Exception:
        errors["base"] = "cannot_connect"
        return None

    flow._pairing_data = data
    flow._pairing_identity = identity
    flow._pairing_tv = tv
    return await flow.async_step_pair()


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


async def _can_connect(hass: HomeAssistant, data: dict[str, Any]) -> bool:
    """Check if the TV accepts a basic API request."""
    def test_connection() -> bool:
        last_error: Exception | None = None
        paired_uuid = (data.get(CONF_PAIRED_UUID) or "").strip()
        device_topic = _device_topic_from_paired_uuid(paired_uuid)
        token_option = _token_mqtt_option(data)
        mqtt_options = (token_option,) if token_option is not None else _mqtt_options_to_try()
        for ssl_context in _ssl_contexts_to_try(data):
            for options in mqtt_options:
                tv: Any | None = None
                try:
                    tv = HisenseLaserTvClient(
                        data[CONF_HOST],
                        port=data[CONF_PORT],
                        timeout=data[CONF_TIMEOUT],
                        ssl_context=ssl_context,
                        client_id=paired_uuid or options.client_id,
                        device_topic=device_topic,
                        username=options.username,
                        password=options.password,
                        protocol=options.protocol,
                    )
                    tv.connect()
                    tv.get_volume()
                    return True
                except Exception as err:
                    last_error = err
                    if isinstance(err, HisenseLaserTvAuthorizationError):
                        raise err
                finally:
                    if tv is not None:
                        tv.disconnect()
        if last_error is not None:
            raise last_error
        return True

    return await hass.async_add_executor_job(test_connection)


async def _start_pairing(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> tuple[HisenseLaserTvClient, VidaaAuthIdentity]:
    """Start VIDAA mobile-app pairing and keep the MQTT session open."""

    def start() -> tuple[HisenseLaserTvClient, VidaaAuthIdentity]:
        identity = build_vidaa_auth_identity(data.get(CONF_PAIRED_UUID))
        last_error: Exception | None = None
        for ssl_context in _ssl_contexts_to_try(data):
            tv = HisenseLaserTvClient(
                data[CONF_HOST],
                port=data[CONF_PORT],
                timeout=data[CONF_TIMEOUT],
                ssl_context=ssl_context,
                client_id=identity.client_id,
                device_topic=identity.client_id,
                username=identity.username,
                password=identity.password,
            )
            try:
                tv.connect()
                tv.start_vidaa_pairing()
                return tv, identity
            except Exception as err:
                last_error = err
                tv.disconnect()
        if last_error is not None:
            raise last_error
        raise HisenseLaserTvAuthorizationError("VIDAA pairing could not start")

    return await hass.async_add_executor_job(start)


async def _finish_pairing(
    hass: HomeAssistant,
    tv: HisenseLaserTvClient,
    identity: VidaaAuthIdentity,
    code: str,
) -> dict[str, Any]:
    """Finish VIDAA pairing and return config-entry token data."""

    def finish() -> dict[str, Any]:
        try:
            token_data = tv.finish_vidaa_pairing(code)
            return {
                CONF_PAIRED_UUID: identity.client_id,
                CONF_VIDAA_CLIENT_ID: identity.client_id,
                CONF_VIDAA_USERNAME: identity.username,
                CONF_VIDAA_ACCESS_TOKEN: token_data.get("accesstoken", ""),
                CONF_VIDAA_ACCESS_TOKEN_TIME: token_data.get("accesstoken_time", ""),
                CONF_VIDAA_ACCESS_TOKEN_DURATION: token_data.get(
                    "accesstoken_duration_day", ""
                ),
                CONF_VIDAA_REFRESH_TOKEN: token_data.get("refreshtoken", ""),
                CONF_VIDAA_REFRESH_TOKEN_TIME: token_data.get("refreshtoken_time", ""),
                CONF_VIDAA_REFRESH_TOKEN_DURATION: token_data.get(
                    "refreshtoken_duration_day", ""
                ),
            }
        finally:
            tv.disconnect()

    return await hass.async_add_executor_job(finish)


async def _can_open_port(host: str, port: int, timeout: float) -> bool:
    """Return if a TCP port can be opened."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except (OSError, TimeoutError, asyncio.TimeoutError):
        return False
    writer.close()
    await writer.wait_closed()
    return True


async def _scan_hosts(cidr: str, port: int) -> list[str]:
    """Scan a local CIDR for devices exposing the Hisense control port."""
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(host) for host in network.hosts()]
    semaphore = asyncio.Semaphore(64)

    async def check_host(host: str) -> str | None:
        async with semaphore:
            if await _can_open_port(host, port, 0.45):
                return host
            return None

    results = await asyncio.gather(*(check_host(host) for host in hosts))
    return sorted(host for host in results if host is not None)


def _entry_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(
                CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
            ): str,
            vol.Optional(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): int,
            vol.Optional(
                CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): int,
            vol.Optional(
                CONF_MAC_ADDRESS,
                default=defaults.get(CONF_MAC_ADDRESS, ""),
            ): str,
            vol.Optional(
                CONF_PAIRED_UUID,
                default=defaults.get(CONF_PAIRED_UUID, ""),
            ): str,
            vol.Optional(
                CONF_CERTFILE,
                default=defaults.get(CONF_CERTFILE, DEFAULT_CERTFILE),
            ): str,
            vol.Optional(
                CONF_KEYFILE,
                default=defaults.get(CONF_KEYFILE, DEFAULT_KEYFILE),
            ): str,
            vol.Optional(
                CONF_SSL_MODE,
                default=defaults.get(CONF_SSL_MODE, DEFAULT_SSL_MODE),
            ): vol.In(SUPPORTED_SSL_MODES),
        }
    )


def _discovery_host(discovery_info: SsdpServiceInfo) -> str | None:
    upnp = discovery_info.upnp or {}
    location = getattr(discovery_info, "ssdp_location", None)
    if not location:
        location = upnp.get("ssdp_location")
    if not location:
        return None
    return urlparse(location).hostname


def _discovery_name(discovery_info: SsdpServiceInfo) -> str:
    upnp = discovery_info.upnp or {}
    for key in DISCOVERY_KEYS:
        value = upnp.get(key)
        if value:
            return str(value)
    return DEFAULT_NAME


def _discovery_mac(discovery_info: SsdpServiceInfo) -> str:
    """Return the best MAC address exposed in the UPnP model description."""
    upnp = discovery_info.upnp or {}
    haystack = "\n".join(str(value) for value in upnp.values() if value)
    for key in ("macWifi", "macEthernet", "mac"):
        match = re.search(rf"{key}=([0-9A-Fa-f:]+)", haystack)
        if match:
            return _format_mac_address(match.group(1))
    return ""


def _format_mac_address(mac_address: str) -> str:
    hex_digits = re.sub(r"[^0-9A-Fa-f]", "", mac_address)
    if len(hex_digits) != 12:
        return mac_address
    return ":".join(hex_digits[index : index + 2] for index in range(0, 12, 2))


def _discovery_unique_id(discovery_info: SsdpServiceInfo, host: str) -> str:
    upnp = discovery_info.upnp or {}
    udn = getattr(discovery_info, "ssdp_udn", None)
    if udn:
        return str(udn)
    for key in ("UDN", "udn", "serialNumber", "serial_number"):
        value = upnp.get(key)
        if value:
            return str(value)
    return host


class HisenseLaserTvConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hisense Laser TV."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_data: dict[str, Any] | None = None
        self._pairing_data: dict[str, Any] | None = None
        self._pairing_identity: VidaaAuthIdentity | None = None
        self._pairing_tv: HisenseLaserTvClient | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show setup options."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["manual", "scan"],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            result = await _begin_pairing_flow(self, user_input, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="manual",
            data_schema=_entry_schema(),
            errors=errors,
        )

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Scan the local network for projectors."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cidr = user_input[CONF_SCAN_CIDR]
            port = user_input[CONF_PORT]
            try:
                hosts = await _scan_hosts(cidr, port)
            except ValueError:
                errors[CONF_SCAN_CIDR] = "invalid_cidr"
            else:
                if not hosts:
                    errors["base"] = "no_devices_found"
                elif len(hosts) == 1:
                    self._discovered_data = {
                        CONF_HOST: hosts[0],
                        CONF_NAME: DEFAULT_NAME,
                        CONF_PORT: port,
                        CONF_TIMEOUT: DEFAULT_TIMEOUT,
                        CONF_MAC_ADDRESS: "",
                        CONF_PAIRED_UUID: "",
                        CONF_SSL_MODE: DEFAULT_SSL_MODE,
                    }
                    return await self.async_step_discovery_confirm()
                else:
                    self._discovered_data = {
                        "hosts": hosts,
                        CONF_PORT: port,
                    }
                    return await self.async_step_scan_select()

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_CIDR, default=DEFAULT_SCAN_CIDR): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_scan_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select one host from scan results."""
        if self._discovered_data is None or "hosts" not in self._discovered_data:
            return self.async_abort(reason="unknown_discovery")

        hosts = self._discovered_data["hosts"]
        port = self._discovered_data[CONF_PORT]
        if user_input is not None:
            host = user_input[CONF_SELECTED_HOST]
            self._discovered_data = {
                CONF_HOST: host,
                CONF_NAME: DEFAULT_NAME,
                CONF_PORT: port,
                CONF_TIMEOUT: DEFAULT_TIMEOUT,
                CONF_MAC_ADDRESS: "",
                CONF_PAIRED_UUID: "",
                CONF_SSL_MODE: DEFAULT_SSL_MODE,
            }
            return await self.async_step_discovery_confirm()

        return self.async_show_form(
            step_id="scan_select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED_HOST): vol.In(hosts),
                }
            ),
        )

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> FlowResult:
        """Handle SSDP discovery."""
        host = _discovery_host(discovery_info)
        if host is None:
            return self.async_abort(reason="unknown_discovery")

        unique_id = _discovery_unique_id(discovery_info, host)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_data = {
            CONF_HOST: host,
            CONF_NAME: _discovery_name(discovery_info),
            CONF_PORT: DEFAULT_PORT,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
            CONF_MAC_ADDRESS: _discovery_mac(discovery_info),
            CONF_PAIRED_UUID: "",
            CONF_SSL_MODE: DEFAULT_SSL_MODE,
        }

        self.context["title_placeholders"] = {
            "name": self._discovered_data[CONF_NAME],
            "host": host,
        }
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm a discovered projector."""
        if self._discovered_data is None:
            return self.async_abort(reason="unknown_discovery")

        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._discovered_data, **user_input}
            result = await _begin_pairing_flow(self, data, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=_entry_schema(self._discovered_data),
            errors=errors,
            description_placeholders={
                "name": self._discovered_data[CONF_NAME],
                "host": self._discovered_data[CONF_HOST],
            },
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish VIDAA app-style pairing."""
        if (
            self._pairing_data is None
            or self._pairing_identity is None
            or self._pairing_tv is None
        ):
            return self.async_abort(reason="unknown_discovery")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                token_data = await _finish_pairing(
                    self.hass,
                    self._pairing_tv,
                    self._pairing_identity,
                    user_input[CONF_PAIRING_CODE],
                )
            except Exception:
                errors["base"] = "pairing_failed"
            else:
                data = {**self._pairing_data, **token_data}
                return _create_entry(self, data)

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required(CONF_PAIRING_CODE): str}),
            errors=errors,
        )
