/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The gateway serves the built app and swaps this placeholder for a fresh nonce on
// every request (strict CSP with 'strict-dynamic'). Vite stamps it on the tags it emits.
const NONCE = "__CSP_NONCE__";

export default defineConfig({
  plugins: [react()],
  html: { cspNonce: NONCE },
  build: {
    target: "es2022",
    sourcemap: false,
    // No inline data: URLs for assets: everything comes from 'self'.
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: {
      // Run the gateway with DEEPSIFT_ALLOWED_ORIGINS=http://localhost:5173
      "/api": { target: "http://127.0.0.1:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
