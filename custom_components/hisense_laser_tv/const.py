"""Constants for the Hisense Laser TV integration."""

DOMAIN = "hisense_laser_tv"

CONF_SSL_MODE = "ssl_mode"
CONF_MAC_ADDRESS = "mac_address"
CONF_CERTFILE = "certfile"
CONF_KEYFILE = "keyfile"
CONF_PAIRED_UUID = "paired_uuid"
CONF_VIDAA_ACCESS_TOKEN = "vidaa_access_token"
CONF_VIDAA_ACCESS_TOKEN_TIME = "vidaa_access_token_time"
CONF_VIDAA_ACCESS_TOKEN_DURATION = "vidaa_access_token_duration_day"
CONF_VIDAA_CLIENT_ID = "vidaa_client_id"
CONF_VIDAA_REFRESH_TOKEN = "vidaa_refresh_token"
CONF_VIDAA_REFRESH_TOKEN_TIME = "vidaa_refresh_token_time"
CONF_VIDAA_REFRESH_TOKEN_DURATION = "vidaa_refresh_token_duration_day"
CONF_VIDAA_USERNAME = "vidaa_username"

DEFAULT_NAME = "Hisense Laser TV"
DEFAULT_PORT = 36669
DEFAULT_TIMEOUT = 8
DEFAULT_SSL_MODE = "auto"
DEFAULT_CERTFILE = "remoteclientmobile.crt"
DEFAULT_KEYFILE = "remoteclientmobile.key"

SSL_MODE_AUTO = "auto"
SSL_MODE_PLAIN = "plain"
SSL_MODE_INSECURE = "insecure"

SUPPORTED_SSL_MODES = {
    SSL_MODE_AUTO: "Auto",
    SSL_MODE_PLAIN: "Plain MQTT",
    SSL_MODE_INSECURE: "TLS without certificate verification",
}

REMOTE_KEYS = {
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "ok": "KEY_OK",
    "back": "KEY_RETURNS",
    "home": "KEY_HOME",
    "menu": "KEY_MENU",
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
    "power": "KEY_POWER",
    "mute": "KEY_MUTE",
    "volume_up": "KEY_VOLUMEUP",
    "volume_down": "KEY_VOLUMEDOWN",
    "channel_up": "KEY_CHANNELUP",
    "channel_down": "KEY_CHANNELDOWN",
    "netflix": "netflix",
    "youtube": "youtube",
    "amazon": "amazon",
}
