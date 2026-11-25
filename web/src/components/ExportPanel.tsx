import { Icon } from '../workspace/Icon'

interface Props {
  sourceId: string
  clipCount: number
}

const FORMATS = [
  { id: 'bundle', label: 'Bundle', extension: '.zip', hint: 'Everything below, plus any renders' },
  { id: 'otio', label: 'OTIO', extension: '.otio', hint: 'Resolve, Premiere (adapter), FilmCraft' },
  { id: 'fcpxml', label: 'FCP7 XML', extension: '.xml', hint: 'Native import in Premiere and Resolve' },
  { id: 'edl', label: 'EDL', extension: '.edl', hint: 'Universal fallback; cannot go offline' },
]

/**
 * The handoff is a real file, not a button that says "coming soon".
 *
 * Media is referenced by absolute path — nothing is copied — so the note is
 * there to explain why the import shows an offline clip if the source moved.
 */
export function ExportPanel({ sourceId, clipCount }: Props) {
  return (
    <section className="inspector-section">
      <header className="section-head">
        <div>
          <span className="label">Handoff</span>
          <h3>Send the reel to an editor</h3>
        </div>
        <span className="pill numeric">{clipCount} clips</span>
      </header>
      <div className="section-body stack-10">
        <div className="format-grid">
          {FORMATS.map((format) => (
            <a
              key={format.id}
              className="format-card"
              title={format.hint}
              href={`/api/sources/${sourceId}/export?format=${format.id}`}
              download
            >
              <span className="format-icon">
                <Icon name={format.id === 'bundle' ? 'download' : 'timeline'} size={15} />
              </span>
              <span className="format-copy">
                <b>{format.label}</b>
                <span>{format.extension}</span>
              </span>
              <Icon name="arrow-up-right" size={13} />
            </a>
          ))}
        </div>
        <p className="field-hint">
          A timeline of the whole reel with each hook, plus SRT caption pages. Media is referenced,
          never copied — an offline clip means the source moved.
        </p>
      </div>
    </section>
  )
}
