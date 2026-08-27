# `licenses/` — the resolved dependency tree, committed

Machine-generated. **Do not hand-edit.** Everything here is rewritten by
[`.github/workflows/licence-data.yml`](../.github/workflows/licence-data.yml) on every
push to `main` and once a week.

The reasoned, human document is [`THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md);
this directory is the evidence under it. `THIRD-PARTY-NOTICES.md` records *why* a
component is acceptable, which no tool can decide; these files record *what is actually
installed*, which no person can enumerate reliably.

## Why it is committed rather than generated on demand

The recurring audit routines read this repository over the GitHub API. They can read
files; they cannot run `pip-licenses`, `npm`, or `syft`. Given only
`requirements-base.txt` and `web/package.json` an audit sees the packages somebody
remembered to name — roughly a hundred — and infers the rest. The resolved tree is
several thousand entries across four ecosystems, and **both components that have broken
this project's Apache-2.0 grant arrived transitively**: `pymeshfix` under a package that
looked like a mesh utility, and `briaai/RMBG-2.0` as another model's configured default.
An audit of the names in a requirements file could not have found either.

## Files

| File | What it is | Produced by |
|---|---|---|
| `report.json` | **Read this first.** Scored index: totals, licence histogram, and the rows that need a person. | `infra/scripts/licence_report.py` |
| `python.json` | Every Python distribution inside the built `p2p-mesh-pipeline` image (Phases 1, 3–5). | `pip-licenses`, run in the container |
| `python-api-server.json` | Every Python distribution inside the built `p2p-api-server` image. | `pip-licenses`, run in the container |
| `python-mac.json` | The macOS-native tree (`requirements-mac.txt`, `mflux`/`mlx`). Weekly. | `pip-licenses` on a macOS runner |
| `python-worker.json` | The TRELLIS.2 GPU worker's tree. **Not produced by CI** — see below. | `pip-licenses` on a CUDA host |
| `node.json` | The web app's **production** tree — what reaches the browser bundle. | `license-checker` |
| `node-dev.json` | The build toolchain (Vite, TypeScript, ESLint). Runs on our machines, not the user's. | `license-checker` |
| `sbom/p2p-*.json` | SBOMs of the built images: Python packages **and** OS packages. | `syft` (syft-json) |
| `sbom/base-*.json` | SBOMs of the registry base images. Weekly. | `syft` (syft-json) |

`pip-licenses` runs **inside the built images**, not against a requirements file, because
the requirements files are not what ships: `infra/docker/pipeline.Dockerfile` installs
`diffusers` from git `HEAD` and a dozen `>=` ranges, and `infra/docker/server.Dockerfile`
pip-installs a list that appears in no requirements file at all. A tree resolved anywhere
else documents an environment nobody runs.

The SBOMs exist for the same reason one layer down: **CuraEngine arrives as an apt
package**, so no Python-level tool can see it, and it is AGPL-3.0.

## Two deliberate gaps

* **The TRELLIS.2 worker image is not built in CI.** It compiles four CUDA extensions
  against a specific GPU architecture, which no hosted runner has. On a CUDA host:

  ```bash
  docker compose -f infra/docker-compose.yml --profile gpu-worker build trellis2-worker
  docker run --rm --entrypoint /bin/sh p2p-trellis2-worker:latest -c \
    'pip install -q pip-licenses && pip-licenses --format=json --with-urls --with-authors \
       --with-license-file --no-license-path' > licenses/python-worker.json
  python3 infra/scripts/normalise_licence_data.py licenses/python-worker.json
  ```

  `report.json` labels the file when it appears and does not pretend the tree is covered
  while it is absent. This is where `nvdiffrast`/`nvdiffrec` would show up if they were
  ever installed, so it is the most important tree to refresh by hand after touching
  `infra/docker/trellis2-worker.Dockerfile`.

* **SBOMs are slimmed before they are committed.** syft's own output for the pipeline
  image is **16 MB**, of which 9 MB is per-package file manifests, 6 MB is file records
  and most of the rest is CPE lists — none of it licence data.
  `infra/scripts/normalise_licence_data.py` keeps `name`, `version`, `type`, `language`,
  `licenses` and `purl` per artifact plus the `source`/`distro`/`descriptor` headers,
  which takes both SBOMs from 20 MB to about 1 MB and makes the file diffable.

* **Full licence texts are kept only where they change an answer.**
  `infra/scripts/normalise_licence_data.py` drops the text of anything the policy classifies
  as permissive and keeps the rest, truncated. Retaining all of it added megabytes of MIT
  boilerplate per merge; dropping all of it would lose the one signal that caught
  `openai/clip-vit-*`, whose repo tag says MIT and whose model card puts *all* deployed
  use out of scope. `LicenseFile` still names the path inside the image.

## Reading `report.json`

```
verdict                 worst severity present: allow | flag | deny
totals.by_severity      how many packages landed in each
totals.by_classification permissive / weak_copyleft / strong_copyleft / non_commercial / unknown
licence_histogram       every licence string seen, most common first
missing_sources         expected files that were absent — counts below are a floor
sources[]               one row per data file, with its own top-10 licences
findings[]              denials, flags, and recorded exceptions. Permissive rows are
                        counted, never listed.
```

Severities come from [`pythonsrc/licence_policy.py`](../pythonsrc/licence_policy.py),
which `tests/test_licensing_guards.py` imports too — the report and the guards cannot
disagree about what is acceptable.

A `findings` row for an OS layer is **aggregated**: one entry per image and licence
class, with a count. Every Debian base image carries dozens of GPL packages (`bash`,
`coreutils`, the gcc runtime) and none of them is a violation while the images stay
undistributed and the AGPL components stay at arm's length. One row per package would
mean the same forty findings every week, which is how the one finding that matters gets
missed. **The count is the signal**: if it moves, a base image changed.

## Running it locally

```bash
make licences        # score whatever data is present, write report.json
make licence-audit   # also write docs/audits/<today>-licence.md
```

Neither regenerates the raw trees — that needs the images. To refresh one by hand, use
the commands in the workflow; they are plain `docker build` and `docker run`.

## What the first run found

Numbers from the run on 2026-08-27, as a sense of scale: **1,371 packages** across six
sources, resolving to **43 finding rows** — 35 individual and 8 aggregates covering 649
OS-layer and unreadable rows. That ratio is the point: an audit that lists every
copyleft `.deb` in a Debian base is an audit nobody reads twice.

It also found a real one. `trimesh[all]`, in two Dockerfiles, includes trimesh's own
`test-more` extra, which had been installing **pymeshlab (GPL-3.0)** and **triangle
(LGPL-3.0)** into production images since Phase 3 was written. Nothing imported either
and no manifest named either. Both images now use `trimesh[easy]`, and
`tests/test_licensing_guards.py` fails on any manifest that names `[all]`.

Three of the five denials that run reported were defects in the scoring, not in the
tree, and each is now a test: a package declaring several licences at once (`docutils`),
a distro-provided package nobody chose (`python-apt`), and packages that put their whole
licence text in the metadata field (`cascadio`, `embreex`, `xatlas` — MIT's text contains
" and " a dozen times, so expression-splitting made three permissive packages
unreadable).

## Failure policy

CI fails on a `deny`: a non-commercial licence, or strong copyleft in a tree that is
linked in-process. It does **not** fail on a `flag` — a flag needs a person to read a
licence, and a red X on every merge is a red X nobody reads.
