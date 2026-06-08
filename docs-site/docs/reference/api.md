# API Reference

The Prompt2Print `api-server` exposes a fully async REST API built with FastAPI. It handles job orchestration, telemetry streaming, and UI interactions.

## Interactive Docs
When the `api-server` Docker container is running, you can access the interactive Swagger documentation by navigating to:
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

## Key Endpoints

- `POST /jobs` — Submit a new text prompt to start the pipeline.
- `GET /jobs/{job_id}` — Retrieve the current phase and status of a specific job.
- `GET /health` — Check if the server and database are responsive.
- `GET /telemetry/stream` — WebSocket endpoint providing real-time printer metrics.
