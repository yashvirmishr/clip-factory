import { useState } from 'react'
import { api } from '../api'
import type { SourceInfo, SourceRow } from '../types'
import { Modal } from '../workspace/Modal'
import './library.css'

interface RemoveDialogProps {
  source: SourceRow
  onClose: () => void
  onRemoved: (fileDeleted: boolean, warnings: string[]) => void
}

/**
 * Removing a source is the one destructive action in the library, so it asks
 * once and says exactly what survives: rendered files and published posts stay;
 * the analysis and clip edits go with the source.
 */
export function RemoveDialog({ source, onClose, onRemoved }: RemoveDialogProps) {
  const [deleteFile, setDeleteFile] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const removable = source.deletable && source.available

  const confirm = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.deleteSource(source.id, deleteFile && removable)
      onRemoved(result.file_deleted, result.warnings ?? [])
    } catch (problem) {
      setError((problem as Error).message)
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`Remove “${source.name}”?`}
      eyebrow="Library"
      onClose={onClose}
      width={560}
      footer={
        <>
          <button type="button" className="btn ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn danger"
            onClick={() => void confirm()}
            disabled={busy}
            data-autofocus
          >
            {busy ? 'Removing…' : deleteFile && removable ? 'Delete file and remove' : 'Remove source'}
          </button>
        </>
      }
    >
      <div className="source-dialog">
        <p>
          The analysis, clip picks and caption edits for this source are removed. Renders
          already on disk and published posts are kept.
        </p>
        <p className="source-dialog-path">{source.path}</p>

        {removable ? (
          <label className="source-dialog-check">
            <input
              type="checkbox"
              checked={deleteFile}
              onChange={(event) => setDeleteFile(event.target.checked)}
              disabled={busy}
            />
            <span>
              Also delete the video file
              <em>It is in the app&apos;s media folder, so it can be removed with the source.</em>
            </span>
          </label>
        ) : (
          <p className="source-dialog-note">
            {source.available
              ? 'The file is outside the app’s media folder, so it is left on disk. Delete it yourself if you no longer need it.'
              : 'The file is already missing from disk, so there is nothing to delete.'}
          </p>
        )}

        {error ? <p className="source-dialog-error">{error}</p> : null}
      </div>
    </Modal>
  )
}

interface RelinkDialogProps {
  source: SourceRow
  onClose: () => void
  onRelinked: (updated: SourceInfo) => void
}

/** Point a source at the file's new home without paying for a second analysis. */
export function RelinkDialog({ source, onClose, onRelinked }: RelinkDialogProps) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const confirm = async () => {
    const target = path.trim()
    if (!target) {
      setError('Paste the file’s new location first.')
      return
    }
    setBusy(true)
    setError('')
    try {
      onRelinked(await api.relinkSource(source.id, target))
    } catch (problem) {
      setError((problem as Error).message)
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`Find “${source.name}”`}
      eyebrow="Library"
      onClose={onClose}
      width={600}
      footer={
        <>
          <button type="button" className="btn ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => void confirm()} disabled={busy}>
            {busy ? 'Checking…' : 'Relink file'}
          </button>
        </>
      }
    >
      <div className="source-dialog">
        <p>
          Point this source at the moved file. Its analysis, clip picks and edits stay,
          so nothing needs to be transcribed again.
        </p>
        <p className="source-dialog-path">Last seen at {source.path}</p>
        <label className="source-dialog-field">
          <span>New file path</span>
          <input
            value={path}
            type="text"
            onChange={(event) => setPath(event.target.value)}
            placeholder="C:\Videos\stream.mp4"
            spellCheck={false}
            autoComplete="off"
            data-autofocus
            disabled={busy}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void confirm()
            }}
          />
        </label>
        <p className="source-dialog-note">
          The file has to be the same recording; a different length is refused so
          captions cannot drift out of sync.
        </p>
        {error ? <p className="source-dialog-error">{error}</p> : null}
      </div>
    </Modal>
  )
}
