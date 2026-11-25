import { Icon } from './Icon'
import type { AppCommand } from './types'

export function MenuItemButton({ command, onRun }: { command: AppCommand; onRun: (command: AppCommand) => void }) {
  return (
    <button
      type="button"
      role="menuitem"
      className="menu-item"
      data-danger={command.danger ? 'true' : undefined}
      data-checked={command.checked ? 'true' : undefined}
      disabled={command.disabled}
      onClick={() => onRun(command)}
    >
      <span className="menu-check" aria-hidden="true">
        {command.checked ? <Icon name="check" size={12} /> : null}
      </span>
      <span className="menu-label">{command.label}</span>
      {command.shortcut ? <span className="menu-kbd">{command.shortcut}</span> : null}
    </button>
  )
}
