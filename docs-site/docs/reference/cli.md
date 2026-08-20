# Command Line Interface (CLI)

While most users will interact with the Web UI, developers can bypass the UI and run the pipeline script directly from the terminal inside the Docker container.

The `pipeline.py` script accepts the following flags:

| Flag | Example | What it does |
|------|---------|--------------|
| `--skip-visualizer` | `--skip-visualizer --blueprint /path/to/img.png` | Bypasses text-to-image generation and uses the provided image file. |
| `--skip-sculptor` | `--skip-sculptor --mesh /path/to/mesh.obj` | Bypasses 3D generation and uses the provided 3D model. |
| `--sculptor-backend` | `--sculptor-backend remote` | Where Phase 2 runs: `auto`, `trellis2` (in-process, needs a CUDA GPU) or `remote` (a GPU worker). |
| `--pipeline-type` | `--pipeline-type 1536_cascade` | TRELLIS.2 voxel resolution: `512`, `1024`, `1024_cascade` (default) or `1536_cascade`. Higher is finer and slower. |
| `--mesh-seed` | `--mesh-seed 7` | Seed for the reconstruction. Distinct from `--seed`, which seeds the blueprint. |
| `--smooth` | `--smooth 5` | Taubin smoothing passes. Off by default — smoothing rounds off the sharp features TRELLIS.2 recovers. |
| `--skip-engineer` | `--skip-engineer` | Skips mesh repair and scaling. |
| `--skip-slicer` | `--skip-slicer` | Skips CuraEngine G-code generation. |
| `--print` | `--print` | Enables the dispatch phase to send the file to the printer. |
| `--start-print` | `--start-print` | Immediately tells the printer to begin heating and printing. |

## Example Usage

Run the pipeline from an existing 3D mesh, skipping AI generation entirely, and print it:

```bash
docker compose run --rm pipeline-runner python pythonsrc/pipeline.py \
  --skip-visualizer --skip-sculptor \
  --mesh /app/outputs/my_custom_mesh.obj \
  --print --start-print
```
