/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./src/**/*.{html,ts}",
  ],
  theme: {
    borderRadius: {
      DEFAULT: '0',
      none: '0',
      sm: '0',
      md: '0',
      lg: '0',
      xl: '0',
      '2xl': '0',
      '3xl': '0',
      full: '0',
    },
    extend: {
      colors: {
        canvas: 'var(--bg-canvas)',
        surface: 'var(--bg-surface)',
        'surface-sunken': 'var(--bg-surface-sunken)',
        'border-default': 'var(--border-default)',
        'border-strong': 'var(--border-strong)',
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'accent-action': 'var(--accent-action)',
        'accent-action-hover': 'var(--accent-action-hover)',
        'tier-1': 'var(--tier-1)',
        'tier-2': 'var(--tier-2)',
        'tier-3': 'var(--tier-3)',
        'tier-4': 'var(--tier-4)',
        'status-amber': 'var(--status-amber)',
        'status-amber-bg': 'var(--status-amber-bg)',
        'status-red': 'var(--status-red)',
        'status-red-bg': 'var(--status-red-bg)',
        'status-green': 'var(--status-green)',
        'status-green-bg': 'var(--status-green-bg)',
      },
      fontFamily: {
        sans: ['IBM Plex Sans', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['IBM Plex Mono', 'Consolas', 'Monaco', 'monospace'],
      },
      fontSize: {
        'data': ['13px', '1.5'],
        'label': ['13px', '1.4'],
        'heading': ['18px', '1.3'],
        'page-title': ['20px', '1.25'],
      },
    },
  },
  plugins: [],
}
