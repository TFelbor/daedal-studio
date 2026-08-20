# Prompt2Print — Cloud Cost Estimation
### Pipeline: Prompt → Blueprint → 3D Mesh → G-code → Remote Upload to Printer

> **Document status:** Pre-production estimate for financial planning. All figures are
> directional — actual costs will require benchmarking on chosen infrastructure.
> Last updated: July 2026

> ⚠️ **Every Phase 2 figure below is stale as of 2026-08-20.** They were measured
> against **TripoSR**, which has been replaced by **TRELLIS.2-4B**. The two are not
> comparable and the difference cuts both ways, so nothing here can be adjusted by a
> multiplier — Phase 2 needs re-benchmarking end to end:
>
> - **A10G (24 GB) is now the floor, not a comfortable choice.** TRELLIS.2 is a 4B
>   model needing ~24 GB of VRAM against TripoSR's ~3 GB. The "always-hot VRAM"
>   sizing and the assumption that FLUX and the sculptor can share one GPU both need
>   rechecking.
> - **Inference is much faster.** Upstream reports 512³ ≈ 3s, 1024³ ≈ 17s and
>   1536³ ≈ 60s on an H100 for shape *and* material. Prompt2Print runs the shape-only
>   path, roughly the first of those two numbers (≈ 2s / 10s / 35s), against
>   TripoSR's ~110-140s. Per-job GPU seconds should fall sharply.
> - **Weight loading and cold starts get worse.** 4B parameters is a much larger
>   download and a much longer load than TripoSR's, which dominates the serverless
>   cold-pool model rather than the inference figures.
> - **`--pipeline-type` is now the main cost lever**, replacing "marching cubes
>   resolution". It is a genuine quality/cost dial: `512`, `1024`, `1024_cascade`
>   (default), `1536_cascade`.
> - **A new deployment shape exists.** Phase 2 can run in a separate GPU worker
>   (`services/trellis2_worker/`) while Phases 1 and 3–5 run on cheap CPU, which is a
>   different cost structure from one GPU box running everything.
>
> Treat the tables below as the TripoSR-era baseline they are.

---

## 1. Executive Summary

### Tiered Architecture

| User tier | Routing | GPU model | SLA guarantee | Cost model |
|---|---|---|---|---|
| **Free** | Serverless queue | A10G (cold pool, NVMe weights) | None (~6-12 min) | Pay-per-GPU-second |
| **Paid** | Priority queue | A10G (always-hot VRAM) | <5 min | Always-on instance |
| **Paid Premium** | Priority queue | A10G (always-hot VRAM) | <5 min | Same instance + LLM step |

### Monthly Cost Summary (75% free / 25% paid user split)

| Scenario | Total jobs/mo | Free jobs | Paid jobs | **Total cost/mo** | **Cost per free job** | **Cost per paid job** |
|---|---|---|---|---|---|---|
| **Low** (MVP) | 100 | 75 | 25 | ~$596 | ~$0.055 | ~$23.40 |
| **Medium** (growth) | 2,000 | 1,500 | 500 | ~$720 | ~$0.055 | ~$1.23 |
| **High** (scale) | 20,000 | 15,000 | 5,000 | ~$2,085 | ~$0.055 | ~$0.25 |

> [!IMPORTANT]
> The free/paid split dramatically changes the economics vs. the single-tier model.
> At Low volume, the paid warm instance is still mostly idle and expensive per-job.
> At Medium volume (~500 paid jobs/mo), the cost per paid job becomes very manageable.
> The free tier cost is nearly flat at ~$0.055/job regardless of scale — it's purely variable.

---

## 2. Pipeline Architecture Recap

The pipeline runs 5 sequential phases per job:

