import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export interface TabDefinition {
  id: string
  label: string
  icon?: IconName
  badge?: ReactNode
  title?: string
}

interface TabsProps {
  items: TabDefinition[]
  value: string
  onChange: (id: string) => void
  ariaLabel: string
  variant?: 'workspace' | 'panel'
  idPrefix: string
}

export function Tabs({ items, value, onChange, ariaLabel, variant = 'workspace', idPrefix }: TabsProps) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])

  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index
    if (event.key === 'ArrowRight') next = (index + 1) % items.length
    else if (event.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    else return
    event.preventDefault()
    onChange(items[next].id)
    refs.current[next]?.focus()
  }

  return (
    <div className={`tabs tabs-${variant}`} role="tablist" aria-label={ariaLabel}>
      {items.map((item, index) => {
        const selected = item.id === value
        return (
          <button
            type="button"
            key={item.id}
            ref={(node) => {
              refs.current[index] = node
            }}
            id={`${idPrefix}-tab-${item.id}`}
            className="tab"
            role="tab"
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            title={item.title ?? item.label}
            data-active={selected ? 'true' : undefined}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => move(event, index)}
          >
            {item.icon ? <Icon name={item.icon} size={13} /> : null}
            <span className="tab-label">{item.label}</span>
            {item.badge !== undefined ? <span className="tab-badge">{item.badge}</span> : null}
          </button>
        )
      })}
    </div>
  )
}
