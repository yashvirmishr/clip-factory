import type { ThemeDefinition } from '../types'

export const cuttingDesk: ThemeDefinition = {
  id: 'cutting-desk',
  name: 'Cutting Desk',
  author: 'Clip Factory',
  description: 'Warm contact-sheet paper, ink and a grease-pencil ultramarine. The original cutting room.',
  scheme: 'light',
  tags: ["Paper", "Editorial", "Default"],
  seeds: {
    canvas: '#e8e3d7',
    surface: '#f4f0e6',
    ink: '#1c231f',
    accent: '#2846d6',
    stage: '#111714',
    stageInk: '#edeadd',
    ok: '#246b4e',
    warn: '#8a6418',
    danger: '#b13b3b',
  },
  fonts: {
    ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
    display: "'Instrument Serif', Georgia, serif",
    mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
  },
  radius: 3,
}
