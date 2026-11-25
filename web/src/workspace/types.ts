import type { IconName } from './Icon'

/** One command registry powers the menu bar, context menus and palette. */
export interface AppCommand {
  id: string
  label: string
  group: string
  shortcut?: string
  icon?: IconName
  keywords?: string
  disabled?: boolean
  checked?: boolean
  danger?: boolean
  run: () => void
}

export interface MenuDefinition {
  id: string
  label: string
  /** Command ids; '-' renders a separator. */
  items: string[]
}
