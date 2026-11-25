import { mix, readableOn, withAlpha } from './color'
import type { ThemeDefinition } from './types'

const LIGHT_PAPER = '#fffdf6'
const WHITE = '#ffffff'
const BLACK = '#000000'

/**
 * A theme is a recipe, not a stylesheet. These nine seeds are expanded into
 * every surface, hairline and monitor tone the workspace needs. Keeping the
 * derivation here means a community theme cannot forget an edge case such as
 * a hover border or a muted caption.
 */
export function themeVars(theme: ThemeDefinition): Record<string, string> {
  const dark = theme.scheme === 'dark'
  const { canvas, surface, ink, accent, stage, stageInk, ok, warn, danger } = theme.seeds
  const lightTarget = dark ? WHITE : LIGHT_PAPER

  const panel2 = mix(surface, lightTarget, dark ? 0.06 : 0.55)
  const panel3 = mix(canvas, surface, 0.55)
  const raised = dark ? mix(canvas, WHITE, 0.08) : mix(canvas, ink, 0.03)
  const raised2 = dark ? mix(canvas, WHITE, 0.14) : mix(canvas, ink, 0.1)
  const field = mix(surface, LIGHT_PAPER, dark ? 0.035 : 0.92)
  const menu = mix(surface, panel2, 0.45)
  const paper = mix(surface, lightTarget, dark ? 0.08 : 0.55)
  const paper2 = mix(panel2, lightTarget, dark ? 0.03 : 0.45)
  const wash = mix(dark ? surface : LIGHT_PAPER, accent, dark ? 0.17 : 0.08)
  const washStrong = mix(dark ? surface : LIGHT_PAPER, accent, dark ? 0.26 : 0.14)
  const ink2 = mix(ink, canvas, dark ? 0.2 : 0.27)
  const ink3 = mix(ink, canvas, dark ? 0.32 : 0.37)
  const accentHi = mix(accent, dark ? WHITE : BLACK, dark ? 0.16 : 0.2)
  const onAccent = readableOn(accent)
  const stage2 = mix(stage, WHITE, 0.055)
  const stage3 = mix(stage, BLACK, 0.28)
  const stageAccent = mix(accent, stageInk, 0.32)
  const stageOk = mix(ok, stageInk, 0.35)
  const stageWarn = mix(warn, stageInk, 0.32)
  const stageDanger = mix(danger, stageInk, 0.32)
  const scroll = mix(canvas, ink, dark ? 0.24 : 0.2)
  const scrollHover = mix(canvas, ink, dark ? 0.38 : 0.32)

  return {
    '--bg': canvas,
    '--panel': surface,
    '--panel-2': panel2,
    '--panel-3': panel3,
    '--raised': raised,
    '--raised-2': raised2,
    '--field': field,
    '--menu': menu,
    '--paper': paper,
    '--paper-2': paper2,
    '--wash': wash,
    '--wash-strong': washStrong,
    '--line': withAlpha(ink, 0.13),
    '--line-strong': withAlpha(ink, 0.21),
    '--line-bright': withAlpha(ink, 0.34),
    '--ink': ink,
    '--ink-2': ink2,
    '--ink-3': ink3,
    '--accent': accent,
    '--accent-hi': accentHi,
    '--accent-soft': withAlpha(accent, dark ? 0.16 : 0.1),
    '--accent-line': withAlpha(accent, dark ? 0.42 : 0.32),
    '--on-accent': onAccent,
    '--ok': ok,
    '--ok-soft': withAlpha(ok, dark ? 0.16 : 0.1),
    '--ok-line': withAlpha(ok, dark ? 0.42 : 0.3),
    '--warn': warn,
    '--warn-soft': withAlpha(warn, dark ? 0.18 : 0.12),
    '--warn-line': withAlpha(warn, dark ? 0.44 : 0.34),
    '--danger': danger,
    '--danger-soft': withAlpha(danger, dark ? 0.16 : 0.1),
    '--danger-line': withAlpha(danger, dark ? 0.42 : 0.32),
    '--stage': stage,
    '--stage-2': stage2,
    '--stage-3': stage3,
    '--stage-ink': stageInk,
    '--on-stage': stageInk,
    '--stage-line': withAlpha(stageInk, 0.15),
    '--stage-accent': stageAccent,
    '--stage-ok': stageOk,
    '--stage-warn': stageWarn,
    '--stage-danger': stageDanger,
    '--scroll': scroll,
    '--scroll-hover': scrollHover,
    '--dot': withAlpha(ink, 0.09),
    '--grid': withAlpha(ink, 0.055),
    '--shadow': dark ? 'rgba(0, 0, 0, 0.65)' : 'rgba(0, 0, 0, 0.55)',
    '--toast-bg': stage3,
    '--toast-ink': stageInk,
    '--toast-accent': stageAccent,
    '--toast-ok': stageOk,
    '--toast-danger': stageDanger,
    '--font-ui': theme.fonts.ui,
    '--font-display': theme.fonts.display,
    '--font-mono': theme.fonts.mono,
    '--r': `${Math.max(0, Math.min(12, theme.radius || 0))}px`,
  }
}

export function themeStyle(theme: ThemeDefinition): Record<string, string> {
  return themeVars(theme)
}

export function applyTheme(theme: ThemeDefinition): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  for (const [name, value] of Object.entries(themeVars(theme))) {
    root.style.setProperty(name, value)
  }
  root.dataset.theme = theme.id
  root.dataset.scheme = theme.scheme
  root.style.colorScheme = theme.scheme

  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme.seeds.canvas)

  document.querySelectorAll('link[data-clip-theme-font]').forEach((node) => node.remove())
  const stylesheet = theme.fonts.stylesheet?.trim()
  if (stylesheet && /^https:\/\//i.test(stylesheet)) {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = stylesheet
    link.dataset.clipThemeFont = theme.id
    document.head.append(link)
  }
}