| Phase | Component | Technology | Compute type | Tier routing |
|---|---|---|---|---|
| 1 | Visualizer | FLUX.2-klein-4B (4B params) | **GPU-heavy** | Free: serverless · Paid: hot VRAM |
| 2 | Sculptor | TripoSR + Marching Cubes res=256 | **GPU-heavy** | Free: serverless · Paid: hot VRAM |
| 3 | Engineer | manifold3d + trimesh (repair, scale, orient) | CPU-only | All tiers: same CPU container |
| 4 | Slicer | CuraEngine (mesh → G-code) | CPU-only | All tiers: same CPU container |
| 5 | Operator | HTTP REST upload to user's printer | Network only | All tiers: negligible |

> [!NOTE]
> Phases 3-5 are CPU-only and complete in ~30-55 seconds total. They are cheap to run
> on both tiers and do not require a GPU instance. For the serverless free tier they
> can run on a standard cheap compute container (e.g. AWS Lambda or equivalent).

---

## 3. Marching Cubes Resolution Assessment

### Why res=256 is the right production setting

TripoSR internally encodes the 3D scene as a **triplane feature grid at 64x64 resolution**.
The marching cubes step samples this grid to extract the mesh surface. Critically, this
means increasing marching cubes resolution beyond the triplane's intrinsic detail yields
**diminishing returns** — you produce more triangles, not more geometric information.

The practical useful ceiling for TripoSR is approximately **res=256–320**.

### Resolution vs. Printer Compatibility

| Printer type | XY print resolution | Voxel size at res=256, 100mm object | Verdict |
|---|---|---|---|
| **FDM (Ender 3, Bambu X1, Prusa MK4)** | ~0.40 mm | ~0.39 mm | ✅ Perfectly matched — mesh is NOT the bottleneck |
| **Resin / SLA / MSLA** | ~0.025–0.05 mm | ~0.39 mm | ⚠️ Mesh resolution is the bottleneck |

**Conclusion for v1 production:** res=256 is the correct choice. The quality ceiling
imposed by the printer's nozzle diameter and layer height (FDM) is equivalent to
res=256's voxel size at typical object scales. Taubin smoothing applied in Phase 2
further reduces surface staircase artifacts.

