interface Props {
  sourceId: string
  clipCount: number
}

const FORMATS = [
  { id: 'bundle', label: 'Bundle (.zip)', hint: 'Everything below, plus any renders' },
  { id: 'otio', label: 'OTIO', hint: 'Resolve, Premiere (adapter), FilmCraft' },
  { id: 'fcpxml', label: 'FCP7 XML', hint: 'Native import in Premiere and Resolve' },
  { id: 'edl', label: 'EDL', hint: 'Universal fallback; cannot go offline' },
]

/**
 * The handoff is a real file, not a button that says "coming soon".
 *
 * Media is referenced by absolute path — nothing is copied — so the note is
 * there to explain why the import shows an offline clip if the source moved.
 */
export function ExportPanel({ sourceId, clipCount }: Props) {
  return (
    <section className="panel">
      <header className="panel-head">
        <span className="label" style={{ color: 'var(--ink-2)' }}>
          Send to editor
        </span>
        <span className="mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>
          {clipCount} clips
        </span>
      </header>
      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div className="chip-row">
          {FORMATS.map((format) => (
            <a
              key={format.id}
              className="chip"
              title={format.hint}
              href={`/api/sources/${sourceId}/export?format=${format.id}`}
              download
              style={{ textDecoration: 'none' }}
            >
              {format.label}
            </a>
          ))}
        </div>
        <span className="mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>
          A timeline of the whole reel with the hook on each clip, plus SRT caption
          pages. Media is referenced, never copied — if a clip opens offline the
          source file moved.
        </span>
      </div>
    </section>
  )
}
