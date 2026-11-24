import type { Hardware } from '../types'
import { ModelList } from './ModelList'

interface Props {
  hardware: Hardware | null
  error: string | null
  onClose: () => void
  onRefresh: () => void
}

export function SetupModal({ hardware, error, onClose, onRefresh }: Props) {
  return (
    <div
      className="scrim"
      onClick={onClose}
      role="presentation"
    >
      <div className="modal" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <header className="modal-head">
          <span className="label" style={{ color: 'var(--ink-2)' }}>
            Hardware &amp; models
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button type="button" className="btn sm ghost" onClick={onRefresh}>
              Re-probe
            </button>
            <button type="button" className="btn sm" onClick={onClose}>
              Close
            </button>
          </div>
        </header>

        <div className="modal-body">
          {error ? <p className="warn-line">{error}</p> : null}
          {!hardware ? (
            <p className="panel-note">Probing this machine…</p>
          ) : (
            <>
              <div className="tier">
                <div className="tier-stamp">{hardware.advice.tier}</div>
                <div>
                  <div className="tier-name">{hardware.advice.tier_label}</div>
                  <div className="tier-blurb">{hardware.advice.blurb}</div>
                </div>
              </div>

              <div className="spec-table">
                <div>CPU</div>
                <div>
                  {hardware.profile.cpu.name || 'unknown'} · {hardware.profile.cpu.logical_cores} threads
                </div>
                <div>Memory</div>
                <div>
                  {hardware.profile.memory.total_gb} GB total · {hardware.profile.memory.available_gb} GB free
                </div>
                <div>GPU</div>
                <div>
                  {hardware.profile.primary_gpu
                    ? `${hardware.profile.primary_gpu.name} · ${hardware.profile.primary_gpu.vram_gb} GB · ${hardware.profile.primary_gpu.vendor}`
                    : 'none detected'}
                </div>
                <div>Backends</div>
                <div>
                  vulkan {hardware.profile.vulkan ? 'yes' : 'no'} · cuda{' '}
                  {hardware.profile.cuda ? 'yes' : 'no'} · ffmpeg{' '}
                  {hardware.profile.ffmpeg ? 'yes' : 'no'}
                </div>
                <div>Disk free</div>
                <div>{hardware.profile.disk_free_gb} GB</div>
                <div>Model budget</div>
                <div>{hardware.advice.model_budget_gb} GB usable after the OS and this app</div>
              </div>

              <div className="panel">
                <header className="panel-head">
                  <span className="label">Models</span>
                  <span className="mono" style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-3)' }}>
                    download · use
                  </span>
                </header>
                <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <ModelList />
                </div>
              </div>

              <div className="panel">
                <header className="panel-head">
                  <span className="label">Before your first run</span>
                </header>
                <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                  {hardware.advice.notes.map((note) => (
                    <div className="panel-note" key={note}>
                      · {note}
                    </div>
                  ))}
                </div>
              </div>

              <p className="panel-note" style={{ color: 'var(--ink-3)' }}>
                Downloads are resumable and every file gets a local SHA-256 so a truncated download
                is caught on the next run. Until a model is installed, analysis runs with the
                deterministic stub scorer, which is labelled everywhere it surfaces.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
