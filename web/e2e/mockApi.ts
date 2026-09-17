import type { Page, Route } from '@playwright/test'

/**
 * A server made of fixtures.
 *
 * The smoke test measures layout, so it needs every page to render its *populated*
 * state — an empty dashboard is three rows of nothing and fits any width. It does not
 * need a server: a real one would mean a database, a printer and a slicer for a test
 * whose whole assertion is `scrollWidth <= clientWidth`.
 *
 * The values are chosen to be hostile to the layout rather than typical. A 36-character
 * job id, a prompt with no space in it, a profile path four directories deep and a
 * printer URL with a port: each of those is a string with no break opportunity in it,
 * and every horizontal scrollbar this pass removed was one of them in a grid track
 * sized by `auto`.
 */

/** Long, unbreakable, and exactly what a real id looks like. */
export const JOB_ID = 'ds-2026-09-17-a3f9c1e8-7b24-4d05-9e11-6c8faa0b3d72'

const RUNNING_JOB = {
  job_id: JOB_ID,
  prompt: 'deck-box-for-double-sleeved-commander-100-cards-with-a-friction-fit-lid',
  status: 'running',
  created_at: '2026-09-17T09:12:00Z',
  material_type: 'PLA',
  dispatch_state: 'not_ready',
  blueprint_gate: null,
  spec: null,
  outcome: null,
  printer_profile: 'pythonsrc/profiles/anycubic_mega.json',
}

const COMPLETED_JOB = {
  ...RUNNING_JOB,
  status: 'completed',
  dispatch_state: 'awaiting_confirmation',
  completed_at: '2026-09-17T09:41:00Z',
  print_time_minutes: 214,
  filament_used_grams: 86.4,
  layer_height_mm: 0.2,
  printer_service: 'moonraker',
  printer_machine_name: 'voron-trident-350.workshop.local:7125',
}

/** A real report rather than a placeholder: `PrintabilityCard` renders the checks, and
 *  three rows of figures is what the card is at its widest. */
const PRINTABILITY = {
  job_id: JOB_ID,
  evaluated_at: '2026-09-17T09:38:00Z',
  process: 'fdm',
  score: 82,
  verdict: 'ready',
  checks: [
    {
      check: 'min_wall_thickness',
      status: 'pass',
      detail: 'Thinnest wall 2,40 mm against a 0,86 mm floor for a 0,4 mm nozzle',
      value: 2.4,
      threshold: 0.86,
      weight: 3,
      critical: true,
    },
    {
      check: 'overhang_angle',
      status: 'warn',
      detail: 'Steepest unsupported overhang 52°',
      value: 52,
      threshold: 45,
      weight: 2,
      critical: false,
    },
  ],
  features: {},
}

/**
 * A spec job, and the two documents the annotated preview needs.
 *
 * Kept off `COMPLETED_JOB` on purpose: the five layout pages and their committed
 * screenshots are issue #87's, and changing what `job-detail` renders for all of them to
 * test a viewer would be a diff nobody asked for. `attach: 'spec'` is the only mode that
 * serves these.
 */
const SPEC = {
  archetype: 'deck_box',
  compartments: [{ contents: { count: 100, card: 'standard', sleeving: 'double' } }],
  lid: { kind: 'lift_off', magnets: false, height_mm: 15, wall_mm: 1.2, clearance_mm: 0.2, top_mm: 2 },
  process: { wall_mm: 2.4, floor_mm: 2 },
  schema_version: 1,
}

const SPEC_JOB = {
  ...RUNNING_JOB,
  status: 'completed',
  dispatch_state: 'awaiting_confirmation',
  completed_at: '2026-09-17T09:41:00Z',
  spec: SPEC,
  spec_hash: 'f3c1d0a99b2e4471',
  archetype: 'deck_box',
  archetype_version: '2',
}

/**
 * `view.json`, trimmed to four lines — two internal, two external — so the smoke can see
 * a tier drop without rendering a dozen labels into a 375px frame.
 *
 * The frame is the compiled plate's own bounds; `MESH_OBJ` below is the same box after
 * the translation Phase 3 applies, so the viewer's reconciliation succeeds exactly as it
 * does against a real run. Move one and not the other and the callouts vanish, which is
 * the behaviour under test.
 */
const VIEW = {
  archetype: 'deck_box',
  archetypeVersion: 'v2',
  hash: 'f3c1d0a99b2e4471',
  frame: { units: 'mm', up: 'z', bounds_mm: { min: [0, 0, 0], max: [70, 40, 30] } },
  callouts: [
    {
      feature: 'cavity_width_mm', label: 'Internal width', value_mm: 65.2, part: 'body',
      from: [2.4, 20, 30], to: [67.6, 20, 30], offset: [0, 0, 1], tier: 1,
    },
    {
      feature: 'cavity_height_mm', label: 'Internal height', value_mm: 28, part: 'body',
      from: [35, 2.4, 2], to: [35, 2.4, 30], offset: [0, 1, 0], tier: 1,
    },
    {
      feature: 'external_width_mm', label: 'External width', value_mm: 70, part: 'body',
      from: [0, 0, 0], to: [70, 0, 0], offset: [0, -1, 0], tier: 2,
    },
    {
      feature: 'external_depth_mm', label: 'External depth', value_mm: 40, part: 'body',
      from: [0, 0, 0], to: [0, 40, 0], offset: [-1, 0, 0], tier: 2,
    },
  ],
}

/**
 * The mesh `GET /jobs/{id}/mesh` serves: a 70 × 40 × 30 mm box, Z-up, XY-centred and sat
 * on Z = 0 — which is `orient_for_print`'s output for a plate built from the origin, and
 * therefore `VIEW`'s frame plus one translation and nothing else.
 */
