# Printer Setup

Connecting your 3D printer to Daedal Studio allows the system to automatically slice files for your specific bed size and dispatch them directly for printing.

## Connecting OctoPrint

1. Obtain your **Global API Key** from OctoPrint (Settings > API).
2. Open your `.env` file in the project root.
3. Set `OCTOPRINT_URL` to your OctoPrint URL (e.g., `http://192.168.1.100:5001`). If OctoPrint is running on the same Mac/Windows host, use `http://host.docker.internal:5001`.
4. Set `OCTOPRINT_API_KEY` to your generated key.

## Connecting Klipper / Moonraker

If you use Klipper with the Moonraker API, you can connect it using the built-in Moonraker operator.
1. Update your `.env` file with your Moonraker IP address.
2. Ensure your Klipper instance is in a "ready" state before dispatching prints.

## The token the app asks for

The first time you open Daedal Studio it asks for an **API token**. Every route but
the healthcheck needs it: dispatching a print heats a nozzle for hours, a hosted
generation spends EUR 0,32, and the settings page holds your printer credentials.

There is one token for the whole server — no accounts, no sign-up. Set `DS_API_TOKEN`
in `.env` if you want to choose it; leave it blank and the server makes one on first
start and writes it to `~/.ds-mvp/.api_token`. Either way:

```bash
make api-token     # prints the token this machine's server is checking
```

Paste it into the box. The browser remembers it; Settings → **04 Developer** can
reveal, replace or forget it.

## Where the app itself is reachable

Daedal Studio serves its UI on **`http://127.0.0.1:8000`** — the machine running it,
and nowhere else. The published port is bound to loopback by default; the token says
who may act, and the bind address says who may try.

This is the *inbound* direction only. A printer on your LAN, OctoPrint on another
host and Moonraker on a Raspberry Pi are all connections the server opens outbound,
and none of them are affected — `OCTOPRINT_URL` keeps working exactly as set above.

To reach the UI from another machine, set `DS_API_BIND` in `.env` (`0.0.0.0`, or a
single LAN address) and restart the server. The token is not TLS, so on a network you
do not trust an SSH tunnel is still the safer route. See §7 of
`docs/README-docker.md`.

## Setup Wizard (Coming Soon)
A UI-based wizard is in development to help you auto-detect firmware, select standard printer profiles (e.g., Ender 3, Prusa), and perform pre-flight connectivity tests.
