import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  root: 'lnbits/static',
  logLevel: 'info',  // Added for verbose logging
  clearScreen: false, // Prevents Vite from clearing the terminal
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://lnbits:5000',
        changeOrigin: true
      },
      '^(?!/assets).*': {
        target: 'http://lnbits:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    // Ensure we have an entry point
    rollupOptions: {
      input: '/app/lnbits/static/js/app.js'
    }
  }
})
