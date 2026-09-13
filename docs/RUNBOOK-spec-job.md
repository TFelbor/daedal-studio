# Runbook — one spec job, end to end

**What this proves:** that a spec submitted to the running application compiles, is
asserted dimensionally, is sliced by the **real CuraEngine**, is dispatched to a printer
by a person, and leaves one `print_job` row that says all of that happened.

**Why it is a runbook and not only a test.** The default test selection covers the
parametric path up to Phase 3 plus printability, with a CuraEngine *stub* on `PATH`
(`infra/ci/curaengine_stub.sh`, which exits 70 if anything really invokes it). Three
things in this list are machines the suite cannot assume: a slicer, a printer and a
telemetry database. `tests/test_spec_job_end_to_end.py` automates every step below and
skips — naming which one is missing — when they are absent. Run that first; run this
when you need to see it, or when the test skips and you want to know why.

Everything here is `bash` from the repository root, on **macOS or Linux alike**.
Nothing below is Mac-specific: the pipeline runs in the `linux/amd64` images either way,
and the one thing that is — Apple Silicon's MPS, which only Phase 1 uses — is a phase a
spec job never runs. See step 1.

**Comments are on their own line, deliberately.** `zsh` does not treat `#` as a comment
when it is interactive (`interactive_comments` is off by default), so
`make build  # ds-base first` pasted into a Mac terminal hands `make` a `#` target and
stops with `No rule to ... '#'`. Copy whole blocks, not lines with trailing prose.

---

## 0. What you need before you start

- Docker running, and the images built. Phase 4 runs **inside** the pipeline image, so
  this is where the real slicer has to be:

  ```bash
  # ds-base first, then the rest
  make build
  docker run --rm ds-mvp-pipeline:latest sh -c "command -v CuraEngine"
  ```

  The second command must print a path — `/usr/bin/CuraEngine`. If it prints nothing the
  image has no slicer and nothing below is a real test of Phase 4. Its other output is
  expected: `linux/amd64` does not match an Apple Silicon host (Rosetta emulates it), and
  the entrypoint writes `config.py` and warns that `OCTOPRINT_API_KEY` is unset, which
  matters to Phase 5 and not to this probe.

  **Rebuild when the tree moves.** `pythonsrc/`, `server/` and `tests/` are bind-mounted
  into the containers, so a `git pull` reaches them live — but a change to
  `infra/docker/*.Dockerfile` or to `requirements-*.txt` does not, and the container then
  runs today's code against yesterday's dependencies. Phase 3 writes `engineered_mesh.3mf`
  on every run through `lxml`, which is exactly such a change: an image built before it
  fails at the export, not at import.

  **`infra/` is copied into the api-server image, not mounted**, and the server runs
  every pipeline as `docker compose run` against *that* copy. So a change to
  `infra/docker-compose.yml` — a volume, an environment key — does not reach a running
  server at all, and the symptom is a job that fails inside compose with the *old* file's
  behaviour while `git diff` shows the fix:

  ```bash
  docker compose -f infra/docker-compose.yml build api-server
  ```

- **A Python environment carrying this repository's dependencies, activated.** Steps 2,
  4 and 7 run `python` with the repository's own modules on the path —
  `server.simulator_manager`, `pythonsrc.organizer`, `pythonsrc.telemetry.trace` — so on a
  bare interpreter every one of them fails before you reach the slicer. Every `python`
  below means that interpreter, and a Mac has no bare `python` at all until one is active.

  **Which environment manager is not the requirement; the packages are.** Use whichever
  you already have — the repository owns no environment and prescribes none:

  ```bash
  # conda, if that is what this machine uses
  conda activate ds-mvp
  pip install -r requirements-mac.txt
  ```

  ```bash
  # venv, if it is not — no extra tooling, and .venv is gitignored
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements-mac.txt
  ```

  `requirements-linux.txt` in place of `requirements-mac.txt` on Linux. Keep this shell
  for the whole runbook; activate the same environment in any second shell you open.

- The local config and the runtime directories, as for the test suite:

  ```bash
  cp pythonsrc/config.template.py pythonsrc/config.py
  # DS_DATABASE_URL is the one required value in .env
  cp .env.template .env
  mkdir -p data/inputs data/outputs data/logs
  ```

- `DS_DATABASE_URL` in `.env`, pointing at a PostgreSQL you are willing to write a row
  to. Every process — the server, the pipeline container, `trace` — reads that one
  variable; an unset one is a configuration error, never a silent default.

- The web bundle, if you want to watch it in the app rather than with `curl`:

  ```bash
  npm --prefix web ci && npm --prefix web run build
  ```

## 1. Start the API server

```bash
make up
```

That is `docker compose -f infra/docker-compose.yml up api-server`, and it is the path
this runbook takes on both operating systems.

