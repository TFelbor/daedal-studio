# Bambu Lab MQTT Protocol

Bambu Lab printers (X1C and P1 series) expose a local MQTT broker when "LAN mode" is enabled. This document details the connection requirements and topic structures.

## Connection Details

- **Broker Address**: `<printer_ip>`
- **Port**: `8883` (MQTT over TLS)
- **Authentication Method**:
  - **Username**: `bblp`
  - **Password**: The LAN Access Code found on the printer screen.

## Cloud API vs LAN API

- **Cloud API**: Connects through Bambu Lab servers. Requires internet access.
- **LAN API**: Connects directly to the local printer. Functions entirely offline but requires "LAN Mode Liveview" to be enabled on the printer. Recent firmware updates introduced payload signing (RSA-SHA256) for commands, alongside the "Bambu Connect" authorization system.

## MQTT Topics

All topics are prefixed with the printer's serial number (`<serial>`).

| Feature | Topic | Description / Usage |
|---------|-------|---------------------|
| **Printer State** | `device/<serial>/report` | Subscribes to telemetry, temperatures, chamber status, and overall printer state. It is a "push" feed from the printer. |
| **Command Request** | `device/<serial>/request` | General topic for sending commands (requires payload with specific command structure). |
| **Print Start** | `device/<serial>/request` | Payload contains `{"print": {"command": "project_file", "param": "filename.3mf"}}` to trigger a print from the SD card. |
| **Print Cancel** | `device/<serial>/request` | Payload contains `{"print": {"command": "stop"}}` to cancel the active print job. |
| **File Upload** | `device/<serial>/request` | While MQTT is not typically used for file uploads (FTP/FTPS on port 990 is standard), some file management commands can be sent via this topic. |
