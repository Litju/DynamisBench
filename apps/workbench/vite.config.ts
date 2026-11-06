import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// DEV-URL must match `build.devUrl` in apps/desktop/src-tauri/tauri.conf.json:
// the Tauri shell loads the workbench from this server in development.
//
// Tailwind is wired through its own Vite plugin rather than a PostCSS pipeline: v4's
// stylesheet is the whole configuration (`src/styles.css` is one `@import`), so there is no
// `tailwind.config.js` and no `postcss.config.js` to keep in step with the source it scans.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
  },
  // The laboratory's two large dependencies are reached only through lazy imports. Bundling
  // them when the server starts keeps the dev server from discovering them mid-session and
  // re-optimising (which stalls the in-flight dynamic import until a reload).
  optimizeDeps: {
    include: ["three", "apache-arrow"],
  },
  build: {
    // The laboratory route's chunk carries three.js (~0.5 MB minified). It is loaded lazily,
    // only when the laboratory is opened, so it does not weigh on the initial bundle.
    chunkSizeWarningLimit: 720,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // A hosted runner creates an environment per file. The gates are deterministic, but the
    // arrow interoperability suite imports a large optional package once; the budget covers
    // that import without turning any test into a wait loop.
    testTimeout: 15_000,
  },
});