**Why not `make start-native`, and why both exist.** `start-native` runs the same app
under `uvicorn` on the host instead of in a container, and the single thing that buys is
Phase 1: FLUX needs Apple Silicon's MPS, which a container cannot reach, so a *generative*
job renders in ~30 s natively against ~84 minutes on CPU in Docker. **A spec job never
runs Phase 1.** `--spec` implies `--skip-visualizer --skip-sculptor`, and `_phase_skips`
makes the server skip both generative phases for a request carrying a spec — so on this
path the two entry points launch the identical `docker compose run pipeline-runner`, and
`make up` is the one that needs no host interpreter, publishes on loopback by the same
`DS_API_BIND` as a native run, and behaves the same on a Linux machine. Reach for
`start-native` when you are working on Phase 1 on a Mac, and not otherwise.

Check it:

```bash
# curl -s http://localhost:8000/health | python -m json.tool
make health
```

`database.healthy` must be true. A server whose database is unreachable still starts,
degraded, and says so here — with the problem in `database.problems`.

## 2. Start the OctoPrint simulator

```bash
docker compose -f infra/docker-compose.yml --profile simulator up -d octoprint-simulator
```

Give it half a minute — the container being up is not OctoPrint answering inside it — and
then read its API key out of the config it boots with and ask it who it is:

```bash
KEY=$(python -c "from server.simulator_manager import simulator_manager; print(simulator_manager.octoprint_api_key())")
curl -s -H "X-Api-Key: $KEY" http://localhost:5001/api/version
```

An unauthenticated `/api/version` answers 403, so the key is not optional even for a
health probe.

> **Order matters.** The API server's shutdown hook calls
> `simulator_manager.stop_octoprint()`, so restarting the server takes the simulator down
> with it. If you `--force-recreate` the api-server, start the simulator again afterwards.
> Its `data/octoprint/octoprint/config.yaml` autoconnects the virtual printer, so it comes
> back Operational on its own.

## 3. Point the app at the simulator

`POST /jobs` refuses unless a printer **answered**, and the answer comes from the
encrypted config store. Three values (this is what Settings → "use simulator" does):

```bash
for pair in "OCTOPRINT_URL=http://localhost:5001" "OCTOPRINT_API_KEY=$KEY" "DEFAULT_PROFILE=ender3.json"; do
  curl -s -X POST http://localhost:8000/config \
    -H 'Content-Type: application/json' \
    -d "{\"key\": \"${pair%%=*}\", \"value\": \"${pair#*=}\"}" > /dev/null
done

curl -s http://localhost:8000/system/printer/status | python -m json.tool
```

`running` must be `true`. `configured: true, running: false` means a target is set and
did not answer — the URL, the key or the container.

Keep `http://localhost:5001` exactly as it is. That is what a person typed, what the row
records as `dispatched_printer_url`, and the only thing that later distinguishes a
simulator print from real hardware; the container-side translation happens at the moment a
connection is opened and nowhere else.

## 4. Submit the spec

Twenty single-sleeved standard cards, with a lift-off lid — so the compiler emits **two**
parts, a body and a lid, which is what makes this a real exercise of the slicer's
adhesion decision:

```bash
cat > /tmp/deck_box.json <<'JSON'
{
  "archetype": "deck_box",
  "schema_version": 1,
  "compartments": [
    {"contents": {"count": 20, "card": "standard", "sleeving": "single"}}
  ],
  "lid": {
    "kind": "lift_off", "magnets": false,
    "height_mm": 12.0, "wall_mm": 1.2, "clearance_mm": 0.2, "top_mm": 2.0
  }
}
JSON

JOB=$(python - <<'PY'
import json, urllib.request
spec = json.load(open("/tmp/deck_box.json"))
body = json.dumps({
    "prompt": "a deck box for 20 single-sleeved standard cards",
    "printer_id": "default", "profile": "ender3.json", "spec": spec,
    "print": False, "start_print": False,
}).encode()
request = urllib.request.Request(
    "http://localhost:8000/jobs", data=body,
    headers={"Content-Type": "application/json"}, method="POST")
print(json.load(urllib.request.urlopen(request))["job_id"])
PY
)
echo "$JOB"
```

`print: false` is the web app's own submission: the pipeline stops after the slicer and
Phase 5 waits for step 6. A spec request skips both generative phases — there is no image
to draw and no reconstruction to buy — and it is never parked at the blueprint gate.

A spec the schema refuses is a **422 listing every problem**, and no row is written. If
that is what you get, fix the spec; the archetype's own rules (a lip thinner than the
minimum feature, a second compartment, magnets) need the kernel and arrive later as a
failed Phase 2.

## 5. Watch it

```bash
curl -s "http://localhost:8000/jobs/$JOB" | python -m json.tool
tail -f "data/logs/$JOB.log"
```

What should go past, in order: `PHASE 2` compiling the spec (the compiler *is* Phase 2 —
"Compiler" in the app), `PHASE 3` asserting rather than repairing and then
`[DS] Dimensions: 26/26 designed features within ±0.05 mm of the spec`, a
`PRINTABILITY` block, and `PHASE 4` handing an STL to CuraEngine. Expect a few minutes,
most of it the slice.

