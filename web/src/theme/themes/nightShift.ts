import type { ThemeDefinition } from '../types'

export const nightShift: ThemeDefinition = {
  id: 'night-shift',
  name: 'Night Shift',
  author: 'Clip Factory',
  description: 'Graphite, warm white and a single phosphor-lime mark for the late edit. Quietly unorthodox.',
  scheme: 'dark',
  tags: ["Dark", "Focus", "Late"],
  seeds: {
    canvas: '#101318',
    surface: '#171c23',
    ink: '#e7e3d6',
    accent: '#c7f464',
    stage: '#07090c',
    stageInk: '#f1eee6',
    ok: '#7fd4a4',
    warn: '#e0bd65',
    danger: '#ff827a',
  },
  fonts: {
    ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
    display: "'Instrument Serif', Georgia, serif",
    mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
  },
  radius: 2,
}
