/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    // DOMParser e document vêm do jsdom; nenhum teste chama rede.
    environment: 'jsdom',
  },
})
