import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser-qualification application root. It exists only for Playwright:
//
// * `e2e/app/main.tsx` imports the production router, provider, shell and routes, and
//   substitutes a session transport only when the page installed the explicitly named test
//   bridge;
// * the production build never reads this file, so `index.html` and `src/main.tsx` remain the
//   only production entry and no test-only session path can be bundled.
//
// The port is the one the sidecar's development origin allows. `strictPort` makes a stray
// server fail the run instead of silently qualifying a different origin.
export default defineConfig({
  root: "e2e/app",
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
  },
});
