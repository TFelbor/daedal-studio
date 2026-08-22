import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
