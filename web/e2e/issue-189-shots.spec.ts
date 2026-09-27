import { test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { mockApi } from './mockApi'

/**
 * The before/after evidence for issue #189, regenerable.
 *
 * Not part of the smoke: it asserts nothing. `viewports.spec.ts` is what fails when a
 * development-status label comes back, and `tests/test_ui_product_copy.py` is the
 * cheap half of that. This exists because "no dev-status label on the two screens the
 * 3 Oct recording films" is a claim a reviewer checks by *looking*, and the shots in
 * `docs/screenshots/issue-189/` are committed for that — the same reason issue #87's
 * are.
 *
 * Skipped unless `SHOT_DIR` says which half to write, so `npm run e2e` in CI does not
 * spend eight browser runs a push rewriting committed images:
 *
 *     SHOT_DIR=before git stash && npx playwright test issue-189-shots   # on main
 *     SHOT_DIR=after  npx playwright test issue-189-shots                # with the change
 */
const SHOT_DIR = process.env.SHOT_DIR ?? ''
const DIR = `../docs/screenshots/issue-189/${SHOT_DIR}`

const PAGES = [
  { name: 'composer', path: '/', ready: 'text=What are we' },
  // Not the section name: this file has to render on both sides of a rename, and
  // "Printer" is section 02 before the change and after it.
  { name: 'settings', path: '/setup', ready: 'text=Printer' },
] as const

const THEMES = ['dark', 'light'] as const
const WIDTHS = [
  { name: '375', width: 375, height: 812 },
  { name: '1280', width: 1280, height: 900 },
] as const

test.beforeAll(async () => {
  if (SHOT_DIR) await mkdir(DIR, { recursive: true })
})

for (const viewport of WIDTHS) {
  test.describe(`${viewport.width}px`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const theme of THEMES) {
      for (const target of PAGES) {
        test(`${target.name} ${theme}`, async ({ page }) => {
          test.skip(!SHOT_DIR, 'set SHOT_DIR=before|after to regenerate the evidence')

          await page.addInitScript(t => {
            try {
              localStorage.setItem('ds.theme', t)
            } catch {
              // Private windows and blocked site data both throw; the default ground
              // is the dark one, which is half of what this wants anyway.
            }
          }, theme)
          await mockApi(page)
          await page.goto(target.path)
          await page.locator(target.ready).first().waitFor({ timeout: 15_000 })
          await page.evaluate(() => document.fonts.ready)

          await page.screenshot({
            path: `${DIR}/${target.name}-${viewport.name}-${theme}.png`,
            fullPage: true,
          })
        })
      }
    }
  })
}
