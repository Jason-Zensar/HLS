/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "monospace"] },
      colors: {
        ink: { 50: "#f7f8fa", 100: "#eef0f4", 200: "#dde1e8", 300: "#c3c9d4", 400: "#8e97a8", 500: "#646d7f", 600: "#4a5263", 700: "#363c4a", 800: "#232733", 900: "#151821" },
        g: { trial: "#2563eb", intervention: "#7c3aed", condition: "#0d9488", biomarker: "#d97706", criterion: "#6b7280", outcome: "#16a34a", safety: "#be4b49", evidence: "#475569" },
      },
    },
  },
  plugins: [],
};
