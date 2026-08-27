# Installation

Welcome to Daedal Studio! This guide will help you install and run the ds-mvp generative engine locally.

## Prerequisites

Before starting, ensure you have the following installed:
- Docker Engine (version 24.x or newer)
- Docker Compose (version 2.20 or newer)
- At least 30 GB of free disk space for AI models
- At least 16 GB of RAM

## Step 1: Configuration

First, create an environment configuration file:

1. Copy the `.env.template` file to `.env` in the root of the project.
2. Open `.env` and configure your settings:
   - Provide a HuggingFace token (`HF_TOKEN`) to download the AI models.
   - Set up your printer connection URL and API key.

## Step 2: Running the Pipeline

Your launch path depends on your computer's hardware.

### macOS (Apple Silicon)
If you're using an M1, M2, or M3 Mac, we recommend running the first phase (text-to-image) natively to take advantage of the Apple GPU, and the rest inside Docker:
1. `make phase1-native PROMPT="a ceramic vase"`
2. `docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a ceramic vase" --skip-visualizer --blueprint /app/inputs/blueprint.png --print --start-print`

### Ubuntu or Windows (with NVIDIA GPU)
If you have an NVIDIA GPU, you can run everything seamlessly inside Docker:
1. `docker compose -f infra/docker-compose.yml -f infra/docker-compose.gpu.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a ceramic vase" --print --start-print`

### Any Computer (CPU Only)
You can run everything on the CPU, but be prepared to wait (over an hour for the first phase):
1. `docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a ceramic vase" --print --start-print`

## Next Steps

Once installed, proceed to [Your First Print](./your-first-print) to see it in action!
