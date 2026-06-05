#!/bin/bash
# run_phase1_native.sh
# Runs Phase 1 (FLUX image generation) natively on Mac with MPS acceleration.
# Phase 1 cannot use MPS inside Docker — Docker runs a Linux VM on Mac
# and cannot access Apple Silicon GPU hardware from inside the container.
#
# Usage: ./run_phase1_native.sh "your prompt here"

set -e

PROMPT="${1:?Usage: ./run_phase1_native.sh \"your prompt here\"}"
OUTPUT="inputs/blueprint.png"

echo "[p2p] Running Phase 1 natively on Mac (MPS accelerated)..."
python pythonsrc/pipeline.py "$PROMPT" \
    --verbose \
    --output-blueprint "$OUTPUT"

echo "[p2p] Blueprint saved to: $OUTPUT"
echo "[p2p] Now run Phases 2-5 in Docker:"
echo ""
echo "  docker compose run --rm pipeline-runner \\"
echo "    python pythonsrc/pipeline.py \"$PROMPT\" \\"
echo "    --skip-visualizer --blueprint /app/inputs/blueprint.png \\"
echo "    --print --start-print --verbose"
