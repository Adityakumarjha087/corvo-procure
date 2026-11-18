/** @type {import('tailwindcss').Config} */
const v = (n) => `rgb(var(--${n}) / <alpha-value>)`;
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), panel: v("panel"), panel2: v("panel2"), line: v("line"), ink: v("ink"), muted: v("muted"), faint: v("faint"),
        accent: v("accent"), accent2: v("accent2"), ok: v("ok"), warn: v("warn"), bad: v("bad"), info: v("info"), vio: v("vio"),
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ["Space Grotesk", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: { card: "0 1px 0 rgb(var(--line) / 0.6), 0 8px 24px -12px rgb(0 0 0 / 0.35)", glow: "0 0 0 1px rgb(var(--accent) / .35), 0 8px 30px -8px rgb(var(--accent) / .35)" },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        pulseDot: { "0%,100%": { opacity: 0.35 }, "50%": { opacity: 1 } },
      },
      animation: { shimmer: "shimmer 1.4s linear infinite", pulseDot: "pulseDot 1.2s ease-in-out infinite" },
    },
  },
  plugins: [],
};
