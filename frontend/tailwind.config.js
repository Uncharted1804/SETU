/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b0d10",
        panel: "#13171c",
        edge: "#232a33",
        muted: "#8b97a8",
        accent: "#4da3ff",
        good: "#39d98a",
        warn: "#f5c451",
        bad: "#ff6b6b",
      },
      fontFamily: {
        // Local system stacks only. No remote fonts, no CDN, no analytics -
        // an air-gapped machine must render identically.
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        mono: ["ui-monospace", "Consolas", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
