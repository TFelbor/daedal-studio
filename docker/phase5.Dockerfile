# ────────────────────────────────────────────────────────────────────────────
# phase5.Dockerfile — Operator (OctoPrint REST client, upload + watch)
#
# Inherits the base layer and adds:
#   - requests (the only non-stdlib dependency of operator_phase.py)
#
# This is the lightest phase image — no ML libs, no mesh tools.
#
# Build (standalone):
#   docker build -f docker/phase5.Dockerfile -t p2p-phase5-operator .
# ────────────────────────────────────────────────────────────────────────────

FROM p2p-base:latest AS phase5-operator

LABEL description="p2p-mesh Phase 5 — Operator (OctoPrint REST client)"

# ── Python dependencies ───────────────────────────────────────────────────────
# operator_phase.py only requires `requests` beyond stdlib.
RUN pip install --no-cache-dir \
        "requests>=2.31.0"

# ── Entry point ───────────────────────────────────────────────────────────────
# Requires OCTOPRINT_URL and OCTOPRINT_API_KEY env vars.
ENTRYPOINT ["/usr/local/bin/p2p-entrypoint", "python", "pythonsrc/operator_phase.py"]
CMD ["--help"]
