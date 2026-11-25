import { normalizeHex, slugify } from './color'
import type { ThemeDefinition, ThemePackage, ThemeSettings, ThemeSeeds, ThemeScheme } from './types'
import { BUILTIN_THEMES } from './themes'

export const THEME_KEY = 'clip-factory.theme.v1'

const DEFAULT_FONTS = {
  ui: "'Familjen Grotesk', 'Segoe UI', system-ui, sans-serif",
  display: "'Instrument Serif', Georgia, serif",
  mono: "'DM Mono', 'Cascadia Mono', ui-monospace, monospace",
}

const DEFAULT_SEEDS: ThemeSeeds = {
  canvas: '#e8e3d7',
  surface: '#f4f0e6',
  ink: '#1c231f',
  accent: '#2846d6',
  stage: '#111714',
  stageInk: '#edeadd',
  ok: '#246b4e',
  warn: '#8a6418',
  danger: '#b13b3b',
}

export const DEFAULT_SETTINGS: ThemeSettings = {
  selectedId: BUILTIN_THEMES[0]?.id ?? 'cutting-desk',
  custom: [],
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function text(value: unknown, fallback: string, max = 120): string {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, max) : fallback
}

function tags(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((tag): tag is string => typeof tag === 'string')
    .map((tag) => tag.trim().slice(0, 18))
    .filter(Boolean)
    .slice(0, 6)
}

function readSeeds(value: unknown): ThemeSeeds | null {
  const source = record(value)
  if (!source) return null
  const seeds = { ...DEFAULT_SEEDS }
  for (const key of Object.keys(DEFAULT_SEEDS) as Array<keyof ThemeSeeds>) {
    const color = typeof source[key] === 'string' ? normalizeHex(source[key]) : null
    if (!color) return null
    seeds[key] = color
  }
  return seeds
}

function readFonts(value: unknown): ThemeDefinition['fonts'] {
  const source = record(value)
  if (!source) return { ...DEFAULT_FONTS }
  const stylesheet = typeof source.stylesheet === 'string' && /^https:\/\//i.test(source.stylesheet)
    ? source.stylesheet.trim().slice(0, 300)
    : undefined
  return {
    ui: text(source.ui, DEFAULT_FONTS.ui, 160),
    display: text(source.display, DEFAULT_FONTS.display, 160),
    mono: text(source.mono, DEFAULT_FONTS.mono, 160),
    ...(stylesheet ? { stylesheet } : {}),
  }
}

/**
 * Coerce an imported or stored object into the small, portable theme schema.
 * Unknown keys are discarded so a theme file can never smuggle markup or CSS
 * into the app.
 */
export function sanitizeTheme(value: unknown): ThemeDefinition | null {
  const source = record(value)
  if (!source) return null
  const seeds = readSeeds(source.seeds)
  if (!seeds) return null
  const scheme: ThemeScheme = source.scheme === 'dark' ? 'dark' : 'light'
  const name = text(source.name, 'Untitled theme', 48)
  const id = typeof source.id === 'string' && /^[a-z0-9][a-z0-9-]{1,48}$/.test(source.id)
    ? source.id
    : `custom-${slugify(name) || 'theme'}`
  const radiusNumber = typeof source.radius === 'number' ? source.radius : 3
  return {
    id,
    name,
    author: text(source.author, 'You', 40),
    description: text(source.description, '', 180),
    scheme,
    tags: tags(source.tags),
    seeds,
    fonts: readFonts(source.fonts),
    radius: Math.max(0, Math.min(12, Math.round(radiusNumber * 2) / 2)),
  }
}

export function sanitizeCustomTheme(value: unknown): ThemeDefinition | null {
  const theme = sanitizeTheme(value)
  if (!theme) return null
  if (!theme.id.startsWith('custom-')) theme.id = `custom-${theme.id}`
  return theme
}

export function allThemes(settings: ThemeSettings): ThemeDefinition[] {
  return [...BUILTIN_THEMES, ...settings.custom]
}

export function sanitizeSettings(value: ThemeSettings): ThemeSettings {
  const custom: ThemeDefinition[] = []
  const seen = new Set(BUILTIN_THEMES.map((theme) => theme.id))
  for (const candidate of Array.isArray(value.custom) ? value.custom : []) {
    const theme = sanitizeCustomTheme(candidate)
    if (!theme) continue
    if (seen.has(theme.id)) {
      theme.id = `custom-${slugify(theme.name) || 'theme'}-${custom.length + 1}`
    }
    seen.add(theme.id)
    custom.push(theme)
  }
  const valid = new Set([...BUILTIN_THEMES, ...custom].map((theme) => theme.id))
  return {
    selectedId: valid.has(value.selectedId) ? value.selectedId : DEFAULT_SETTINGS.selectedId,
    custom,
  }
}

export function makeCustomTheme(base: ThemeDefinition, name = 'Untitled theme'): ThemeDefinition {
  const suffix = Date.now().toString(36).slice(-5)
  return {
    ...base,
    id: `custom-${slugify(name) || 'theme'}-${suffix}`,
    name,
    author: 'You',
    description: base.description,
    tags: base.tags.slice(0, 4),
    seeds: { ...base.seeds },
    fonts: { ...base.fonts },
  }
}

export function uniqueCustomId(theme: ThemeDefinition, current: ThemeDefinition[]): ThemeDefinition {
  const taken = new Set([...BUILTIN_THEMES, ...current].map((item) => item.id))
  if (!taken.has(theme.id) && theme.id.startsWith('custom-')) return theme
  let index = 2
  let id = `custom-${slugify(theme.name) || 'theme'}`
  while (taken.has(id)) {
    id = `custom-${slugify(theme.name) || 'theme'}-${index}`
    index += 1
  }
  return { ...theme, id }
}

export function themePackage(theme: ThemeDefinition): ThemePackage {
  return { format: 'clip-factory.theme', version: 1, theme }
}

export function parseThemeFile(raw: string): { theme?: ThemeDefinition; error?: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { error: 'That file is not valid JSON.' }
  }
  const envelope = record(parsed)
  if (!envelope) return { error: 'The theme file must contain a JSON object.' }
  if (envelope.format !== undefined && envelope.format !== 'clip-factory.theme') {
    return { error: 'Unknown theme format. Expected clip-factory.theme.' }
  }
  const candidate = envelope.theme ?? envelope
  const theme = sanitizeTheme(candidate)
  if (!theme) {
    return { error: 'The theme is missing one or more required colour seeds.' }
  }
  return { theme }
}

export { BUILTIN_THEMES }
