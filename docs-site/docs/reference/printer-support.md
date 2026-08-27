# Printer Support Matrix

Daedal Studio is designed to integrate with major open-source printer firmware ecosystems.

| Firmware    | Print Dispatch | Telemetry | Failure Detection | Status |
|-------------|---------------|-----------|-------------------|--------|
| **OctoPrint** | Full Support | Socket.IO | Basic (Temp & Z) | Supported |
| **Klipper**   | Full Support | WebSocket | Full | Supported |
| **Bambu Lab** | Stub only | None yet | None yet | In Progress |

## Setup Instructions

### OctoPrint
To use OctoPrint, generate an Application Key in your OctoPrint web interface (Settings > API). Set this key as the `OCTOPRINT_API_KEY` in your `.env` file. Make sure your `OCTOPRINT_URL` points to your Raspberry Pi or host running OctoPrint.

### Klipper (Moonraker)
Klipper integration is handled via the Moonraker API. Provide your Moonraker IP address. Klipper provides much richer telemetry than OctoPrint, making failure detection more accurate.

### Bambu Lab
Integration with Bambu Lab's proprietary MQTT protocol is currently in development.
