/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: {
          primary: '#0a0a0f',
          surface: '#111118',
          elevated: '#16161f',
        },
        border: {
          default: '#1e1e2e',
          subtle: '#2a2a3e',
        },
        accent: {
          DEFAULT: '#6366f1',
          hover: '#4f46e5',
        },
        text: {
          primary: '#f1f5f9',
          secondary: '#94a3b8',
          muted: '#475569',
        },
        green: '#22c55e',
        red: '#ef4444',
        amber: '#f59e0b',
      },
      fontFamily: {
        sans: ['system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