const MESH_OBJ = [
  'v -35 -20 0', 'v 35 -20 0', 'v 35 20 0', 'v -35 20 0',
  'v -35 -20 30', 'v 35 -20 30', 'v 35 20 30', 'v -35 20 30',
  'f 1 3 2', 'f 1 4 3', 'f 5 6 7', 'f 5 7 8',
  'f 1 2 6', 'f 1 6 5', 'f 2 3 7', 'f 2 7 6',
  'f 3 4 8', 'f 3 8 7', 'f 4 1 5', 'f 4 5 8',
].join('\n')

const CONFIG = {
  DEFAULT_PROFILE: { value: 'pythonsrc/profiles/anycubic_mega.json', is_secret: false },
  PRINTER_FIRMWARE: { value: 'moonraker', is_secret: false },
  MOONRAKER_URL: { value: 'http://voron-trident-350.workshop.local:7125', is_secret: false },
  MOONRAKER_API_KEY: { value: '••••••••', is_secret: true },
  LOG_LEVEL: { value: 'INFO', is_secret: false },
  SKIP_VISUALIZER: { value: 'false', is_secret: false },
  SKIP_SCULPTOR: { value: 'false', is_secret: false },
}

/**
 * Which of `NewJob`'s two pages the composer route renders.
 *
 * `jobId` decides, and the page sets it from `GET /jobs?status=running` on mount — so
 * whether `/` is the composer or the running view is a property of the *server's*
 * answer, not of the URL. That is the app's design (`docs/SYSTEM-AS-BUILT.md`
 * § Frontend), and it means the smoke has to choose here rather than navigate.
 *
 * `'spec'` is the third mode and is not about that choice at all: it answers every job
 * route with a compiled deck box, so the mesh viewer has a `view.json` to annotate with
 * (issue #88).
 */
export type Attach = 'none' | 'running' | 'spec'

/** Path → body. Longest prefix wins, so `/jobs/{id}` beats `/jobs`. */
function responses(attach: Attach): [RegExp, unknown][] {
  const job = attach === 'running' ? RUNNING_JOB : attach === 'spec' ? SPEC_JOB : COMPLETED_JOB
  return [
    // Arrays, not envelopes. `getJobTelemetry` returns `TelemetrySample[]` and calls
    // `.filter` on it — a `{ samples: [] }` here is a `TypeError` at render, a blank
    // page, and a smoke test that fails as a timeout waiting for text that never
    // arrives. The mock has to match the client's types, not the endpoint's name.
    [/\/jobs\/[^/]+\/telemetry$/, []],
    [/\/jobs\/[^/]+\/failure$/, []],
    [/\/jobs\/[^/]+\/printability$/, PRINTABILITY],
    [/\/jobs\/[^/]+\/provenance$/, null],
    [/\/jobs\/[^/]+\/printer-info$/, { service: 'moonraker', machine_name: 'voron-trident-350' }],
    [/\/jobs\/[^/]+$/, job],
    [
      /\/jobs\?.*status=running/,
      attach === 'running' ? { jobs: [RUNNING_JOB], total: 1 } : { jobs: [], total: 0 },
    ],
    [/\/jobs/, { jobs: [COMPLETED_JOB, RUNNING_JOB], total: 2 }],
    [/\/config\/test-connection/, { ok: true, detail: 'Connected' }],
    [/\/config/, CONFIG],
    [/\/simulators\/status/, { services: {} }],
    [/\/system\/printer\/status/, { configured: true, running: true, service: 'moonraker' }],
    [/\/system\/info/, { version: 'e2e', engine: 'parametric' }],
    [/\/feedback\/pending/, { jobs: [] }],
    [/\/feedback\/stats/, { shown: 0, answered: 0 }],
    [/\/prompt\/size-hint/, { hint: null }],
    [/\/activity/, { ok: true }],
    [/\/health/, { status: 'ok' }],
  ]
}

/** The prefixes that belong to the API rather than to the bundle. */
const API = /\/(jobs|config|simulators|system|feedback|prompt|activity|organizer|health)(\/|\?|$)/

export async function mockApi(page: Page, attach: Attach = 'none'): Promise<void> {
  const table = responses(attach)
  // The token, before the first script runs: `App` renders nothing but the gate
  // without one, and the gate is not a page this pass is about.
  await page.addInitScript(() => {
    window.localStorage.setItem('ds.apiToken', 'e2e-token')
  })

  await page.route('**/*', async (route: Route) => {
    const url = new URL(route.request().url())
    if (!API.test(url.pathname + url.search)) return route.fallback()

    const target = url.pathname + url.search
    // The one route that is not JSON. `MeshViewer` parses the body as an OBJ, so a
    // `{}` here is a mesh with no vertices — a viewer that renders, reports nothing
    // wrong, and shows an empty frame.
    if (/\/jobs\/[^/]+\/mesh/.test(target)) {
      return route.fulfill({ status: 200, contentType: 'text/plain', body: MESH_OBJ })
    }
    // The other special case, and it has to be a real 404: a job with no spec is how the
    // viewer learns it has nothing to annotate with, and an empty 200 would read as
    // "compiled, and every number is missing" — which is why the server 404s it too.
    if (/\/jobs\/[^/]+\/spec$/.test(target)) {
      return attach === 'spec'
        ? route.fulfill({ status: 200, json: { ...SPEC_JOB, view: VIEW } })
        : route.fulfill({ status: 404, json: { detail: 'Job has no spec' } })
    }
    const match = table.find(([pattern]) => pattern.test(target))
    if (!match) return route.fulfill({ status: 200, json: {} })
    return route.fulfill({ status: 200, json: match[1] as object })
  })
}
