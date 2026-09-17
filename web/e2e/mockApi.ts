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
 */
export type Attach = 'none' | 'running'

/** Path → body. Longest prefix wins, so `/jobs/{id}` beats `/jobs`. */
function responses(attach: Attach): [RegExp, unknown][] {
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
    [/\/jobs\/[^/]+$/, attach === 'running' ? RUNNING_JOB : COMPLETED_JOB],
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
    const match = table.find(([pattern]) => pattern.test(target))
    if (!match) return route.fulfill({ status: 200, json: {} })
    return route.fulfill({ status: 200, json: match[1] as object })
  })
}
