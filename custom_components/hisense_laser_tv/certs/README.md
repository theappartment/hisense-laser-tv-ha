# Certificate files

Place local VIDAA/RemoteNOW client certificate files here if you want the
integration to load them from the custom component directory:

- `remoteclientmobile.crt`
- `remoteclientmobile.key`

These files are intentionally not committed to the public repository because
they contain certificate/private-key material extracted from mobile apps.

Home Assistant also accepts the same files in:

- `/ssl/remoteclientmobile.crt`
- `/ssl/remoteclientmobile.key`
- `/config/ssl/remoteclientmobile.crt`
- `/config/ssl/remoteclientmobile.key`