**Future consideration:** If resin printer support is added as a premium target,
res=384–512 can be introduced as a "High Fidelity" option — but only on an A100 80GB
(A10G's 24 GB VRAM becomes tight above res=320).

---

## 4. Two-Tier Infrastructure Architecture

### Free Tier — Serverless GPU

```
Free user request
       │
       ▼
  Job Queue (Redis / SQS)
       │
       ▼
  Serverless GPU Container
  (e.g. Modal.com / RunPod Serverless)
  ┌─────────────────────────────────┐
  │  Model weights on NVMe volume   │  ← loads in ~10-20s (not 60-120s)
  │  Phase 1: FLUX inference        │  ← ~90-100s GPU
  │  Phase 2: TripoSR inference     │  ← ~110-140s GPU
  └─────────────────────────────────┘
       │
       ▼
  CPU Container (cheap / Lambda)
  ┌─────────────────────────────────┐
  │  Phase 3: Mesh repair           │  ← ~10-20s CPU
  │  Phase 4: CuraEngine slice      │  ← ~10-30s CPU
  │  Phase 5: Upload to printer     │  ← <5s network
  └─────────────────────────────────┘
  Total user-facing time: ~6-12 min
  Cost per job: ~$0.05-0.06
```

### Paid Tier — Always-Hot Dedicated Pool

```
Paid user request
       │
       ▼
  Priority Job Queue
       │
       ▼
  Always-On A10G Instance(s)
  ┌─────────────────────────────────┐
  │  FLUX weights hot in VRAM       │  ← 0s load time
  │  TripoSR weights hot in VRAM    │  ← 0s load time
  │  Phase 1: FLUX inference        │  ← ~75-100s
  │  Phase 2: TripoSR inference     │  ← ~100-140s
  │  Phase 3+4: CPU (same box)      │  ← ~25-55s
  │  Phase 5: Upload                │  ← <5s
  └─────────────────────────────────┘
  Total user-facing time: ~3:30-5:00 min
  Cost: fixed ~$555/month per GPU
```

---

## 5. Assumptions

### 5.1 SLA & Quality Assumptions

| Parameter | Free Tier | Paid Tier |
|---|---|---|
| Max wall-clock time (SLA) | No guarantee (~6-12 min) | **<5 minutes** |
| FLUX inference steps | 20 steps | Standard: 20 · Premium: 25 |
| TripoSR marching cubes res | 256 | 256 |
| LLM prompt preprocessing | No | Paid Premium: Yes (GPT-4o Mini) |
| Priority in queue | Low / FIFO | High / priority queue |

### 5.2 Infrastructure Assumptions

| Parameter | Value | Rationale |
|---|---|---|
| Paid GPU tier | **NVIDIA A10G (24 GB VRAM)** | Comfortably fits both models hot; 5-min SLA met; 66% cheaper than A100 |
| Free GPU tier | A10G via serverless platform | Same GPU class; weights on persistent NVMe (~10-20s load) |
| Serverless platform | **Modal.com** or **RunPod Serverless** | Both support persistent volume storage for model weights; no per-minute idle billing |
| GPU VRAM (paid hot) | ~14-16 GB | FLUX ~8-10 GB (bfloat16) + TripoSR ~3 GB + U2Net ~0.2 GB + overhead |
| Serverless billing unit | Per GPU-second | Only billed for actual inference time |
| Cloud provider (paid tier) | **CoreWeave EU** or **Lambda Labs EU** | Cheapest A10G rates in nuclear-power EU regions |
| Nuclear power preference | **France (EDF ~70% nuclear)** | AWS eu-west-3, GCP europe-west9, OVHcloud France all qualify |
| Spot discount (paid burst) | ~50-60% off on-demand | For demand spikes above warm pool capacity |

### 5.3 User Split Assumption

| Scenario | Total jobs/mo | Free (75%) | Paid (25%) | Notes |
|---|---|---|---|---|
| **Low** | 100 | 75 | 25 | Early adopters; typical freemium ratio |
| **Medium** | 2,000 | 1,500 | 500 | Word-of-mouth growth; conversion improving |
| **High** | 20,000 | 15,000 | 5,000 | Established product; 25% conversion maintained |

> The 75/25 free/paid split is a conservative freemium industry benchmark. Many
> consumer SaaS products see 2-10% paid conversion; hardware-adjacent products with
> clear utility tend toward the higher end. Adjust this assumption as you gather real data.

### 5.4 Serverless Cost Per Job (Free Tier)

| Phase | GPU seconds | Rate (A10G serverless) | Cost |
|---|---|---|---|
| Phase 1 — FLUX | ~90-100s | ~$0.00022/s | ~$0.020-0.022 |
| Phase 2 — TripoSR | ~110-140s | ~$0.00022/s | ~$0.024-0.031 |
| Container startup + teardown | ~15-20s | ~$0.00022/s | ~$0.003-0.004 |
| Phases 3-5 — CPU container | ~40-55s | ~$0.000015/s (CPU) | ~$0.001 |
| **Total per free job** | | | **~$0.048-0.058** |

> Rounded to **~$0.055/job** for planning purposes. This is remarkably cheap and
> scales linearly — the free tier generates no idle cost whatsoever.

### 5.5 Per-Job Data Assumptions

| Asset | Size | Storage duration |
|---|---|---|
| Blueprint PNG | ~3 MB | Transient — deleted after Phase 2 |
| Raw mesh OBJ | ~2-8 MB | Transient |
| Engineered mesh STL | ~1-5 MB | Transient |
| G-code file | ~0.5-5 MB | Transient — deleted after upload |
| Telemetry/log record | ~0.1 MB | Retained for job history |
| **Total per job** | **~5-20 MB** | Mostly transient; only ~0.1 MB persisted |

---

## 6. Phase Timing Estimates

### Free Tier — Serverless (A10G, NVMe weights, ~15s startup)

| Phase | Time |
|---|---|
| Container startup + model load from NVMe | ~15-20s |
| Phase 1 — FLUX (20 steps, 1024x1024) | ~90-100s |
| Phase 2 — TripoSR (res=256) | ~110-140s |
| Phase 3 — Mesh repair (CPU) | ~10-20s |
| Phase 4 — CuraEngine slice (CPU) | ~10-30s |
| Phase 5 — Upload | <5s |
| **Total** | **~4:00-6:00 min** (plus any queue wait) |

### Paid Tier — Always-Hot (A10G, models in VRAM)

| Phase | Standard | Premium |
|---|---|---|
| Phase 1 — FLUX | ~75-100s (20 steps) | ~90-120s (25 steps) |
| Phase 2 — TripoSR (res=256) | ~100-140s | ~100-140s (same) |
| Phase 3 — Mesh repair | ~8-18s | ~8-18s |
| Phase 4 — CuraEngine slice | ~10-30s | ~10-30s |
| Phase 5 — Upload | <5s | <5s |
| **Total (optimistic)** | **~3:15-3:45 min** ✅ | **~3:30-4:20 min** ✅ |
| **Total (conservative)** | **~4:45-5:00 min** ✅ | **~5:00 min** ⚠️ |

> [!WARNING]
> The conservative Premium (25-step) estimate sits right at the 5-minute boundary.
> Benchmark Phase 1 at 25 steps on a real A10G before committing. Cap at 22 steps
> initially if needed to guarantee the SLA with comfortable headroom.

---

## 7. Full Cost Breakdown

### 7.1 Free Tier — Serverless GPU Compute

| Scenario | Free jobs/mo | Cost per job | **Free tier GPU cost/mo** |
|---|---|---|---|
| **Low** | 75 | ~$0.055 | **~$4.10** |
| **Medium** | 1,500 | ~$0.055 | **~$82.50** |
| **High** | 15,000 | ~$0.055 | **~$825** |

> Zero idle cost. Scales perfectly with usage. This is the major advantage of
> serverless for the free tier — you never pay for capacity you don't use.

### 7.2 Paid Tier — Always-On GPU Compute

| Scenario | Paid jobs/mo | GPU Config | Always-on hrs | Burst hrs | **Paid GPU cost/mo** |
|---|---|---|---|---|---|
| **Low** | 25 | 1x A10G warm | 730 | 0 | **$555** |
| **Medium** | 500 | 1x A10G warm | 730 | 0 | **$555** |
| **High** | 5,000 | 2x A10G warm + spot burst | 730x2 | ~200 @ 50% off | **$1,110 + $76 = $1,186** |

> At Low and Medium, one A10G warm instance can comfortably handle 500 paid jobs/month.
> Each job takes ~4 min; one A10G can serve ~15 jobs/hr → ~10,800 jobs/month capacity
> on a single GPU. Even at Medium volume, utilisation is only ~5% — the GPU is mostly
> idle. This is the fundamental challenge at early scale.

### 7.3 Storage Costs

| Item | Capacity | Rate | Low | Medium | High |
|---|---|---|---|---|---|
| Model weights — paid tier (SSD block) | ~10 GB | $0.02/GB/mo | $0.20 | $0.20 | $0.20 |
| Model weights — free tier (serverless NVMe volume) | ~10 GB | ~$0.05/GB/mo | $0.50 | $0.50 | $0.50 |
| Job telemetry logs | ~0.01 GB/100 jobs | $0.023/GB | <$0.01 | ~$0.05 | ~$0.46 |
| **Storage total** | | | **<$1** | **<$1** | **<$2** |

### 7.4 Networking / Egress Costs

| Item | Per job | Low (100) | Medium (2K) | High (20K) |
|---|---|---|---|---|
| G-code upload to user's printer | ~2 MB avg | 200 MB | 4 GB | 40 GB |
| Egress cost (~$0.09/GB EU) | | <$0.02 | ~$0.36 | ~$3.60 |
| **Networking total** | | **<$1** | **<$1** | **<$4** |

### 7.5 API Server + Web UI

| Tier | Instance type | Cost/month |
|---|---|---|
| All scenarios | 1-2x t3.medium equivalent (~$0.04/hr) | ~$30-60 |

### 7.6 LLM Prompt Preprocessing (Paid Premium Only)

| Model | Cost/call | At 30% of paid jobs |
|---|---|---|
| GPT-4o Mini | ~$0.0003 | ~$0.002 (Low) / $0.045 (Med) / $0.45 (High) |

> Negligible in all scenarios. Even if 100% of paid jobs used GPT-4o (not Mini)
> at $0.005/call, the High scenario cost would be only $25/month.

---

## 8. Total Monthly Cost Summary (Revised Tiered Model)

| Cost Component | **Low** (100 jobs) | **Medium** (2,000 jobs) | **High** (20,000 jobs) |
|---|---|---|---|
| Free tier — Serverless GPU | $4.10 | $82.50 | $825 |
| Paid tier — Always-on GPU | $555 | $555 | $1,186 |
| API Server / Web UI | $30 | $60 | $120 |
| CPU burst / Phase 3-5 containers | $0 | $0 | ~$50 |
| Storage | <$1 | <$1 | <$2 |
| Networking / Egress | <$1 | <$1 | <$4 |
| LLM (Premium paid, ~30% adoption) | <$0.01 | <$0.05 | <$0.50 |
| **Total / month** | **~$591** | **~$699** | **~$2,188** |
| **Cost per free job** | **~$0.055** | **~$0.055** | **~$0.055** |
| **Cost per paid job** | **~$23.40** | **~$1.23** | **~$0.25** |

### Comparison: Single-Tier vs. Two-Tier Model

| Scenario | Single-tier (all always-on) | Two-tier (free serverless + paid hot) | Savings |
|---|---|---|---|
| **Low** | ~$586 | ~$591 | ~0% (similar at low volume) |
| **Medium** | ~$1,212 | **~$699** | **-42% cheaper** |
| **High** | ~$2,756 | **~$2,188** | **-21% cheaper** |

> At Medium scale the two-tier model saves ~$513/month because 75% of jobs are served
> at $0.055 (serverless) instead of consuming expensive always-on GPU capacity.

---

## 9. Highest Cost Levers (Ranked)

| Rank | Lever | Impact | Mitigation |
|---|---|---|---|
| 🔴 1 | **Paid GPU — always-on fixed cost** | At 25 paid jobs/month the GPU sits ~99.7% idle. $555 fixed cost divided by 25 jobs = $22.20/job just in idle cost. | Maximise paid user volume ASAP; consider scale-to-zero with warm restart during off-peak |
| 🔴 2 | **Free/paid user ratio** | If 95% of users are free, serverless costs dominate and scale linearly. If ratio flips, warm instance becomes much more efficient. | Monitor and optimise conversion; cap free tier at N jobs/month |
| 🟡 3 | **FLUX inference steps** | Each extra step = proportional GPU time. 20 → 30 steps = +50% Phase 1 cost on both tiers. | Benchmark quality at 16, 18, 20 steps; find minimum viable threshold |
| 🟡 4 | **TripoSR resolution** | res=256 vs res=128 = ~8x more marching cube ops. Diminishing returns above 256 for TripoSR anyway. | Keep at 256 for v1 — going higher won't improve quality meaningfully |
| 🟢 5 | **Serverless platform selection** | Modal.com vs RunPod vs Banana can vary 20-30% in per-second pricing | Compare and benchmark before committing |
| 🟢 6 | **Provider choice (paid tier)** | CoreWeave EU vs AWS/GCP = 40-50% cost variance | Use CoreWeave EU or Lambda Labs EU |
| 🟢 7 | **Free tier job cap** | Unlimited free jobs scale serverless costs linearly. A cap (e.g. 3 jobs/month free) limits downside. | Implement a free tier job quota |

---

## 10. Provider Recommendations

### Paid Tier (Always-Hot)

| Provider | A10G price/hr | Nuclear region | Verdict |
|---|---|---|---|
| **CoreWeave EU** | **~$0.76** | EU-2 (France-adjacent) | ✅ Top pick |
| **Lambda Labs EU** | **~$0.75** | EU (France-connected) | ✅ Strong option |
| **OVHcloud France** | ~$0.80-1.10 | EDF France ~70% nuclear | ✅ Best for nuclear purity |
| AWS eu-west-3 Paris | ~$1.01 | French nuclear grid | ⚠️ 30% premium |
| GCP europe-west9 Paris | ~$0.90+ | French nuclear grid | ⚠️ Less flexible |

### Free Tier (Serverless)

| Platform | A10G serverless rate | Persistent volumes | Cold start (NVMe) | Verdict |
|---|---|---|---|---|
| **Modal.com** | ~$0.00022/s | ✅ Yes | ~10-15s | ✅ Top pick |
| **RunPod Serverless** | ~$0.00020/s | ✅ Yes | ~15-25s | ✅ Strong option |
| **Banana.dev** | ~$0.00025/s | ⚠️ Limited | ~20-30s | ⚠️ Acceptable |
| AWS SageMaker Async | Varies | ✅ Yes | ~60-120s | ❌ Too slow for free tier UX |

> [!IMPORTANT]
> **Persistent volumes for model weights are critical** on the serverless platform.
> Without them, the container must download FLUX (~8 GB) from HuggingFace on every
> cold start — adding 3-8 minutes and blowing the free tier's UX entirely.
> Modal.com and RunPod both support this well.

---

## 11. Financial Planning Guidance

### Suggested Pricing

| Tier | Price | Jobs included | Rationale |
|---|---|---|---|
| **Free** | $0 | 3 jobs/month | Acquisition tool; cost ~$0.16/month per active free user |
| **Paid Standard** | $9.99/month | 10 jobs (+ $0.89/extra) | Clear speed/SLA upgrade; ~$1/job economics at Medium scale |
| **Paid Premium** | $19.99/month | 10 jobs (+ $1.49/extra) | LLM enrichment + 25-step quality; near-zero marginal cost to you |
| **Pay-as-you-go** | $2.49/job (Standard) · $3.99/job (Premium) | N/A | For low-volume or trial users |

### Key Break-Even Milestones (Paid tier only)

| Milestone | Paid jobs needed | Notes |
|---|---|---|
| Cover warm GPU cost at $9.99/mo subscription | ~56 paid users (10 jobs each) | 560 paid jobs/month |
| Cost per paid job = $1.00 | ~560 paid jobs/month | Strong unit economics begin here |
| Cost per paid job = $0.25 | ~5,000 paid jobs/month | Excellent margins |

> [!TIP]
> Cap free tier at 3 jobs/month per user. This limits free tier liability to ~$0.16/month
> per active free user while giving enough usage to demonstrate value and convert to paid.

### Optimisation Roadmap

1. **Benchmark FLUX at 16-20 steps on A10G** — find minimum viable quality; each step saved reduces both free and paid tier costs proportionally
2. **Monitor free/paid ratio** — if it drifts to >85% free, consider tighter free job limits or faster conversion nudges
3. **Paid tier utilisation tracking** — if paid GPU sits <10% utilised, implement scale-to-zero during quiet periods with a ~90s warm restart (acceptable for off-peak)
4. **Future model upgrades** — newer single-image-to-3D models (InstantMesh, etc.) or distilled FLUX variants could reduce inference time significantly, cutting both tier costs
5. **Batch processing for free tier** — during low-paid-demand periods, route free jobs through the paid warm GPU (opportunistic utilisation boost at zero extra cost)

---

*All prices sourced from public provider pricing pages, July 2026. Actual prices
are subject to change and should be re-verified at time of procurement.*
