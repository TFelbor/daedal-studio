# Your First Print

Let's walk through generating and printing your first 3D object from a text prompt.

## 1. Entering a Prompt
Start by defining what you want to make. You can run the pipeline by passing a natural language prompt directly:

```bash
docker compose -f infra/docker-compose.yml run --rm pipeline-runner python pythonsrc/pipeline.py "a cute low-poly frog" --print --start-print
```

## 2. Watching the Pipeline
The system will run through five automated phases:
1. **Visualizer**: Your text becomes a 2D blueprint image.
2. **Sculptor**: The blueprint is transformed into a 3D mesh.
3. **Engineer**: The mesh is repaired, scaled, and prepared for printing.
4. **Slicer**: The mesh is sliced into G-code instructions.
5. **Operator**: The G-code is uploaded to your 3D printer.

## 3. Printing!
Because we included the `--start-print` flag, the job is dispatched to your connected printer automatically. You can monitor the telemetry data in real-time or check your printer's dashboard.

Congratulations! You've just gone from text to a physical object without the cloud.
