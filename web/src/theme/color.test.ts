import { describe, expect, it } from 'vitest'
import {
  contrastRatio,
  formatRatio,
  mix,
  normalizeHex,
  readableOn,
} from './color'

describe('colour helpers', () => {
  it('normalises short and long hex values', () => {
    expect(normalizeHex('#ABC')).toBe('#aabbcc')
    expect(normalizeHex(' #0f0f0f ')).toBe('#0f0f0f')
    expect(normalizeHex('not a colour')).toBeNull()
  })

  it('mixes towards the second colour', () => {
    expect(mix('#000000', '#ffffff', 0.5)).toBe('#808080')
    expect(mix('#000000', '#ffffff', 2)).toBe('#ffffff')
  })

  it('knows black on white is the maximum ratio', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 1)
  })

  it('picks a readable ink for light and dark surfaces', () => {
    expect(readableOn('#ffffff')).toBe('#141711')
    expect(readableOn('#111111')).toBe('#fffdf6')
  })

  it('formats ratios with one decimal below ten', () => {
    expect(formatRatio(21)).toBe('21:1')
    expect(formatRatio(4.5)).toBe('4.5:1')
  })
})
