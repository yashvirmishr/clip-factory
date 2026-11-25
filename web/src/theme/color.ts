function clampChannel(value: number): number {
  return Math.max(0, Math.min(255, Math.round(value)))
}

export function normalizeHex(input: string): string | null {
  const value = input.trim().toLowerCase()
  if (/^#[0-9a-f]{6}$/.test(value)) return value
  if (/^#[0-9a-f]{3}$/.test(value)) {
    return `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`
  }
  return null
}

export function isHex(input: string): boolean {
  return normalizeHex(input) !== null
}

export function hexToRgb(input: string): { r: number; g: number; b: number } {
  const hex = normalizeHex(input) ?? '#000000'
  return {
    r: parseInt(hex.slice(1, 3), 16),
    g: parseInt(hex.slice(3, 5), 16),
    b: parseInt(hex.slice(5, 7), 16),
  }
}

export function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b].map((channel) => clampChannel(channel).toString(16).padStart(2, '0')).join('')}`
}

/** Mix 0..1 of b into a. */
export function mix(a: string, b: string, amount: number): string {
  const start = hexToRgb(a)
  const end = hexToRgb(b)
  const t = Math.max(0, Math.min(1, amount))
  return rgbToHex(
    start.r + (end.r - start.r) * t,
    start.g + (end.g - start.g) * t,
    start.b + (end.b - start.b) * t,
  )
}

export function withAlpha(input: string, alpha: number): string {
  const { r, g, b } = hexToRgb(input)
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha)).toFixed(3)})`
}

export function relativeLuminance(input: string): number {
  const { r, g, b } = hexToRgb(input)
  const channels = [r, g, b].map((channel) => {
    const value = channel / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

export function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(a)
  const second = relativeLuminance(b)
  const light = Math.max(first, second)
  const dark = Math.min(first, second)
  return (light + 0.05) / (dark + 0.05)
}

const LIGHT_INK = '#fffdf6'
const DARK_INK = '#141711'

export function readableOn(background: string): string {
  return contrastRatio(background, LIGHT_INK) >= contrastRatio(background, DARK_INK) ? LIGHT_INK : DARK_INK
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 36)
}

export function formatRatio(value: number): string {
  return `${value.toFixed(value >= 10 ? 0 : 1)}:1`
}
