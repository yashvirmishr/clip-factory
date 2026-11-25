import { Modal } from './Modal'
import { Icon } from './Icon'

export function AboutDialog({
  version,
  onClose,
  onOpenShortcuts,
}: {
  version: string
  onClose: () => void
  onOpenShortcuts: () => void
}) {
  return (
    <Modal
      title="Clip Factory"
      eyebrow="About"
      onClose={onClose}
      width={560}
      footer={
        <>
          <button type="button" className="btn ghost" onClick={onOpenShortcuts}>
            <Icon name="keyboard" size={14} />
            Keyboard shortcuts
          </button>
          <span className="dialog-note">Version {version}</span>
        </>
      }
    >
      <div className="about-lockup">
        <img className="brand-mark brand-mark-lg" src="/brand/clip-factory-mark-color.png" alt="" width={56} height={56} />
        <div>
          <p className="about-kicker">Local-first clip triage</p>
          <p className="about-copy">
            A cutting room that runs on your machine. Ingest a stream, let the pipeline find the
            moments worth keeping, then review, trim and hand the reel to your editor.
          </p>
        </div>
      </div>
      <dl className="about-facts">
        <div>
          <dt>Pipeline</dt>
          <dd>Audio → transcript → signals → gates → score</dd>
        </div>
        <div>
          <dt>Privacy</dt>
          <dd>Transcription, detection and scoring never leave this machine.</dd>
        </div>
        <div>
          <dt>Handoff</dt>
          <dd>Premiere XML, Final Cut XML, OTIO, SRT and a rendered 9:16 bundle.</dd>
        </div>
      </dl>
      <p className="dialog-note about-note">
        The only model is the one you install. Until then the deterministic stub scorer is labelled
        everywhere it surfaces.
      </p>
    </Modal>
  )
}
