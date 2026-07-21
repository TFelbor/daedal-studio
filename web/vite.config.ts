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
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
