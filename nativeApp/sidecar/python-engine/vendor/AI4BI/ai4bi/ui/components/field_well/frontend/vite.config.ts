import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "./" so the built asset URLs are relative — required because Streamlit
// serves the component from an arbitrary component path, not the web root.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    assetsDir: "assets",
    // Inline everything into index.html-referenced assets; keep it simple.
    chunkSizeWarningLimit: 2000,
  },
});
