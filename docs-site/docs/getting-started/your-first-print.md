# Your First Print

Let's walk through producing and printing your first part.

:::info Direction
Daedal Studio is pivoting to **custom-fit tabletop & TCG organizers**: an LLM reads the
numbers out of your prompt, and a parametric engine builds exact geometry from them.
The prompt-to-organizer flow is under construction; what runs end-to-end today is the
pipeline below, entered either from a text prompt (generative branch) or from a mesh
you supply.
:::

## 1. Run the pipeline on a mesh you already have

This is the route the parametric engine will use, and it works today. Give Phase 3 a
mesh whose dimensions are final, and tell it not to rescale:

```bash
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "deck box" --skip-visualizer --skip-sculptor --mesh /app/data/inputs/box.stl --no-scale --print --start-print
```

The mesh is validated (never rescaled — `--no-scale` means "these dimensions are
final"), scored for printability, sliced with your printer profile's real settings, and
dispatched.

## 2. Or run the generative branch from a prompt

```bash
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a cute low-poly frog" --print --start-print
```

This runs the benched text→image→3D path: **Visualizer** (prompt → blueprint image),
**Sculptor** (image → mesh; needs an NVIDIA GPU, a GPU worker, or a paid hosted
endpoint), then the same Engineer → Slicer → Operator chain.

## 3. Watching and printing

Jobs submitted from the web UI stop twice for a human: once at the blueprint (on the
generative branch) and once before dispatch — you confirm the exact printer shown
before anything heats up. The `--start-print` flag above is the unattended CLI path
that skips those gates. Telemetry streams live either way, with automatic failure
detection.
