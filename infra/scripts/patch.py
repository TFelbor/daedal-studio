"""
infra/scripts/patch.py — One-time patch script to add api-server and web
services to infra/docker-compose.yml. Run from the project root.

Usage: python infra/scripts/patch.py
"""
import re

with open("infra/docker-compose.yml", "r") as f:
    content = f.read()

# Add the new volumes
content = content.replace(
    "  p2p-models-cache:\n    name: p2p-models-hf-cache",
    "  p2p-models-cache:\n    name: p2p-models-hf-cache\n  p2p-telemetry:\n    name: p2p-telemetry"
)

# Add the new services
services_addition = """
  # ── API Server ──────────────────────────────────────────────────────────────
  api-server:
    platform: linux/amd64
    build:
      context: ..
      dockerfile: infra/docker/server.Dockerfile
    image: p2p-api-server:latest
    ports:
      - "8000:8000"
    volumes:
      - ../data/inputs:/app/inputs
      - ../data/outputs:/app/outputs
      - p2p-telemetry:/app/telemetry
    environment:
      - TELEMETRY_DB_PATH=/app/telemetry/telemetry.db
    depends_on:
      - pipeline-runner
    command: uvicorn server.app:app --host 0.0.0.0 --port 8000

  # ── Web (build only, for dev) ───────────────────────────────────────────────
  web:
    build:
      context: ..
      dockerfile: infra/docker/web.Dockerfile
    profiles:
      - dev
"""

# Insert services right before the volumes section
content = content.replace("# ── Named volumes", services_addition.lstrip() + "\n# ── Named volumes")

with open("infra/docker-compose.yml", "w") as f:
    f.write(content)

print("Patched infra/docker-compose.yml successfully.")
