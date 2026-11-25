import { useCallback, useLayoutEffect, useMemo } from 'react'
import { applyTheme } from './compile'
import {
  BUILTIN_THEMES,
  DEFAULT_SETTINGS,
  makeCustomTheme,
  sanitizeCustomTheme,
  sanitizeSettings,
  THEME_KEY,
  uniqueCustomId,
} from './index'
import type { ThemeDefinition, ThemeSettings } from './types'
import { usePersistentState } from '../workspace/usePersistentState'

export function useTheme() {
  const [stored, setStored] = usePersistentState<ThemeSettings>(THEME_KEY, DEFAULT_SETTINGS)
  const settings = useMemo(() => sanitizeSettings(stored), [stored])
  const themes = useMemo(() => [...BUILTIN_THEMES, ...settings.custom], [settings.custom])
  const activeTheme = useMemo(
    () => themes.find((theme) => theme.id === settings.selectedId) ?? BUILTIN_THEMES[0],
    [settings.selectedId, themes],
  )

  useLayoutEffect(() => {
    applyTheme(activeTheme)
  }, [activeTheme])

  const useThemeById = useCallback((id: string) => {
    setStored((current) => {
      const safe = sanitizeSettings(current)
      if (![...BUILTIN_THEMES, ...safe.custom].some((theme) => theme.id === id)) return safe
      return { ...safe, selectedId: id }
    })
  }, [setStored])

  const createCustom = useCallback((base: ThemeDefinition, name?: string) => {
    const next = makeCustomTheme(base, name)
    setStored((current) => {
      const safe = sanitizeSettings(current)
      return { selectedId: next.id, custom: [...safe.custom, next] }
    })
    return next
  }, [setStored])

  const saveCustom = useCallback((theme: ThemeDefinition) => {
    const safeTheme = sanitizeCustomTheme(theme)
    if (!safeTheme) return
    setStored((current) => {
      const safe = sanitizeSettings(current)
      const exists = safe.custom.some((item) => item.id === safeTheme.id)
      return {
        ...safe,
        custom: exists
          ? safe.custom.map((item) => (item.id === safeTheme.id ? safeTheme : item))
          : [...safe.custom, uniqueCustomId(safeTheme, safe.custom)],
      }
    })
  }, [setStored])

  const deleteCustom = useCallback((id: string) => {
    setStored((current) => {
      const safe = sanitizeSettings(current)
      const custom = safe.custom.filter((theme) => theme.id !== id)
      return {
        selectedId: safe.selectedId === id ? DEFAULT_SETTINGS.selectedId : safe.selectedId,
        custom,
      }
    })
  }, [setStored])

  return {
    settings,
    themes,
    customThemes: settings.custom,
    activeTheme,
    useThemeById,
    createCustom,
    saveCustom,
    deleteCustom,
  }
}
