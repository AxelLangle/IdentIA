/**
 * Configuración de Vite para el frontend de IdentIA.
 *
 * Habilita React y Tailwind CSS v4 y configura un proxy en desarrollo local
 * para redirigir todas las peticiones `/api/*` hacia el backend FastAPI en 127.0.0.1:8000.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
