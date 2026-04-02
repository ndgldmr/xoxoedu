import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ── Brand utilities ───────────────────────────────────────────
      // e.g. bg-brand-primary, text-brand-secondary, hover:bg-brand-primary-hover
      colors: {
        brand: {
          primary:        "var(--brand-primary)",
          "primary-hover":"var(--brand-primary-hover)",
          secondary:      "var(--brand-secondary)",
          dark:           "var(--brand-dark)",
        },
        surface: {
          base:           "var(--surface-base)",
          raised:         "var(--surface-raised)",
          overlay:        "var(--surface-overlay)",
        },
        content: {
          primary:        "var(--content-primary)",
          secondary:      "var(--content-secondary)",
          muted:          "var(--content-muted)",
          inverted:       "var(--content-inverted)",
        },
        border:           "var(--border-color)",
      },

      // ── Typography ────────────────────────────────────────────────
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "monospace"],
      },

      // ── Border radius ─────────────────────────────────────────────
      borderRadius: {
        sm:    "calc(var(--radius) - 2px)",   /* 0.375rem */
        DEFAULT: "var(--radius)",             /* 0.5rem   */
        md:    "var(--radius)",               /* 0.5rem   */
        lg:    "calc(var(--radius) + 2px)",   /* 0.625rem */
        xl:    "calc(var(--radius) + 6px)",   /* 0.875rem */
        "2xl": "calc(var(--radius) + 10px)",  /* 1.125rem */
        full:  "9999px",
      },

      // ── Animations ───────────────────────────────────────────────
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up":   "accordion-up 0.2s ease-out",
        "fade-in":        "fade-in 0.2s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
