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
  { name: 'printer-setup', path: '/setup', ready: 'text=Spec engine' },
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
