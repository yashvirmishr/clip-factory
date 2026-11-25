import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'
import type { AppCommand } from './types'

interface CommandPaletteProps {
  open: boolean
  commands: AppCommand[]
  onRun: (command: AppCommand) => void
  onClose: () => void
}

export function CommandPalette({ open, commands, onRun, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const available = useMemo(() => commands.filter((command) => !command.disabled), [commands])

  const results = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    if (!tokens.length) return available
    return available.filter((command) => {
      const haystack = `${command.label} ${command.group} ${command.keywords ?? ''}`.toLowerCase()
      return tokens.every((token) => haystack.includes(token))
    })
  }, [available, query])

  const groups = useMemo(() => {
    const map = new Map<string, Array<{ command: AppCommand; index: number }>>()
    results.forEach((command, index) => {
      const list = map.get(command.group) ?? []
      list.push({ command, index })
      map.set(command.group, list)
    })
    return Array.from(map.entries())
  }, [results])

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    setQuery('')
    setActive(0)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 20)
    return () => {
      window.clearTimeout(timer)
      previous?.focus?.()
    }
  }, [open])

  useEffect(() => {
    setActive(0)
  }, [query])

  useEffect(() => {
    if (!open) return
    const node = document.getElementById(`command-option-${active}`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [active, open, query])

  if (!open) return null

  const run = (command: AppCommand) => {
    onRun(command)
    onClose()
  }

  const key = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((current) => (results.length ? (current + 1) % results.length : 0))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((current) => (results.length ? (current - 1 + results.length) % results.length : 0))
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      setActive(0)
      return
    }
    if (event.key === 'End') {
      event.preventDefault()
      setActive(Math.max(0, results.length - 1))
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const command = results[active]
      if (command) run(command)
    }
  }

  return createPortal(
    <div
      className="palette-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="palette-search">
          <Icon name="search" size={16} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={key}
            placeholder="Search commands, panels and clip actions…"
            role="combobox"
            aria-expanded="true"
            aria-controls="command-list"
            aria-autocomplete="list"
            aria-activedescendant={results.length ? `command-option-${active}` : undefined}
            spellCheck={false}
          />
          <kbd className="kbd">Esc</kbd>
        </div>

        <div className="palette-list" id="command-list" role="listbox" aria-label="Commands">
          {results.length === 0 ? (
            <p className="palette-empty">No command matches “{query.trim()}”.</p>
          ) : (
            groups.map(([group, entries]) => (
              <div className="palette-group" key={group} role="presentation">
                <p className="palette-group-label" role="presentation">
                  {group}
                </p>
                {entries.map(({ command, index }) => (
                  <button
                    type="button"
                    key={command.id}
                    id={`command-option-${index}`}
                    role="option"
                    aria-selected={index === active}
                    className="palette-item"
                    data-active={index === active ? 'true' : undefined}
                    tabIndex={-1}
                    onPointerEnter={() => setActive(index)}
                    onClick={() => run(command)}
                  >
                    <span className="palette-icon">
                      {command.icon ? <Icon name={command.icon} size={15} /> : null}
                    </span>
                    <span className="palette-label">{command.label}</span>
                    {command.checked ? <Icon name="check" size={13} /> : null}
                    {command.shortcut ? <span className="palette-kbd">{command.shortcut}</span> : null}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>

        <footer className="palette-footer">
          <span><kbd className="kbd">↑</kbd><kbd className="kbd">↓</kbd> navigate</span>
          <span><kbd className="kbd">↵</kbd> run</span>
          <span><kbd className="kbd">esc</kbd> close</span>
          <span className="palette-count num">{results.length} commands</span>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
