/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["selector", '[data-theme="dark"]'],
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
        content: "rgb(var(--setu-content) / <alpha-value>)",
      },
      fontFamily: {
        // Local system stacks only. No remote fonts, no CDN, no analytics -
        // an air-gapped machine must render identically.
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        mono: ["ui-monospace", "Consolas", "Menlo", "monospace"],
      },
      borderRadius: {
        DEFAULT: "10px",
        md: "10px",
        lg: "14px",
        xl: "18px",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        DEFAULT: "var(--shadow-sm)",
        md: "var(--shadow-md)",
      },
      transitionDuration: {
        DEFAULT: "220ms",
      },
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0.4, 0, 0.2, 1)",
      },
    },
  },
  plugins: [],
};
