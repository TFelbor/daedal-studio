import { test, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import type { Attach } from './mockApi'
import { JOB_ID, mockApi } from './mockApi'

/**
 * Four pages, three widths, one assertion: nothing scrolls sideways.
 *
 * This is the only thing in this repository that runs a browser, and it is deliberately
 * the smallest thing that could. Layout is what an engine does with the rules rather
 * than what the rules say, so no amount of reading `web/src/*.css` can answer "does the
 * dashboard fit on a phone" — but nor does answering it need assertions about what the
 * page *says*. `tests/test_layout_ladder.py` fixes the breakpoints; this checks the
 * result at the widths those breakpoints are for.
 *
 * 375 is an iPhone SE and the narrowest screen worth supporting; 768 is a tablet, and it
 * is here because consolidating the ladder onto 900/720 changed the 900–1000px band and
 * something has to look at it; 1280 is the desktop the app was designed on and is the
 * regression guard on everything above.
 *
 * The screenshots are the other half of the job. They are written to
 * `docs/screenshots/issue-87/` and committed, because "usable at 375px" is a claim a
 * reviewer has to be able to check without a device.
 */

const VIEWPORTS = [
  { name: '375', width: 375, height: 812 },
  { name: '768', width: 768, height: 1024 },
  { name: '1280', width: 1280, height: 900 },
] as const

/**
 * `attach` is how the running view is reached: `/` renders the composer or the running
 * job depending on what `GET /jobs?status=running` answers, not on the URL. See
 * `mockApi`.
 */
const PAGES: { name: string; path: string; ready: string; attach?: Attach }[] = [
  { name: 'composer', path: '/', ready: 'text=What are we' },
  { name: 'running', path: '/', ready: 'text=Elapsed', attach: 'running' },
  { name: 'job-detail', path: `/dashboard/${JOB_ID}`, ready: 'text=Record' },
  { name: 'dashboard', path: '/dashboard', ready: 'text=Jobs' },
  { name: 'printer-setup', path: '/setup', ready: 'text=Sizing' },
  { name: 'about', path: '/about', ready: 'text=Funding' },
]

const SHOTS = '../docs/screenshots/issue-87'

test.beforeAll(async () => {
  await mkdir(SHOTS, { recursive: true })
})

/**
 * The widest element that sticks out of the viewport, named.
 *
 * A bare `scrollWidth > clientWidth` is a true failure and a useless one — the page is
 * 40px too wide and the next question is always "because of what". This walks the tree
 * and returns the deepest element whose right edge is past the viewport, which is
 * almost always the culprit rather than one of its ancestors.
 */
async function overflowingElement(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const limit = document.documentElement.clientWidth
    let worst: { selector: string; right: number } | null = null
    for (const element of Array.from(document.querySelectorAll('body *'))) {
      const rect = element.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) continue
      if (rect.right <= limit + 1) continue
      if (worst && rect.right <= worst.right) continue
      const tag = element.tagName.toLowerCase()
      const cls = typeof element.className === 'string' ? element.className.trim() : ''
      worst = { selector: cls ? `${tag}.${cls.split(/\s+/).join('.')}` : tag, right: rect.right }
    }
    return worst
  })
}

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.width}px`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const target of PAGES) {
      test(`${target.name} fits and scrolls only downward`, async ({ page }) => {
        await mockApi(page, target.attach ?? 'none')
        await page.goto(target.path)
        // The pages fetch on mount and render their empty state first; waiting for a
        // string that only exists in the populated state is what stops this measuring
        // a skeleton.
        await page.locator(target.ready).first().waitFor({ timeout: 15_000 })
        // Fonts arrive from a CDN and change every text measurement when they do.
        await page.evaluate(() => document.fonts.ready)

        await page.screenshot({
          path: `${SHOTS}/${target.name}-${viewport.name}.png`,
          fullPage: true,
        })

        const widths = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }))
        const culprit = await overflowingElement(page)
        expect(
          widths.scroll,
          culprit
            ? `${target.name} at ${viewport.width}px scrolls sideways; widest offender is ` +
              `${culprit.selector}, whose right edge is at ${Math.round(culprit.right)}px`
            : `${target.name} at ${viewport.width}px scrolls sideways`,
        ).toBeLessThanOrEqual(widths.client)
      })
    }
  })
}

/**
 * The box insert's compartment list (issue #152).
 *
 * The composer's only control that is a *list* — every other archetype has a fixed set
 * of fields, so the widest the form can get is a known quantity that the composer page
 * test above already covers. An insert's grows: three compartments open by default and
 * a person can add more, each a bordered block of its own grid. So it gets the same one
 * assertion at both ends of the ladder, on the state the strip actually produces.
 */
for (const width of [375, 1280]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } })

    test('the box insert’s compartment list fits', async ({ page }) => {
      await mockApi(page)
      await page.goto('/')
      await page.locator('text=What are we').first().waitFor({ timeout: 15_000 })
      await page.getByRole('button', { name: 'Box insert' }).click()
      // The third compartment is the last thing the list renders, so waiting for it is
      // waiting for the whole editor rather than for a partial render.
      await page.locator('text=Compartment 3').first().waitFor({ timeout: 15_000 })
      await page.evaluate(() => document.fonts.ready)

      await page.screenshot({
        path: `${SHOTS}/box-insert-${width}.png`,
        fullPage: true,
      })

      const widths = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }))
      const culprit = await overflowingElement(page)
      expect(
        widths.scroll,
        culprit
          ? `the box insert form at ${width}px scrolls sideways; widest offender is ` +
            `${culprit.selector}, whose right edge is at ${Math.round(culprit.right)}px`
          : `the box insert form at ${width}px scrolls sideways`,
      ).toBeLessThanOrEqual(widths.client)
    })
  })
}

test.describe('375px', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('the pipeline explainer opens closed and can be opened', async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
    const details = page.locator('details').first()
    await details.waitFor()
    // Collapsed on a phone: five phase descriptions is two thirds of this screen, and
    // the printer plate above it is the part that can stop the submit button working.
    await expect(details).not.toHaveAttribute('open', /.*/)
    await details.locator('summary').click()
    await expect(details).toHaveAttribute('open', /.*/)
  })

  test('the running view puts its controls above the stage', async ({ page }) => {
    await mockApi(page, 'running')
    await page.goto('/')
    await page.locator('text=Elapsed').first().waitFor({ timeout: 15_000 })

    // The rail dissolves into three homes in source order phases → controls → stage,
    // which is not the DOM order: the stage comes first in the markup and the controls
    // are the last thing in the rail. Dispatch and stop are what this view is for, and
    // below the stage they are past a 200-layer toolpath and two log panes.
    const boxes = await page.evaluate(() => {
      const top = (selector: string) =>
        document.querySelector(selector)!.getBoundingClientRect().top + window.scrollY
      return {
        phases: top('[class*="railPhases"]'),
        controls: top('[class*="railBottom"]'),
        stage: top('[class*="stagePane"]'),
      }
    })
    expect(boxes.phases).toBeLessThan(boxes.controls)
    expect(boxes.controls).toBeLessThan(boxes.stage)

    // And nothing is pinned over the page: a 420px panel stuck to the bottom of an
    // 812px screen would cover half of it for the whole session.
    const position = await page
      .locator('[class*="railBottom"]')
      .evaluate(node => getComputedStyle(node).position)
    expect(position).toBe('static')
  })
})

/**
 * The annotated preview (issue #88).
 *
 * The one part of it no source assertion can reach: whether the labels are *there*, and
 * whether the phone step drops the ones it is meant to. Everything about what a callout
 * says is fixed in Python — `tests/test_view_callouts.py` binds the value to the designed
 * feature and the line to the planes the part has — so this asserts only what a browser
 * knows: a spec job draws them, a prompt job does not, and 375px shows tier 1 alone.
 *
 * It needs a real WebGL context, because a label only exists once the scene has been
 * built. Playwright's Chromium falls back to SwiftShader, which is enough.
 */
test.describe('the mm callouts', () => {
  test.use({ viewport: { width: 1280, height: 900 } })

  test('a spec job is annotated in millimetres, with a comma decimal', async ({ page }) => {
    await mockApi(page, 'spec')
    await page.goto(`/dashboard/${JOB_ID}`)
    const width = page.locator('[data-callout="cavity_width_mm"]')
    await width.waitFor({ timeout: 15_000 })
    // The value comes off `view.json` and is rendered, not computed: 65,2 mm is the
    // fixture's own figure, and a viewer that rounded, converted or recomputed it would
    // show something else here.
    await expect(width).toContainText('65,2 mm')
    await expect(width).toContainText('Internal width')
    // Both tiers, above the phone step.
    await expect(page.locator('[data-tier="2"]').first()).toBeVisible()
  })

  test('a prompt job gets no annotations and no explanation of their absence', async ({ page }) => {
    await mockApi(page, 'none')
    await page.goto(`/dashboard/${JOB_ID}`)
    await page.locator('text=Record').first().waitFor({ timeout: 15_000 })
    // Given time to have drawn them if it were going to: the mesh route answers for
    // every job, so an unguarded viewer would annotate this one with the fixture's
    // millimetres.
    await page.waitForTimeout(1500)
    await expect(page.locator('[data-callout]')).toHaveCount(0)
    // And nothing stands in for them. The spec panel is where a missing spec is
    // explained; the viewer inventing a second sentence is the fabrication this
    // criterion forbids.
    await expect(page.getByText(/no dimensions|not annotated|no spec/i)).toHaveCount(0)
  })
})

test.describe('375px', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('a phone shows the internal figures and drops the externals', async ({ page }) => {
    await mockApi(page, 'spec')
    await page.goto(`/dashboard/${JOB_ID}`)
    await page.locator('[data-callout="cavity_width_mm"]').waitFor({ timeout: 15_000 })
    // Tier 1 is the cavity and the closure — what a misparse costs a print over, and
    // what a person cannot check by looking at the outside of the rendered box. Tier 2
    // is the externals, which the fits line already states in words.
    await expect(page.locator('[data-tier="1"]').first()).toBeVisible()
    await expect(page.locator('[data-tier="2"]').first()).toBeHidden()
  })
})

test.describe('1280px', () => {
  test.use({ viewport: { width: 1280, height: 900 } })

  test('the explainer is open and is not a control', async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
    const details = page.locator('details').first()
    await details.waitFor()
    await expect(details).toHaveAttribute('open', /.*/)
    // No caret, no pointer, and the keyboard skips it: above the phone step this is a
    // block title that happens to be marked up as a summary.
    await expect(details.locator('summary')).toHaveAttribute('tabindex', '-1')
  })
})

/**
 * The two screens the beta videos record (issue #189).
 *
 * The app recording is filmed on 3 Oct 2026 and cannot be edited after it is posted,
 * so a development-status label on screen is wrong in that material forever. Three
 * were, and two had stopped being true of `main`.
 *
 * This needs a browser rather than a grep over `web/src`, for two reasons a source
 * test cannot reach. "Not available" is still in the source — it is the Moonraker
 * simulator's status, and what changed is that the card is behind a closed
 * disclosure; only a rendered page can tell "absent" from "not on the default view".
 * And the second half of the issue is that nothing was *deleted* to get there, which
 * is a claim about controls working after a click.
 *
 * `tests/test_ui_product_copy.py` holds the cheap half that runs in `pytest tests/`.
 */
const DEV_STATUS = [
  'pre-beta',
  'not yet wired',
  'benched',
  'llm',
  'spec engine',
  'not available',
]

/**
 * `AI` is on the issue's list and is deliberately not in the array above.
 *
 * The composer's default view carries the EU AI Act Art. 50(1) disclosure — "Your
 * prompt is read by an AI system…" — which Art. 50(1) puts on the *interface*, whose
 * wording was approved by the owner on 2026-09-09 (#78) and is used verbatim, and
 * which `tests/test_ip_notice.py` fails without. So the word is checked where it is a
 * product claim rather than a regulated one: nowhere on `/setup`, and on `/` only
 * outside that one sentence.
 */
const AI_WORD = /(?<![A-Za-z])AI(?![A-Za-z])/
const ART_50_DISCLOSURE = 'Your prompt is read by an AI system'

for (const width of [375, 1280]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } })

    for (const target of [
      { name: 'composer', path: '/', ready: 'text=What are we' },
      { name: 'settings', path: '/setup', ready: 'text=Sizing' },
    ]) {
      test(`the ${target.name} shows no development status`, async ({ page }) => {
        await mockApi(page)
        await page.goto(target.path)
        await page.locator(target.ready).first().waitFor({ timeout: 15_000 })

        const shown = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
        for (const word of DEV_STATUS) {
          expect(
            shown.toLowerCase(),
            `the ${target.name} at ${width}px still says "${word}" on its default view`,
          ).not.toContain(word)
        }

        // Everything but the one sentence the law requires.
        const withoutDisclosure = shown.split(ART_50_DISCLOSURE).join('')
        if (target.path === '/') {
          expect(
            shown,
            'the Art. 50(1) disclosure has left the composer; see tests/test_ip_notice.py',
          ).toContain(ART_50_DISCLOSURE)
        }
        expect(
          AI_WORD.test(withoutDisclosure),
          `the ${target.name} at ${width}px says "AI" outside the Art. 50(1) disclosure`,
        ).toBe(false)
      })
    }

    test(`the developer disclosure keeps its controls, ${width}px`, async ({ page }) => {
      await mockApi(page)
      await page.goto('/setup')
      await page.locator('text=Sizing').first().waitFor({ timeout: 15_000 })

      const dev = page.locator('#settings-developer details')
      // Closed at both ends of the ladder: "developer configuration" is not a
      // property of the width it is being read on.
      await expect(dev).not.toHaveAttribute('open', /.*/)

      await dev.locator('summary').click()
      await expect(dev).toHaveAttribute('open', /.*/)

      // Nothing was removed to clear the first screen. One control from each of the
      // three groups the disclosure holds.
      await expect(page.locator('#hf-token')).toBeVisible()
      await expect(page.getByRole('button', { name: 'Start' })).toBeVisible()
      await expect(page.locator('#log-level')).toBeVisible()
      await expect(page.locator('text=Skip sculptor')).toBeVisible()
    })
  })
}
