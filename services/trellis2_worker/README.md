# TRELLIS.2 GPU sculptor worker

Phase 2 runs TRELLIS.2-4B, which needs an NVIDIA GPU with roughly 24 GB of VRAM
and four compiled CUDA extensions (`flash-attn`, `CuMesh`, `FlexGEMM`, `o-voxel`).
None of them has a CPU kernel. This worker exists so the *rest* of the pipeline —
FLUX on a Mac, the Engineer, CuraEngine, the API server — can keep running on a
machine that has no such GPU.

The client side is `pythonsrc/sculptors/remote.py`.

## What it returns

**Raw geometry, before print post-processing.** Orientation, component pruning,
smoothing and decimation all happen on the client, in
`SculptorBackend.postprocess`. Two reasons:

- there is then exactly one implementation of post-processing, shared by local and
  remote runs, so a remote job and a local job produce the same mesh;
- GPU seconds are not billed for work a CPU does fine.

The coordinate frame comes back in the `X-DS-Up-Axis` response header, which is
what makes that split safe — the client rotates to Z-up using it rather than
assuming.

## Endpoints

| Method | Path      | Purpose                                            |
| ------ | --------- | -------------------------------------------------- |
| `GET`  | `/health` | Readiness, loaded model, GPU name and free VRAM     |
| `POST` | `/sculpt` | Multipart blueprint image → raw mesh bytes          |

`POST /sculpt` form fields: `image` (required), `backend`, `pipeline_type`, `seed`.
Response headers: `X-DS-Mesh-Format`, `X-DS-Up-Axis`, `X-DS-Backend`,
`X-DS-Model`, `X-DS-Model-Version`.

Requests are serialised: one 4B-parameter reconstruction at a time, because the
GPU cannot serve two, and because `pipeline_type`/`seed` overrides are applied to
the shared backend instance under the same lock and restored afterwards.

## Configuration

| Variable                  | Default    | Meaning                                          |
| ------------------------- | ---------- | ------------------------------------------------ |
| `DS_WORKER_API_KEY`      | *(unset)*  | If set, `Authorization: Bearer …` is required     |
| `DS_WORKER_BACKEND`      | `trellis2` | Backend to serve                                 |
| `DS_WORKER_MESH_FORMAT`  | `obj`      | Wire format for the returned mesh                |
| `DS_WORKER_PRELOAD`      | `true`     | Load weights at boot rather than on first request |
| `TRELLIS2_MODEL_PATH`     | `/models/trellis2` | Local weights; falls back to the HF repo  |
| `TRELLIS2_REPO_PATH`      | `/opt/TRELLIS.2`   | The TRELLIS.2 source checkout             |
| `TRELLIS2_PIPELINE_TYPE`  | `1024_cascade`     | Default voxel resolution                  |

## Running it

```sh
# Build (30-60 min; the CUDA extensions compile from source).
# Set the arch list to your deployment GPU: 8.0=A100 8.6=A10G 8.9=L4 9.0=H100
docker build -f infra/docker/trellis2-worker.Dockerfile \
    --build-arg TORCH_CUDA_ARCH_LIST="8.6" \
    -t ds-trellis2-worker .

# Run on the GPU host
docker run --rm --gpus all -p 8100:8100 \
    -v ds-models-trellis2:/models/trellis2 \
    -e HF_TOKEN=$HF_TOKEN \
    -e DS_WORKER_API_KEY=some-shared-secret \
    ds-trellis2-worker

# Or via compose, on the GPU host
docker compose -f infra/docker-compose.yml --profile gpu-worker up trellis2-worker
```

Then, on the machine running the pipeline:

```sh
export DS_SCULPTOR_BACKEND=remote
export DS_SCULPTOR_REMOTE_URL=http://<gpu-host>:8100
export DS_SCULPTOR_REMOTE_KEY=some-shared-secret
python pythonsrc/pipeline.py "a ceramic vase"
```

Check it before submitting a job — a failed preload shows up here rather than as a
failed Phase 2 four minutes in:

```sh
curl -s http://<gpu-host>:8100/health | python -m json.tool
```

## Building the adapted checkout

The Dockerfile clones upstream TRELLIS.2 by default. To build a fork — for example
one that replaces the `nvdiffrast`/`nvdiffrec` renderers, whose licences are not
compatible with this project's Apache-2.0 grant — override the build args:

```sh
docker build -f infra/docker/trellis2-worker.Dockerfile \
    --build-arg TRELLIS2_REPO=https://github.com/<you>/TRELLIS.2.git \
    --build-arg TRELLIS2_REF=<branch> \
    -t ds-trellis2-worker .
```

The shape-only path this worker uses never imports a rasterizer, so the renderer
question does not arise at inference time — but it does decide what the image is
allowed to contain. See `THIRD-PARTY-NOTICES.md`.
