import type { ThemeDefinition } from '../types'

export const blueprint: ThemeDefinition = {
  id: 'blueprint',
  name: 'Blueprint',
  author: 'Clip Factory',
  description: 'Cool drafting paper and petrol ink. A measured, architectural room for structural cuts.',
  scheme: 'light',
  tags: ["Cool", "Studio", "Precise"],
  seeds: {
    canvas: '#dbe4e8',
    surface: '#edf3f4',
    ink: '#11242c',
    accent: '#0d6f86',
    stage: '#071a21',
    stageInk: '#e5f1f0',
    ok: '#237a5c',
    warn: '#8f681e',
    danger: '#b44343',
  },
  fonts: {
    ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
    display: "'Instrument Serif', Georgia, serif",
    mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
  },
  radius: 2,
}
