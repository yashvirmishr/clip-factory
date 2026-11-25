import type { Hardware } from '../types'
import { Icon } from '../workspace/Icon'
import { Modal } from '../workspace/Modal'
import { Spinner } from '../workspace/ui'
import { ModelList } from './ModelList'

interface Props {
  hardware: Hardware | null
  error: string | null
  onClose: () => void
  onRefresh: () => void
}

export function SetupModal({ hardware, error, onClose, onRefresh }: Props) {
  return (
    <Modal
      title="Hardware & models"
      eyebrow="Setup"
      onClose={onClose}
      width={820}
      footer={
        <>
          <p className="dialog-note">
            Downloads are resumable and checksummed. Until a model is installed, analysis uses the
            deterministic stub scorer — labelled everywhere it surfaces.
          </p>
          <button type="button" className="btn ghost" onClick={onRefresh}>
            <Icon name="refresh" size={14} />
            Re-probe
          </button>
        </>
      }
    >
      {error ? (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : null}

      {!hardware ? (
        <div className="panel-loading">
          <Spinner label="Probing this machine" />
        </div>
      ) : (
        <div className="setup">
          <section className="tier">
            <div className="tier-stamp">{hardware.advice.tier}</div>
            <div className="tier-copy">
              <span className="label">Recommended tier</span>
              <h3>{hardware.advice.tier_label}</h3>
              <p>{hardware.advice.blurb}</p>
            </div>
            <div className="tier-budget">
              <span className="label">Model budget</span>
              <b className="num">{hardware.advice.model_budget_gb} GB</b>
              <span className="field-hint">after OS + app</span>
            </div>
          </section>

          <section className="setup-section">
            <header className="section-head">
              <div>
                <span className="label">This machine</span>
                <h3>Probe results</h3>
              </div>
            </header>
            <dl className="spec-grid">
              <div>
                <dt>CPU</dt>
                <dd>
                  {hardware.profile.cpu.name || 'Unknown'}
                  <span className="num">{hardware.profile.cpu.logical_cores} threads</span>
                </dd>
              </div>
              <div>
                <dt>Memory</dt>
                <dd>
                  {hardware.profile.memory.total_gb} GB total
                  <span className="num">{hardware.profile.memory.available_gb} GB free</span>
                </dd>
              </div>
              <div>
                <dt>GPU</dt>
                <dd>
                  {hardware.profile.primary_gpu?.name ?? 'None detected'}
                  {hardware.profile.primary_gpu ? (
                    <span className="num">
                      {hardware.profile.primary_gpu.vram_gb} GB · {hardware.profile.primary_gpu.vendor}
                    </span>
                  ) : (
                    <span className="num">CPU fallback</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>Backends</dt>
                <dd className="backend-pills">
                  <span className="pill" data-tone={hardware.profile.vulkan ? 'ok' : undefined}>Vulkan {hardware.profile.vulkan ? 'on' : 'off'}</span>
                  <span className="pill" data-tone={hardware.profile.cuda ? 'ok' : undefined}>CUDA {hardware.profile.cuda ? 'on' : 'off'}</span>
                  <span className="pill" data-tone={hardware.profile.ffmpeg ? 'ok' : 'warn'}>ffmpeg {hardware.profile.ffmpeg ? 'on' : 'missing'}</span>
                </dd>
              </div>
              <div>
                <dt>Disk free</dt>
                <dd className="num">{hardware.profile.disk_free_gb} GB</dd>
              </div>
              <div>
                <dt>Platform</dt>
                <dd>{hardware.profile.os}</dd>
              </div>
            </dl>
          </section>

          <section className="setup-section">
            <header className="section-head">
              <div>
                <span className="label">Models</span>
                <h3>Download · activate</h3>
              </div>
              <span className="field-hint">The largest that fits is recommended</span>
            </header>
            <ModelList />
          </section>

          {hardware.advice.notes.length ? (
            <section className="setup-section">
              <header className="section-head">
                <div>
                  <span className="label">Before your first run</span>
                </div>
              </header>
              <ul className="setup-notes">
                {hardware.advice.notes.map((note) => (
                  <li key={note}>
                    <Icon name="info" size={13} />
                    <span>{note}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
