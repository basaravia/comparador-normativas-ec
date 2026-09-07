/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "var(--color-primary, #1e40af)",
          hover: "var(--color-primary-hover, #1d4ed8)",
          light: "var(--color-primary-light, #eff6ff)",
        },
        accent: "var(--color-accent, #3b82f6)",
        surface: "var(--color-surface, #ffffff)",
        canvas: "var(--color-background, #f8fafc)",
        border: "var(--color-border, #e2e8f0)",
        content: {
          main: "var(--color-text-main, #0f172a)",
          muted: "var(--color-text-muted, #64748b)",
        },
        estado: {
          cumple: {
            bg: "var(--color-state-cumple-bg, #dcf0e0)",
            fg: "var(--color-state-cumple-fg, #15803d)",
          },
          parcial: {
            bg: "var(--color-state-parcial-bg, #fff2cc)",
            fg: "var(--color-state-parcial-fg, #b45309)",
          },
          omision: {
            bg: "var(--color-state-omision-bg, #fce8e6)",
            fg: "var(--color-state-omision-fg, #b91c1c)",
          },
          no_aplica: {
            bg: "var(--color-state-no-aplica-bg, #f3f4f6)",
            fg: "var(--color-state-no-aplica-fg, #737373)",
          },
        },
      },
      screens: {
        'ipad': '768px',
        'ipad-pro': '1024px',
      },
    },
  },
  plugins: [],
}
