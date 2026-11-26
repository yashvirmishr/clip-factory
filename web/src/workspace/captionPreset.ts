/**
 * The caption preset is chosen in two places - the subtitle studio and the
 * render panel - and they must agree. One module holds the choice so switching
 * the preset while restyling never leaves the render button on the old style.
 */

const KEY = 'clipper.captionPreset'
const FALLBACK = 'hormozi'

export function getCaptionPreset(): string {
  try {
    return window.localStorage.getItem(KEY) || FALLBACK
  } catch {
    return FALLBACK
  }
}

export function setCaptionPreset(key: string): void {
  try {
    window.localStorage.setItem(KEY, key)
  } catch {
    /* storage disabled; the in-memory choice still drives this session */
  }
}
