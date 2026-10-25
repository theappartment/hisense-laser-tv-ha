![Hisense Laser TV Home Assistant HACS cover](assets/cover.png)

# Hisense Laser TV for Home Assistant

Custom Home Assistant integration for local control of Hisense Laser TV / VIDAA
projectors over the device MQTT control port.

Tested with:

- Hisense `HE100L5` Laser TV on firmware `V0000.01.00L.P0301`, transport
  protocol `1140` — newer VIDAA, uses PIN pairing.
- Hisense `49P4` (P-series LCD) — older VIDAA, uses the hardcoded service
  credentials over plain MQTT, no pairing or TLS certificate required.

The integration auto-detects which path your TV supports: it first attempts a
plain connection with the built-in service credentials and only falls back to
PIN pairing if the TV rejects authorization. Legacy TLS client certificates
are only needed for firmware that refuses plain MQTT.

## Features

- Local MQTT control on port `36669`
- Config flow from the Home Assistant UI
- SSDP discovery plus manual network scan
- VIDAA legacy-app pairing flow with PIN entry
- Power, volume, mute, source selection, play, pause, stop
- Wake-on-LAN and VIDAA Android-app wake packet support when a MAC address is configured
- Dedicated `Accendi tramite Wi-Fi` button entity for dashboards
- Extra remote keys through `media_player.send_command` when available

## Install

### HACS custom repository

1. Open HACS in Home Assistant.
2. Open the menu in the top right and choose **Custom repositories**.
3. Add this repository URL:

```text
https://github.com/theappartment/hisense-laser-tv-ha
```

4. Choose category **Integration**.
5. Install **Hisense Laser TV**.
6. Restart Home Assistant.
7. Go to **Settings > Devices & services > Add integration > Hisense Laser TV**.

### Manual install

Copy this folder into Home Assistant:

```text
custom_components/hisense_laser_tv
```

The final path must be:

```text
/config/custom_components/hisense_laser_tv
```

Restart Home Assistant, then go to:

```text
Settings > Devices & services > Add integration > Hisense Laser TV
```

## Wake from standby

When a MAC address is configured, `turn_on` sends both:

- a standard Wake-on-LAN magic packet
- the legacy VIDAA Android app wake packet on UDP broadcast port `33129`

The VIDAA packet is sent five times, 100 ms apart, matching the behavior found
in the Android app. Wi-Fi wake support still depends on projector firmware,
network standby settings, and router/access point broadcast handling.

The Wi-Fi MAC can also be added or corrected after setup from:

```text
Settings > Devices & services > Hisense Laser TV > Configure
```

Use the MAC address of the active Wi-Fi interface, not the Ethernet MAC. The TV
must also have network wake, wake on wireless network, or fast start enabled.

### After a mains power cycle

On older VIDAA sets (confirmed on the 49P4), the "Fast Start" / "Wake on
Wireless Network" settings only apply to standby that was entered **from
an on state**. After the TV has been fully switched off at the wall, it
boots into a deep standby where the Wi-Fi radio is not powered. In that
state WOL packets are not received and Home Assistant cannot wake the TV
over the network — regardless of what the integration sends.

The TV must be powered on at least once with the physical remote after a
mains cycle. From that point on, soft standby works normally and
Home Assistant can wake it. Until that first manual power-on happens, the
entity will stay unavailable and the log will show a single
`OSError: [Errno 113] Host is unreachable` warning (repeated poll failures
are suppressed and only logged at debug level).

## Dashboard card

Version `0.5.0` includes the **Hisense Laser TV** dashboard card. The integration
registers it automatically after Home Assistant restarts; no Lovelace resource
needs to be added manually.

In dashboard edit mode, choose **Add card**, search for **Hisense Laser TV**, and
select the TV entity. The Wi-Fi wake button is found automatically, or it can be
selected explicitly in the visual card editor.

The card provides:

- power on through the configured Wi-Fi MAC and power off
- current volume, mute, and a direct volume slider
- horizontal quick selection for every input reported by the TV
- clear offline and missing Wi-Fi MAC states

Equivalent YAML configuration:

```yaml
type: custom:hisense-laser-tv-card
entity: media_player.hisense_laser_tv
wake_button: button.hisense_laser_tv_accendi_tramite_wi_fi
```

## Pairing

Pairing is only used when the TV firmware refuses the built-in service
credentials. The integration always tries a plain connection first; older
VIDAA sets (e.g. the P-series) complete setup without any PIN prompt. Newer
VIDAA firmware will reject the plain connection, at which point the
integration starts the PIN pairing flow automatically.

During setup, keep the projector powered on and on the VIDAA home screen.

1. Add the integration in Home Assistant.
2. Enter the projector IP address or use discovery/scan.
3. If the projector shows a PIN, enter it in the Home Assistant pairing
   field. If no PIN appears and setup completes, your TV didn't need pairing.
4. Home Assistant stores any paired VIDAA app identity in the config entry.

If the entity is created but remains unavailable, open Home Assistant logs and
look for `custom_components.hisense_laser_tv`.

## Certificates

Most tested models work with plain MQTT and do **not** need the legacy TLS
client certificate. Only some VIDAA/RemoteNOW firmware refuses plain
connections and requires the legacy mobile-app TLS client certificate. If
your TV falls into that group, provide the files below; otherwise skip this
section. This repository does not ship private-key material.

The integration looks for these files:

```text
remoteclientmobile.crt
remoteclientmobile.key
```

Supported locations:

```text
/ssl/remoteclientmobile.crt
/ssl/remoteclientmobile.key
/config/ssl/remoteclientmobile.crt
/config/ssl/remoteclientmobile.key
/config/custom_components/hisense_laser_tv/certs/remoteclientmobile.crt
/config/custom_components/hisense_laser_tv/certs/remoteclientmobile.key
```

For personal use, these can be extracted from a compatible legacy VIDAA /
RemoteNOW Android APK. With OpenSSL 3, legacy PKCS#12 files may need the
`-legacy` flag:

```bash
openssl pkcs12 -legacy -in remoteclientmobile.p12 -clcerts -nokeys \
  -out remoteclientmobile.crt -passin pass:multiscreen123

openssl pkcs12 -legacy -in remoteclientmobile.p12 -nocerts -nodes \
  -out remoteclientmobile.key -passin pass:multiscreen123
```

Only use certificate files you are legally allowed to use.

For the most convenient Home Assistant setup, put the files in:

```text
/config/ssl/remoteclientmobile.crt
/config/ssl/remoteclientmobile.key
```

Then leave the certificate fields at their default values during setup.

## Discovery

Automatic discovery uses SSDP/UPnP. It works when Home Assistant and the
projector are on the same network and Home Assistant can receive multicast
traffic.

If SSDP does not show the projector:

1. Choose **Add integration > Hisense Laser TV**.
2. Choose **Scan local network**.
3. Enter a CIDR such as `192.168.1.0/24`.

The scan checks for the local VIDAA MQTT port `36669`.

## Notes

This is an unofficial integration. Hisense/VIDAA does not publish this local
MQTT API as a stable public API, so firmware differences are expected.

The integration was created because older Python libraries for Hisense TVs
depend on `paho-mqtt` versions that conflict with modern Home Assistant.
