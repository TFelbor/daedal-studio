# Klipper Simulation

When developing the Prompt2Print telemetry and failure detection logic, it is often necessary to simulate a 3D printer running Klipper and Moonraker without using real hardware.

We provide a lightweight Python script that acts as a mock Moonraker server. It binds to a local port and simulates the JSON-RPC WebSocket behaviour of Klipper.

### Running the Simulator

```bash
python scripts/simulate_klipper.py --port 7125
```

Once running, you can connect the `api-server` or `pipeline-runner` to `ws://localhost:7125/websocket`. 

### Simulating Failures

The simulator allows you to trigger synthetic anomalies to test the failure detection engine:
- **Drop Temp**: Artificially lowers the hotend temperature to 120°C to trigger `DetectTemperatureDrop`.
- **Runaway**: Spikes the hotend to 300°C to trigger `DetectThermalRunaway`.
- **Drop Z**: Instantly lowers the Z-height mid-print to trigger `DetectZHeightAnomaly`.
