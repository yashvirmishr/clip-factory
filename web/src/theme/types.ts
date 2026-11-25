export type ThemeScheme = 'light' | 'dark'

export interface ThemeSeeds {
  canvas: string
  surface: string
  ink: string
  accent: string
  stage: string
  stageInk: string
  ok: string
  warn: string
  danger: string
}

export interface ThemeFonts {
  ui: string
  display: string
  mono: string
  /** Optional https://fonts.googleapis.com stylesheet for a custom typeface. */
  stylesheet?: string
}

export interface ThemeDefinition {
  id: string
  name: string
  author: string
  description: string
  scheme: ThemeScheme
  tags: string[]
  seeds: ThemeSeeds
  fonts: ThemeFonts
  radius: number
}

export interface ThemeSettings {
  selectedId: string
  custom: ThemeDefinition[]
}

export interface ThemePackage {
  format: 'clip-factory.theme'
  version: 1
  theme: ThemeDefinition
}

export const THEME_SEED_KEYS: Array<keyof ThemeSeeds> = [
  'canvas',
  'surface',
  'ink',
  'accent',
  'stage',
  'stageInk',
  'ok',
  'warn',
  'danger',
]

export const COLOR_LABELS: Record<keyof ThemeSeeds, string> = {
  canvas: 'Canvas',
  surface: 'Surface',
  ink: 'Ink',
  accent: 'Accent',
  stage: 'Monitor',
  stageInk: 'Monitor text',
  ok: 'Success',
  warn: 'Warning',
  danger: 'Danger',
}

export const COLOR_HINTS: Record<keyof ThemeSeeds, string> = {
  canvas: 'The room behind the panels.',
  surface: 'Toolbars, cards and inspectors.',
  ink: 'Primary type and hairlines.',
  accent: 'Selection, primary actions and the status rail.',
  stage: 'The video well. Keep it dark for colour judgement.',
  stageInk: 'Labels and controls inside the monitor.',
  ok: 'Approvals and healthy states.',
  warn: 'Pending or cautionary states.',
  danger: 'Rejections and destructive actions.',
}
