import type { ThemeDefinition } from '../types'
import { blueprint } from './blueprint'
import { cuttingDesk } from './cuttingDesk'
import { fieldNotes } from './fieldNotes'
import { nightShift } from './nightShift'
import { risograph } from './risograph'
import { silverHalide } from './silverHalide'

/** Built-in marketplace shelf. Add a theme here after creating its definition. */
export const BUILTIN_THEMES: ThemeDefinition[] = [
  cuttingDesk,
  nightShift,
  blueprint,
  risograph,
  fieldNotes,
  silverHalide,
]
