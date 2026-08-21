#!/bin/bash
# infra/scripts/run_phase1_native.sh
# Runs Phase 1 (FLUX image generation) natively on Mac with MPS acceleration.
# Phase 1 cannot use MPS inside Docker — Docker runs a Linux VM on Mac
# and cannot access Apple Silicon GPU hardware from inside the container.
#
# Usage (from project root):
#   bash infra/scripts/run_phase1_native.sh "your prompt here"
# Or via Makefile:
#   make phase1-native PROMPT="your prompt here"

set -e

PROMPT="${1:?Usage: bash infra/scripts/run_phase1_native.sh \"your prompt here\" [extra visualizer args]}"
shift  # anything after the prompt (e.g. --seed N, --steps N) is forwarded verbatim
OUTPUT="data/inputs/blueprint.png"

# Ensure output directory exists
mkdir -p data/inputs

echo "[p2p] Running Phase 1 natively on Mac (MPS accelerated)..."
python pythonsrc/visualizer.py --prompt "$PROMPT" \
    --verbose \
    --output "$OUTPUT" \
    "$@"

echo "[p2p] Blueprint saved to: $OUTPUT"
echo "[p2p] Now run Phases 2-5 in Docker:"
echo ""
echo "  docker compose -f infra/docker-compose.yml run --rm pipeline-runner \\"
echo "    python pythonsrc/pipeline.py \"$PROMPT\" \\"
echo "    --skip-visualizer --blueprint /app/data/inputs/blueprint.png \\"
echo "    --print --start-print --verbose"
