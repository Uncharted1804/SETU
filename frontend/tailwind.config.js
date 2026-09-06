/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--setu-ink) / <alpha-value>)",
        panel: "rgb(var(--setu-panel) / <alpha-value>)",
        edge: "rgb(var(--setu-edge) / <alpha-value>)",
        muted: "rgb(var(--setu-muted) / <alpha-value>)",
        accent: "rgb(var(--setu-accent) / <alpha-value>)",
        good: "rgb(var(--setu-good) / <alpha-value>)",
        warn: "rgb(var(--setu-warn) / <alpha-value>)",
        bad: "rgb(var(--setu-bad) / <alpha-value>)",
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
