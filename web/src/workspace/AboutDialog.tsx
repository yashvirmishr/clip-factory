import { useState } from 'react'
import { api } from '../api'
import { Modal } from './Modal'
import { Icon } from './Icon'

async function copyText(text: string): Promise<boolean> {
  // The desktop shell exposes a write-only clipboard bridge; browsers use the
  // async clipboard, then the selection fallback.
  try {
    if (window.clipFactory?.copyText) {
      await window.clipFactory.copyText(text)
      return true
    }
  } catch {
    /* fall through */
  }
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Clipboard permissions vary in a hardened shell. Fall back to the
    // selection API so "Copy diagnostics" still works.
    const area = document.createElement('textarea')
    area.value = text
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    try {
      return document.execCommand('copy')
    } catch {
      return false
    } finally {
      area.remove()
    }
  }
}

export function AboutDialog({
  version,
  onClose,
  onOpenShortcuts,
}: {
  version: string
  onClose: () => void
  onOpenShortcuts: () => void
}) {
  const [diagnostics, setDiagnostics] = useState<'idle' | 'copying' | 'copied' | 'error'>('idle')
  const [report, setReport] = useState<string | null>(null)

  const copyDiagnostics = async () => {
    setDiagnostics('copying')
    try {
      const snapshot = await api.diagnostics()
      const text = JSON.stringify(snapshot, null, 2)
      setReport(text)
      const ok = await copyText(text)
      setDiagnostics(ok ? 'copied' : 'error')
      if (ok) window.setTimeout(() => setDiagnostics('idle'), 2200)
    } catch {
      setDiagnostics('error')
    }
  }

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
          <button
            type="button"
            className="btn ghost"
            onClick={() => void copyDiagnostics()}
            disabled={diagnostics === 'copying'}
            title="Version, paths, disk space and recent jobs for a bug report"
          >
            <Icon name="copy" size={14} />
            {diagnostics === 'copied' ? 'Copied' : diagnostics === 'error' ? 'Copy failed' : 'Copy diagnostics'}
          </button>
          <span className="dialog-note">Version {version}</span>
        </>
      }
    >
      <div className="about-lockup">
        <img className="brand-mark brand-mark-lg" src="/brand/clip-factory-mark-color.png" alt="" width={56} height={56} />
        <div>
          <p className="about-kicker">Local-first clip finding</p>
          <p className="about-copy">
            A cutting room that runs on your machine. Ingest a stream, let the pipeline find the
            moments worth keeping, then review, trim and hand the reel to your editor.
          </p>
        </div>
      </div>
      <dl className="about-facts">
        <div>
          <dt>Pipeline</dt>
          <dd>Audio → words → moments → checks → score</dd>
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
      {report && diagnostics === 'error' ? (
        <div className="diagnostics-fallback">
          <p className="warn-line">
            <Icon name="alert" size={13} />
            Clipboard access is blocked here. Select the report and copy it manually.
          </p>
          <pre>{report}</pre>
        </div>
      ) : null}
    </Modal>
  )
}
