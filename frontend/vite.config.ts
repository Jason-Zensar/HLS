import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // start.bat sets CTPIP_API_PORT when port 8000 is taken by another program
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": `http://127.0.0.1:${process.env.CTPIP_API_PORT || 8000}` } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
});
