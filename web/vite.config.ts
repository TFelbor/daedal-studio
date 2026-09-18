import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    // The service worker's cache name. One per build, so `activate` can delete every
    // other one — without it a deploy leaves the previous shell installed and the only
    // cure is a person knowing to unregister a worker they cannot see.
    __SW_BUILD__: JSON.stringify(new Date().toISOString()),
  },
  build: {
    rollupOptions: {
      // Two entries. The worker is a second Rollup input rather than a hand-written file
      // in `public/`, so `tsc -b` type-checks it and the bundler resolves it — a worker
      // copied verbatim is the one file in the app nothing checks, and it is also the
      // one file that can brick the app for a returning visitor.
      input: {
        main: 'index.html',
        sw: 'src/sw.ts',
      },
      output: {
        // `/sw.js`, unhashed and at the root: a worker's default scope is the directory
        // it is served from, so `assets/sw-a1b2c3.js` would control `/assets/` and
        // nothing else, and a fingerprinted name would leave the browser unable to find
        // the registration it already has.
        entryFileNames: chunk => (chunk.name === 'sw' ? 'sw.js' : 'assets/[name]-[hash].js'),
      },
    },
  },
  server: {
    proxy: {
      '/jobs': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/system': 'http://localhost:8000',
      '/config': 'http://localhost:8000',
      '/simulators': 'http://localhost:8000',
      // Without this the outcome-feedback banner breaks in dev only: Vite answers an
      // unmatched path with index.html, so `res.ok` is true and `res.json()` throws
      // on HTML. The pilot's response rate is measured through these two endpoints.
      '/feedback': 'http://localhost:8000',
      // Same failure mode, two more endpoints: unproxied, Vite answers with index.html,
      // `res.ok` is true and the JSON parse throws. `/prompt` carries the size hint the
      // composer prefills from; `/activity` carries the UI event stream.
      '/prompt': 'http://localhost:8000',
      '/activity': 'http://localhost:8000',
      // Web push: the VAPID public key and the two halves of a subscription's life.
      // Unproxied it would answer with index.html and the JSON parse would throw —
      // and `tests/test_pwa_shell.py` reads this block as the list of paths the API
      // owns, so a push route the service worker could cache would fail there.
      '/push': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
