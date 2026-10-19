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
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
