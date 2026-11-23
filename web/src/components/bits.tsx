import type { GateResult, LearnState, ScoreItem } from '../types'

const SIGNAL_LABELS: Record<string, string> = {
  audio: 'AUD',
  chat: 'CHAT',
  hook_lexicon: 'HOOK',
}

export function ScoreBars({ signals }: { signals: Record<string, number> }) {
  const keys = ['audio', 'chat', 'hook_lexicon']
  return (
    <>
      <div className="bars">
        {keys.map((key) => (
          <span className="bar" key={key} data-key={key}>
            <i style={{ width: `${Math.round((signals[key] ?? 0) * 100)}%` }} />
          </span>
        ))}
      </div>
      <div className="bars-legend">
        {keys.map((key) => (
          <span key={key}>{SIGNAL_LABELS[key]}</span>
        ))}
      </div>
    </>
  )
}

export function TruthList({ items }: { items: ScoreItem[] }) {
  if (!items.length) return null
  return (
    <div className="truth-list">
      {items.map((item) => (
        <div className="truth" key={item.id} data-ok={item.passed}>
          <span className="mark">{item.passed ? '✓' : '✕'}</span>
          <span>{item.label}</span>
          {item.detail ? <span className="detail">{item.detail}</span> : null}
        </div>
      ))}
    </div>
  )
}

export function GateWarnings({ gates }: { gates: GateResult[] }) {
  const failed = gates.filter((gate) => !gate.passed)
  if (!failed.length) {
    return <div className="panel-note">Every gate passed. Nothing flagged.</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {failed.map((gate) => (
        <div className="warn-line" key={gate.id}>
          <span className="mono" style={{ fontSize: 10, opacity: 0.7 }}>
            {gate.severity === 'block' ? '■' : '▲'}
          </span>
          <span>
            <b style={{ fontWeight: 500, color: 'inherit' }}>{gate.id.replace(/_/g, ' ')}</b>
            {gate.detail ? ` — ${gate.detail}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}

export function Panel({
  title,
  aside,
  children,
}: {
  title: string
  aside?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <span className="label" style={{ color: 'var(--ink-2)' }}>
          {title}
        </span>
        {aside ? <div style={{ marginLeft: 'auto' }}>{aside}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function LearningPanel({ learn }: { learn: LearnState | null }) {
  if (!learn) return null
  const pct = Math.round(learn.progress_to_ranker * 100)
  const auc = learn.ranker_holdout_auc
  return (
    <section className="panel">
      <header className="panel-head">
        <span className="label" style={{ color: 'var(--ink-2)' }}>
          Model growth
        </span>
        <span style={{ marginLeft: 'auto' }}>
          {learn.ranker_active ? (
            <span className="pill ok">ranker live</span>
          ) : (
            <span className="pill">{learn.decisions}/{learn.learning_threshold}</span>
          )}
        </span>
      </header>
      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="meter">
          <i style={{ width: `${learn.ranker_active ? 100 : pct}%` }} />
        </div>
        <p className="panel-note" style={{ margin: 0 }}>
          {learn.ranker_active
            ? `Personal re-ranker is live — held-out AUC ${auc?.toFixed(3) ?? '—'}.`
            : `Approve or reject ${Math.max(0, learn.learning_threshold - learn.decisions)} more clips to train your re-ranker.`}
        </p>
        <div className="stat-grid" style={{ margin: '0 -10px -10px' }}>
          <div className="stat">
            <div className="stat-value">{learn.quality.approvals}</div>
            <div className="stat-label">approved</div>
          </div>
          <div className="stat">
            <div className="stat-value">{learn.quality.rejections}</div>
            <div className="stat-label">rejected</div>
          </div>
          <div className="stat">
            <div className="stat-value">{learn.hook_edits}</div>
            <div className="stat-label">hook edits</div>
          </div>
          <div className="stat">
            <div className="stat-value">
              {learn.quality.approval_rate ? `${Math.round(learn.quality.approval_rate * 100)}%` : '—'}
            </div>
            <div className="stat-label">approval rate</div>
          </div>
        </div>
        {learn.style_profile ? (
          <p
            className="panel-note"
            style={{
              margin: 0,
              borderTop: '1px solid var(--seam)',
              paddingTop: 9,
              whiteSpace: 'pre-line',
              color: 'var(--ink-2)',
            }}
          >
            {learn.style_profile}
          </p>
        ) : null}
      </div>
    </section>
  )
}
