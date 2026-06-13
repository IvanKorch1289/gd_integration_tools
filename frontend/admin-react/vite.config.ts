import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // S108 W1: esbuild 0.28.1+ requires es2022+ for destructuring
    // transform. Vite 6.4 default `chrome87` is below that threshold.
    target: 'es2022',
  },
})
