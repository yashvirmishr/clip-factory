import { useEffect, useRef, useState } from 'react'
import { Icon, type IconName } from './Icon'

/**
 * The rail is the only top-level navigation in the app. Areas own a whole
 * screen; within an area, tabs only switch the content of one pane. Keeping
 * that rule is what stops the three identical tab strips from coming back.
 */
export type Area = 'library' | 'clips' | 'publish'

const AREAS: Array<{ id: Area; label: string; icon: IconName; hint: string }> = [
  { id: 'library', label: 'Library', icon: 'folder', hint: 'Sources, ingest and analysis (Ctrl 1)' },
  { id: 'clips', label: 'Clips', icon: 'film', hint: 'Clip list, monitor and inspector (Ctrl 2)' },
  { id: 'publish', label: 'Publish', icon: 'upload', hint: 'Uploads, accounts and performance (Ctrl 3)' },
]

export interface RailAction {
  id: string
  label: string
  icon: IconName
  onSelect: () => void
}

interface RailProps {
  area: Area
  onChange: (area: Area) => void
  queueCount?: number
  actions: RailAction[]
}

export function Rail({ area, onChange, queueCount = 0, actions }: RailProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const footRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (!footRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  return (
    <nav className="rail" aria-label="Areas">
      {AREAS.map((item) => {
        const active = item.id === area
        const count = item.id === 'publish' ? queueCount : 0
        return (
          <button
            type="button"
            key={item.id}
            className="rail-item"
            data-active={active ? 'true' : undefined}
            aria-current={active ? 'page' : undefined}
            aria-label={item.label}
            title={item.hint}
            onClick={() => onChange(item.id)}
          >
            <span className="rail-icon">
              <Icon name={item.icon} size={19} />
              {count > 0 ? <span className="rail-badge num">{count > 99 ? '99+' : count}</span> : null}
            </span>
            <span className="rail-label">{item.label}</span>
          </button>
        )
      })}

      <div className="rail-foot" ref={footRef}>
        <button
          type="button"
          className="rail-item"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label="Settings"
          title="Settings"
          data-active={menuOpen ? 'true' : undefined}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="rail-icon">
            <Icon name="sliders" size={19} />
          </span>
          <span className="rail-label">Settings</span>
        </button>
        {menuOpen ? (
          <div className="rail-menu" role="menu" aria-label="Settings">
            {actions.map((action) => (
              <button
                type="button"
                key={action.id}
                className="menu-item"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false)
                  action.onSelect()
                }}
              >
                <Icon name={action.icon} size={14} />
                <span>{action.label}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </nav>
  )
}
