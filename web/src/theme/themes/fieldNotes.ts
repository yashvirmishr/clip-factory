import type { ThemeDefinition } from '../types'

export const fieldNotes: ThemeDefinition = {
  id: 'field-notes',
  name: 'Field Notes',
  author: 'Clip Factory',
  description: "Sage paper, olive ink and a notebook grid. An outdoorsman's log for long-form storytelling.",
  scheme: 'light',
  tags: ["Organic", "Paper", "Calm"],
  seeds: {
    canvas: '#e3e5d4',
    surface: '#f1f2e3',
    ink: '#24301e',
    accent: '#4d6b33',
    stage: '#10150d',
    stageInk: '#ecebdc',
    ok: '#3d6f48',
    warn: '#85641e',
    danger: '#a7483e',
  },
  fonts: {
    ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
    display: "'Instrument Serif', Georgia, serif",
    mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
  },
  radius: 1,
}
