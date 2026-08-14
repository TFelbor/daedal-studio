# Split CSS Strategy and Dark Mode Implementation

## Goal
Implement a split CSS architecture for the Vite/React project, introducing a `global.css` file containing variables, resets, layout, and shared component styles (buttons, navbar, footer). Each page will have its own CSS file for page‑specific styles. Introduce a 5‑color palette following the 60‑30‑10 rule, with a CTA color and a highlight/badge color. Add dark‑mode support with automatic detection and a toggle button integrated into the existing header/navbar component.

## Open Questions
- Do you want the per‑page CSS files to be named `PageName.css` and placed alongside the page component (`src/pages/PageName.tsx`), or in a dedicated subdirectory? (Default: alongside the component.)
- Should the theme toggle be a separate `ThemeToggle` component or inline within the existing `Header` component? (Default: inline in `Header`).

## Proposed Changes
---
### 1. Add Global Styles
- **[NEW] `src/global.css`** – defines `:root` variables for the light palette (primary, secondary, accent‑cta, highlight, danger) and a `[data-theme='dark']` block with dark‑mode values. Includes CSS reset, box‑sizing, base typography, and shared component styles (buttons, navbar, footer).
- **[MODIFY] `src/main.tsx`** – import `./global.css` before any other CSS imports.
- **[MODIFY] `src/index.css`** – remove variable definitions and shared component rules that will now live in `global.css`. Keep only page‑specific utilities if needed.
---
### 2. Per‑Page CSS Files
For each page component under `src/pages/`:
- **JobDetail** – create `src/pages/JobDetail.css` (derived from `JobDetail.module.css` but without the CSS‑module scoping).
- **JobList** – create `src/pages/JobList.css`.
- **NewJob** – create `src/pages/NewJob.css`.
- **PrintMonitor** – create `src/pages/PrintMonitor.css`.
- **PrinterSetup** – create `src/pages/PrinterSetup.css`.
Each page component will import its new stylesheet (`import './JobDetail.css';`).
---
### 3. Dark‑Mode Variables and Logic
- Extend `global.css` with a `[data-theme='dark']` selector that overrides the five palette variables.
- Add a small utility script **[NEW] `src/theme.ts`** that:
  1. Checks `localStorage.getItem('theme')` on load.
  2. If absent, checks `window.matchMedia('(prefers-color-scheme: dark)')`.
  3. Sets `document.documentElement.dataset.theme` to `'light'` or `'dark'` accordingly.
  4. Exposes a `toggleTheme()` function that flips the theme, updates the attribute, and writes the new value to `localStorage`.
- Import `src/theme.ts` at the top of `src/main.tsx` so the logic runs early.
---
### 4. Theme Toggle UI
- **[MODIFY] `src/components/Header.tsx`** (or the existing navbar component) to include a button/icon that calls `toggleTheme()` from `theme.ts`.
- Style the toggle button using the shared button classes from `global.css`.
---
### 5. Update Component Class Names
- Replace any hard‑coded color values in JSX/CSS with the new CSS variables (e.g., `background: var(--accent-color);`).
- Ensure button components use `.btn-primary` for the CTA color and `.badge` utilities for highlights/badges.
---
### 6. Verification Plan
- **Automated Tests** – run `npm test` (if present) to ensure nothing breaks.
- **Manual Checks** – after `npm run dev`:
  * Verify global styles (reset, fonts, layout) apply across pages.
  * Confirm each page loads its specific CSS (no missing styles).
  * Test theme detection on fresh load (light vs. dark based on system).
  * Click the toggle button and ensure the UI switches and persists across reloads.
  * Verify the 5‑color palette respects the 60‑30‑10 distribution (visual inspection).
---
## Verification Plan
### Automated
- `npm run lint` (if available) to catch syntax errors.
- `npm run build` to ensure the production bundle compiles.
### Manual
- Open the app in a browser, inspect each page, and ensure the layout matches the design.
- Use the browser devtools to verify `document.documentElement.dataset.theme` toggles correctly.
- Confirm colors change according to the defined variables for both light and dark modes.

**Next Steps**
Once you approve this plan, I will create the new files, modify the existing ones, and run the verification steps.
