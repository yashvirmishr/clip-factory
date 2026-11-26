import type { ThemeDefinition } from '../types'

export const silverHalide: ThemeDefinition = {
  id: 'silver-halide',
  name: 'Silver Halide',
  author: 'Clip Factory',
  description: 'Neutral darkroom greys with a safelight red. Monochrome discipline, one warm accent.',
  scheme: 'light',
  tags: ["Monochrome", "Darkroom", "Film"],
  seeds: {
    canvas: '#d9d9d3',
    surface: '#efefe9',
    ink: '#1a1a18',
    accent: '#9e3b2b',
    stage: '#0b0b0a',
    stageInk: '#e9e6dc',
    ok: '#386c55',
    warn: '#84621e',
    danger: '#9e3b2b',
  },
  fonts: {
    ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
    display: "'Instrument Serif', Georgia, serif",
    mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
  },
  radius: 2,
}
