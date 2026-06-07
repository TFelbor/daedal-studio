import re

with open("docker-compose.yml", "r") as f:
    content = f.read()

# Add the new volumes
volumes_addition = """
  p2p-telemetry:
    name: p2p-telemetry"""
content = content.replace("  p2p-models-cache:\n    name: p2p-models-hf-cache", "  p2p-models-cache:\n    name: p2p-models-hf-cache\n  p2p-telemetry:\n    name: p2p-telemetry")

# Add the new services
services_addition = """
  # ── API Server ──────────────────────────────────────────────────────────────
  api-server:
    platform: linux/amd64
    build:
      context: .
      dockerfile: docker/server.Dockerfile
    image: p2p-api-server:latest
    ports:
      - "8000:8000"
    volumes:
      - ./inputs:/app/inputs
      - ./outputs:/app/outputs
      - p2p-telemetry:/app/telemetry
    environment:
      - TELEMETRY_DB_PATH=/app/telemetry/telemetry.db
    depends_on:
      - pipeline-runner
    command: uvicorn server.app:app --host 0.0.0.0 --port 8000

  # ── Web (build only, for dev) ───────────────────────────────────────────────
  web:
    build:
      context: .
      dockerfile: docker/web.Dockerfile
    profiles:
      - dev
"""

# Insert services right before the volumes section
content = content.replace("# ── Named volumes", services_addition.lstrip() + "\n# ── Named volumes")

with open("docker-compose.yml", "w") as f:
    f.write(content)
