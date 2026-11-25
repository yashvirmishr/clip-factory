import type { ThemeDefinition } from '../types'

export const risograph: ThemeDefinition = {
  id: 'risograph',
  name: 'Risograph',
  author: 'Clip Factory',
  description: 'Blush stock, blackberry ink and a riso-pink marker. For hooks that deserve a little theatre.',
  scheme: 'light',
  tags: ["Print", "Playful", "Warm"],
  seeds: {
    canvas: '#f0dcdd',
    surface: '#faede9',
    ink: '#2a1a22',
    accent: '#b93a5c',
    stage: '#1b1117',
    stageInk: '#f7e8e7',
    ok: '#2f745d',
    warn: '#91651f',
    danger: '#b23a45',
  },
  fonts: {
    ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
    display: "'Instrument Serif', Georgia, serif",
    mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
  },
  radius: 4,
}