When it settles, the job's own directory explains itself:

```bash
ls "data/outputs/$JOB"
python -m json.tool < "data/outputs/$JOB/dimension_report.json"
```

- `spec.json` — the spec in canonical form (one spec, one string, one hash)
- `compile_features.json` — every designed dimension, the part list, the spec hash
- `compiled_mesh.stl` — Phase 2's output, what Phase 3 received
- `engineered_mesh.obj` / `.stl` / `.3mf` — the viewer's, CuraEngine's, and the handoff
  copy, which is the only one of the three that records `unit="millimeter"`
- `dimension_report.json` — designed against measured, per feature, off the exported mesh
- `printability.json` — the 11 checks, the score and the verdict
- `engineered_mesh.gcode` — what a printer would run

The row should now say: `size_source: "spec"`, `slice_status: "success"`, a `layer_count`
above zero, a `printability_verdict`, and `dispatch_state: "awaiting_confirmation"`.

## 6. Confirm the dispatch gate

Nothing has been sent to a printer yet. The gate wants the target **as it was displayed**
— confirming a printer you are no longer looking at is not confirming — so read it back
and send it with the confirmation:

```bash
python - <<PY
import json, urllib.request
job = "$JOB"
shown = json.load(urllib.request.urlopen(f"http://localhost:8000/jobs/{job}"))["dispatch_target"]
print("dispatching to", shown)
body = json.dumps({"confirmed": True, "profile": shown["profile"],
                   "base_url": shown["base_url"]}).encode()
request = urllib.request.Request(
    f"http://localhost:8000/jobs/{job}/print-dispatch", data=body,
    headers={"Content-Type": "application/json"}, method="POST")
print(json.load(urllib.request.urlopen(request)))
PY
```

A 409 is the gate working: the printer moved under you (check step 3), the job was already
sent, or the printer did not answer when re-probed. Without `confirmed: true` it is a 400 —
there is no unconfirmed code path.

The simulator's virtual printer now really prints. `dispatch_state` becomes `dispatched`
and the outcome becomes `awaiting_verdict`: dispatched is not printed, and only a person
closes that out.

## 7. Read the row back

```bash
python -m pythonsrc.telemetry.trace --latest
```

That renders one job's row as the writes that filled it, in write order, each annotated
with the `TelemetryDB` method that performed it and each column marked written,
placeholder or expected-null. `--list` indexes recent jobs with a coverage count, a job id
or unique prefix traces that one, `--json` emits a coverage map, `--db` takes a URL other
than `$DS_DATABASE_URL`. The session is opened read-only.

**This is the output to paste into the pull request or the issue.** What has to be in it:

| Where | What it must say |
| --- | --- |
| the request | `size_source = spec`, `requested_size_mm` and `requested_scale_axis` null — the spec fixed every dimension |
| generation | `generation_model = organizer/deck_box`, `generation_backend = local`, no `generation_cost_eur`, the spec hash in `generation_params` |
| blueprint | every `blueprint_*` column null — no image existed, and nothing invented one |
| mesh lineage | `repair_report.repair_method = asserted`, `scale_applied = false`, `scale_axis = preserved`, and a `dimension_check` with `within_tolerance: true` |
| printability | a score and a verdict — `ready` for this spec (the 20-card box measured 100 / `ready` in the dry run); a wider plate can read `risky` on `min_wall_thickness`, because the measurement pitch grows with the plate's width and a 1,4 mm lip then reads as "within tolerance of the minimum" — the check's known quantisation, not a thin lip |
| slice | `slice_status = success`, a `layer_count`, filament figures derived from the E axis |
| dispatch | `dispatched_printer_url = http://localhost:5001` |

## 8. Put the machine back

The virtual printer is mid-print, and it will stay that way:

```bash
curl -s -X POST -H "X-Api-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"command": "cancel"}' http://localhost:5001/api/job
docker compose -f infra/docker-compose.yml --profile simulator stop octoprint-simulator
```

A print someone cancels is not machine-observed evidence about the part, so leave the
job's outcome alone unless you are recording a real verdict.

## The same run, automated

```bash
# pytest tests/ -v -m "slow and real_printer"
make test-slow
pytest tests/test_spec_job_end_to_end.py -m "slow and real_printer"
```

Steps 1–6 without the reading. It drives the ASGI app in-process rather than through
`uvicorn` — a subprocess server would fire the shutdown hook and stop your simulator — and
it will only dispatch to `http://localhost:5001`, so it cannot hand a print to a machine
you have configured in Settings. It cancels the print it starts.

**It does not leave you the row step 7 reads.** `tests/conftest.py` points
`DS_DATABASE_URL` at a schema it creates before collection and **drops after it**, and the
pipeline container inherits that URL from the server — so the row this test writes and
asserts on is gone by the time `pytest` exits, and `python -m pythonsrc.telemetry.trace
--latest` against your real database then shows some *other* job. This form answers "does
the path still work"; only steps 1–7 by hand leave a row in the database you keep.
