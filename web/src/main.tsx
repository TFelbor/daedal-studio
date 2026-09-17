import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './global.css'
import './theme'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// The service worker, in production builds only.
//
// `import.meta.env.PROD` rather than a feature check alone: `npm run dev` serves modules
// from Vite, and a worker holding a cached shell in front of that is a dev server whose
// edits stop appearing — which reads as a broken build and is diagnosed as one. There is
// no `sw.js` at all under `vite dev`; the guard is so nothing looks for it.
//
// After load, not during it. Registration competes with the first render for the same
// connection, and the worker is for the *next* visit — it has nothing to offer this one.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(error => {
      // A refused registration is not a reason to fail the app: everything the worker
      // does is an optimisation over a network the page can still reach itself.
      console.warn('[sw] registration failed', error)
    })
  })
}
