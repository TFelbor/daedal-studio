# ────────────────────────────────────────────────────────────────────────────
# phase1.Dockerfile — Visualizer (FLUX.2-klein-4B, text-to-image)
#
# Inherits the base layer and adds:
#   - PyTorch (CPU by default; GPU via compose override)
#   - diffusers, transformers, accelerate, safetensors
#   - Model weights are NOT baked in — stored in a named volume at
#     /models/flux and downloaded on first run.
#
# Build (standalone):
#   docker build -f infra/docker/phase1.Dockerfile -t ds-phase1-visualizer .
# ────────────────────────────────────────────────────────────────────────────

FROM ds-base:latest AS phase1-visualizer

LABEL description="ds-mvp Phase 1 — Visualizer (FLUX text-to-image)"

# ── Model path ────────────────────────────────────────────────────────────────
ENV FLUX_MODEL_PATH=/models/flux \
    HF_HOME=/models/hf_cache \
    TRANSFORMERS_CACHE=/models/hf_cache

# ── Python dependencies ───────────────────────────────────────────────────────
# Install in a separate RUN step so the layer is cacheable independently.
RUN pip install --no-cache-dir \
        torch==2.5.1 \
        torchvision==0.20.1 \
        torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
        "diffusers>=0.30.0" \
        "transformers>=4.44.0" \
        "accelerate>=0.33.0" \
        "safetensors>=0.4.0" \
        "sentencepiece>=0.2.0" \
        "protobuf>=3.20.0" \
        "Pillow>=10.0.0" \
        "huggingface_hub>=0.24.0" \
        "hf_transfer>=0.1.6"

# ── Entry point ───────────────────────────────────────────────────────────────
# Expects OCTOPRINT_API_KEY, FLUX_MODEL_PATH, etc. via environment / .env file
ENTRYPOINT ["/usr/local/bin/ds-entrypoint", "python", "pythonsrc/visualizer.py"]
CMD ["--help"]
