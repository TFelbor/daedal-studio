"""
infra/scripts/patch_env.py — One-time patch script to add telemetry config
to .env.template and docs/README-docker.md. Run from the project root.

Usage: python infra/scripts/patch_env.py
"""
with open(".env.template", "a") as f:
    f.write("\n# ── Telemetry & Error Handling ────────────────────────────────────────────────\n")
    f.write("TELEMETRY_DB_PATH=/app/telemetry/telemetry.db\n")
    f.write("PAUSE_ON_FAILURE=false\n")

try:
    with open(".env", "a") as f:
        f.write("\n# ── Telemetry & Error Handling ────────────────────────────────────────────────\n")
        f.write("TELEMETRY_DB_PATH=/app/telemetry/telemetry.db\n")
        f.write("PAUSE_ON_FAILURE=false\n")
except Exception:
    pass

with open("docs/README-docker.md", "r") as f:
    readme = f.read()

# Add to volume table
readme = readme.replace(
    "| `p2p-outputs` | `/app/outputs` | Meshes, G-code (output from pipeline) |",
    "| `p2p-outputs` | `/app/outputs` | Meshes, G-code (output from pipeline) |\n| `p2p-telemetry` | `/app/telemetry` | SQLite telemetry database (persists between restarts) |"
)

with open("docs/README-docker.md", "w") as f:
    f.write(readme)

print("Patched .env.template and docs/README-docker.md successfully.")
