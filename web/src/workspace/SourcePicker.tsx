import { useEffect, useRef, useState } from 'react'
import { formatTime } from '../api'
import type { SourceRow } from '../types'
import { Icon } from './Icon'

interface SourcePickerProps {
  sources: SourceRow[]
  selectedId: string | null
  onSelect: (source: SourceRow) => void
  onOpenLibrary: () => void
}

/**
 * The source switcher lives in the Clips header now that the bin is its own
 * area. Same reach, one fewer permanent column.
 */
export function SourcePicker({ sources, selectedId, onSelect, onOpenLibrary }: SourcePickerProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = sources.find((source) => source.id === selectedId) ?? null

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="source-picker" ref={rootRef}>
      <button
        type="button"
        className="source-picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={selected ? `Source: ${selected.name}. Switch source.` : 'Choose a source'}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="film" size={14} />
        <span className="source-picker-name" title={selected?.name ?? 'No source'}>
          {selected?.name ?? 'No source'}
        </span>
        {selected ? <span className="source-picker-time num">{formatTime(selected.duration)}</span> : null}
        <Icon name="chevron-down" size={13} />
      </button>

      {open ? (
        <div className="source-picker-pop" role="listbox" aria-label="Sources">
          <div className="source-picker-list">
            {sources.length === 0 ? (
              <p className="panel-empty">No sources yet.</p>
            ) : (
              sources.map((source) => (
                <button
                  type="button"
                  key={source.id}
                  role="option"
                  aria-selected={source.id === selectedId}
                  className="source-picker-row"
                  data-active={source.id === selectedId ? 'true' : undefined}
                  onClick={() => {
                    onSelect(source)
                    setOpen(false)
                  }}
                >
                  <span className="source-picker-row-name">{source.name}</span>
                  <span className="source-picker-row-meta num">
                    {formatTime(source.duration)}
                    <span aria-hidden="true"> · </span>
                    {source.clip_count} clips
                  </span>
                  {source.analyzed ? <span className="source-ready" title="Analyzed"><i aria-hidden="true" /></span> : null}
                </button>
              ))
            )}
          </div>
          <button
            type="button"
            className="source-picker-foot"
            onClick={() => {
              setOpen(false)
              onOpenLibrary()
            }}
          >
            <Icon name="folder" size={14} />
            Open library
            <Icon name="chevron-right" size={13} />
          </button>
        </div>
      ) : null}
    </div>
  )
}
