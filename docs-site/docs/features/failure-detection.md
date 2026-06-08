# Failure Detection

3D printing can sometimes go wrong. Prompt2Print uses real-time telemetry from your printer to catch failures before they cause hardware damage or waste significant material.

## How it Works
The system continuously analyzes telemetry data against a set of four predefined heuristics. If a rule is triggered, the system flags an anomaly.

If you have configured `PAUSE_ON_FAILURE=true` in your `.env` file, the system will automatically command your printer to pause.

## The 4 Rules Explained

1. **Temperature Drop**  
   If the hotend temperature suddenly drops below 150°C during an active print, it usually indicates a broken thermistor wire or a detached heater cartridge.

2. **Thermal Runaway**  
   If the hotend temperature exceeds 280°C, the system triggers immediately to prevent a fire or hardware damage caused by a runaway heater.

3. **Z-Height Anomaly**  
   If the Z-axis height unexpectedly drops during a print, it means the print head collided with something or the stepper motor lost its position. This almost always ruins a print.

4. **Stalled Print**  
   If the printer's state hasn't changed or progressed in over 5 minutes while supposedly printing, the job has hung (often due to serial disconnection or firmware crashes).

## Manual Reporting
If you spot a failure (like a "spaghetti" print) that the system missed, you can hit the **Abort Print** button in the Web UI. This records the failure in the database, helping you build a history of when and why prints failed.
