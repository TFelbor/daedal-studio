# Telemetry Collection

To ensure your prints succeed safely, Prompt2Print continuously collects telemetry data from your printer while a job is active.

## What We Collect

Data is streamed via WebSockets or Socket.IO directly from your printer firmware and stored locally in a SQLite database (`/app/telemetry/telemetry.db`). We collect:

- **Hotend Temperature**: Actual and target temperatures of the extruder.
- **Bed Temperature**: Actual and target temperatures of the heated bed.
- **Z-Height**: The current physical height of the nozzle.
- **Progress**: Job completion percentage.
- **Current G-code Line**: The active command being executed (if supported by firmware).

## Privacy Guarantee

Because Prompt2Print is fully local, your telemetry data **never leaves your machine**. It is used exclusively to power the Web UI dashboard and run failure detection heuristics.
