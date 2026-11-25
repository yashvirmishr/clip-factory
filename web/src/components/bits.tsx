import type { GateResult, LearnState, ScoreItem } from '../types'
import { Icon } from '../workspace/Icon'

const SIGNALS: Array<{ key: string; label: string }> = [
  { key: 'audio', label: 'Audio' },
  { key: 'chat', label: 'Chat' },
  { key: 'hook_lexicon', label: 'Hook' },
]

export function ScoreBars({ signals }: { signals: Record<string, number> }) {
  return (
    <div className="signal-rows">
      {SIGNALS.map(({ key, label }) => {
        const value = Math.round((signals[key] ?? 0) * 100)
        return (
          <div className="signal-row" key={key}>
            <span className="signal-label">{label}</span>
            <span className="signal-track" aria-hidden="true">
              <i style={{ width: `${value}%` }} data-signal={key} />
            </span>
            <span className="signal-value num">{value}</span>
          </div>
        )
      })}
    </div>
  )
}

export function TruthList({ items }: { items: ScoreItem[] }) {
  if (!items.length) return null
  return (
    <div className="truth-list">
      {items.map((item) => (
        <div className="truth" key={item.id} data-ok={item.passed}>
          <span className="truth-mark" aria-hidden="true">
            <Icon name={item.passed ? 'check' : 'x'} size={12} />
          </span>
          <span className="truth-label">{item.label}</span>
          {item.detail ? <span className="truth-detail">{item.detail}</span> : null}
        </div>
      ))}
    </div>
  )
}

export function GateWarnings({ gates }: { gates: GateResult[] }) {
  const failed = gates.filter((gate) => !gate.passed)
  if (!failed.length) {
    return (
      <p className="panel-note panel-note-ok">
        <Icon name="check" size={13} />
        Every gate passed. Nothing flagged.
      </p>
    )
  }
  return (
    <div className="gate-list">
      {failed.map((gate) => (
        <div className="gate" key={gate.id} data-severity={gate.severity}>
          <Icon name="alert" size={13} />
          <div>
            <b>{gate.id.replace(/_/g, ' ')}</b>
            {gate.detail ? <span>{gate.detail}</span> : null}
          </div>
          <span className="gate-severity">{gate.severity}</span>
        </div>
      ))}
    </div>
  )
}

export function LearningPanel({ learn }: { learn: LearnState | null }) {
  if (!learn) {
    return (
      <section className="panel learning-card">
        <header className="panel-head">
          <span className="label">Model growth</span>
        </header>
        <p className="panel-note">Learning state is unavailable while the sidecar is offline.</p>
      </section>
    )
  }

  const pct = Math.round(learn.progress_to_ranker * 100)
  const remaining = Math.max(0, learn.learning_threshold - learn.decisions)

  return (
    <section className="panel learning-card">
      <header className="panel-head">
        <span className="label">Model growth</span>
        {learn.ranker_active ? (
          <span className="pill ok">
            <i aria-hidden="true" /> ranker live
          </span>
        ) : (
          <span className="pill">
            <span className="num">{learn.decisions}</span>/<span className="num">{learn.learning_threshold}</span>
          </span>
        )}
      </header>
      <div className="panel-body">
        <div
          className="meter"
          role="progressbar"
          aria-label="Progress to a personal re-ranker"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={learn.ranker_active ? 100 : pct}
        >
          <i style={{ width: `${learn.ranker_active ? 100 : pct}%` }} />
        </div>
        <p className="panel-note">
          {learn.ranker_active
            ? `Personal re-ranker is live — held-out AUC ${learn.ranker_holdout_auc?.toFixed(3) ?? '—'} on ${learn.ranker_samples} samples.`
            : `Approve or reject ${remaining} more clips to train your re-ranker.`}
        </p>
        <dl className="learning-stats">
          <div>
            <dt>Approved</dt>
            <dd className="num">{learn.labels.approve}</dd>
          </div>
          <div>
            <dt>Rejected</dt>
            <dd className="num">{learn.labels.reject}</dd>
          </div>
          <div>
            <dt>Hook edits</dt>
            <dd className="num">{learn.hook_edits}</dd>
          </div>
          <div>
            <dt>Approval</dt>
            <dd className="num">
              {learn.quality.decisions ? `${Math.round(learn.quality.approval_rate * 100)}%` : '—'}
            </dd>
          </div>
        </dl>
        {learn.ranker_history.length ? (
          <div className="learning-history">
            <span className="label">AUC history</span>
            <div className="sparkline" aria-hidden="true">
              {learn.ranker_history.slice(-12).map((point) => (
                <i key={point.at} style={{ height: `${Math.max(8, point.auc * 100)}%` }} title={point.auc.toFixed(3)} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
