# Hisense Laser TV

Local Home Assistant integration for Hisense Laser TV / VIDAA projectors.

## Highlights

- Local MQTT control on port `36669`
- VIDAA legacy pairing with PIN entry
- SSDP discovery and local network scan
- Power, volume, mute, source selection, play, pause, stop
- Wake-on-LAN when a MAC address is configured

## Before installing

Some VIDAA/RemoteNOW firmware requires legacy mobile-app TLS certificate files:

- `remoteclientmobile.crt`
- `remoteclientmobile.key`

This public repository does not bundle private-key material. See the README for
supported certificate locations and extraction notes.
