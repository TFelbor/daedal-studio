# p2p-mesh — Changes Walkthrough

## Summary

All pre-Phase 4 bugs have been fixed and Phase 4 (Operator) has been implemented and verified end-to-end.

---

## Changes Made

### [FIXED] `pythonsrc/engineer.py`

| Bug | Fix |
|-----|-----|
| `hollow_mesh()` called `mesh.apply_offset()` (non-existent in trimesh) | Replaced with **voxel-based shell** using `scipy.ndimage.binary_erosion` on the filled voxel grid — no Blender required |
| `orient_for_print()` used a hardcoded sign-flip rotation that misaligned geometry | Replaced with a cross-product rotation matrix via `trimesh.transformations.rotation_matrix` that correctly maps the smallest-extent axis to Z and translates Z-min to 0 |
| `remove_degenerate_faces()` / `remove_duplicate_faces()` removed in trimesh 4.x | Fixed to use `nondegenerate_faces()` boolean mask + `np.unique` for duplicates |
| All `print()` → `logging` | Structured `[INFO]`/`[DEBUG]` output, toggled with `--verbose` |
| Hardcoded relative paths | `pathlib.Path` throughout; `output_path.parent.mkdir(parents=True)` |
| Bare `sys.argv` parsing | Full `argparse` CLI: `engineer.py [input] [output] [mm] [--hollow] [--wall MM] [--verbose]` |

### [FIXED] `pythonsrc/sculptor.py`

| Change | Detail |
|--------|--------|
| Decimation step added | `simplify_quadric_decimation(target_faces)` after Taubin smoothing (default 5 000 faces — tunable via `--faces N`) |
| Hardcoded `"inputs/debug_final_view.png"` path | Derived from `image_path.parent / "debug_final_view.png"` |
| Model directory path | `Path(__file__).parent / "models" / "TripoSR"` — CWD-independent |
| All `print()` → `logging` | |
| Full `argparse` CLI | `sculptor.py [--blueprint PATH] [--output PATH] [--faces N] [--verbose]` |

### [FIXED] `pythonsrc/visualizer.py`

| Change | Detail |
|--------|--------|
| `input()` prompt hardcoded | Added `--prompt` flag; interactive fallback retained when omitted |
| Hard-coded paths | `pathlib.Path` + `parent.mkdir()` |
| All `print()` → `logging` | |
| Full `argparse` CLI | `visualizer.py [--prompt TEXT] [--output PATH] [--steps N] [--verbose]` |

### [NEW] `pythonsrc/pipeline.py`

Unified entrypoint that chains all four phases with a single command:

```bash
# Full run
python pythonsrc/pipeline.py "a ceramic vase" --target-mm 80 --hollow

# Skip Visualizer (reuse existing blueprint)
python pythonsrc/pipeline.py --skip-visualizer --skip-sculptor --mesh outputs/test_mesh.obj

# With OctoPrint upload + auto-start
python pythonsrc/pipeline.py "a chess knight" --print \
    --octoprint-url http://octopi.local --octoprint-key MY_KEY --start-print
```

**Key flags:**
- `--skip-visualizer` / `--skip-sculptor` — fast iteration on specific phases
- `--workspace DIR` — set project root (all paths derived from it)
- `--faces N` — decimation target (Phase 2)
- `--hollow` / `--wall MM` — hollow shell (Phase 3)

### [NEW] `pythonsrc/operator_phase.py`

Full OctoPrint REST API client. Covers:

| Capability | API endpoint |
|------------|--------------|
| Connectivity check / version | `GET /api/version` |
| Connection state | `GET /api/connection` |
| File upload | `POST /api/files/local` |
| File list / delete | `GET/DELETE /api/files/{location}/{name}` |
| Job start / pause / cancel | `POST /api/job` |
| Job status + progress watch | `GET /api/job` (polled loop) |

```bash
# Dry-run (no printer needed)
python pythonsrc/operator_phase.py --dry-run --url http://octopi.local

# Upload and start
python pythonsrc/operator_phase.py --file outputs/engineered_mesh.obj \
    --url http://octopi.local --key MY_KEY --start --watch

# API key from environment variable (CI-friendly)
OCTOPRINT_API_KEY=MY_KEY python pythonsrc/operator_phase.py --file ...
```

---

## Verified Test Results

| Test | Command | Result |
|------|---------|--------|
| Engineer (solid) | `engineer.py test_mesh.obj engineered.obj 50.0 --verbose` | ✅ Watertight, 451k faces, 50mm longest dim |
| Engineer (hollow) | `engineer.py ... --hollow --wall 2.0` | ✅ Watertight, 5736 faces, voxel shell correct |
| Pipeline (skip 1+2) | `pipeline.py --skip-visualizer --skip-sculptor --mesh ... --target-mm 60` | ✅ `Pipeline complete ✓ Output: outputs/engineered_mesh.obj` |
| Operator `--help` | `operator_phase.py --help` | ✅ All flags listed |
| Operator `--dry-run` | `operator_phase.py --dry-run` | ✅ Attempts connection, clean `ConnectionError` (no printer on network, expected) |

---

## How to Connect to OctoPrint

1. Start OctoPrint on the same network as the Mac.
2. Generate an **Application API Key** in OctoPrint → Settings → API.
3. Upload and print:
```bash
python pythonsrc/pipeline.py "your object" \
    --print \
    --octoprint-url http://<printer-ip> \
    --octoprint-key <API_KEY> \
    --start-print \
    --watch
```
