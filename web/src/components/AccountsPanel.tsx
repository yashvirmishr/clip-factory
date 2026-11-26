import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { AccountPost, PersonalState, WeeklyState } from '../types'
import { Icon } from '../workspace/Icon'
import { Field, Spinner, TextField } from '../workspace/ui'

interface Account {
  id: string
  platform: string
  handle?: string
  display_name?: string
  external_id?: string
}

interface Platform {
  platform: string
  label: string
  aspect: string
  min_duration_s: number
  max_duration_s: number
  connected: number
  adapter: boolean
}

interface Props {
  onNotify: (kind: 'ok' | 'error' | 'info', message: string) => void
}

const SETUP: Record<string, { name: string; hint: string; docs: string }> = {
  youtube: {
    name: 'YouTube',
    hint: 'Google Cloud → APIs & Services → Credentials → OAuth client (Web application). Add the callback below.',
    docs: 'https://developers.google.com/youtube/v3/guides/authentication',
  },
  x: {
    name: 'X',
    hint: 'X developer portal → your app → User authentication settings → OAuth 2.0 (confidential client). Add the callback below.',
    docs: 'https://docs.x.com/x-api/fundamentals/authentication',
  },
}

const REDIRECT = 'http://127.0.0.1:8756/api/connections/callback'

function labelFor(platform: string): string {
  return SETUP[platform]?.name ?? platform
}

function when(seconds: number): string {
  if (!seconds) return 'never'
  return new Date(seconds * 1000).toLocaleString()
}

/**
 * The account side of the loop: connect once, then read what the platform
 * actually rewarded. The numbers here are measured, not estimated; the model
 * is only shown when it cleared the documented gate.
 */
export function AccountsPanel({ onNotify }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [selected, setSelected] = useState('')
  const [posts, setPosts] = useState<AccountPost[]>([])
  const [baseline, setBaseline] = useState<Record<string, unknown>>({})
  const [secretReady, setSecretReady] = useState(true)
  const [storeHint, setStoreHint] = useState('')
  const [personal, setPersonal] = useState<PersonalState | null>(null)
  const [weekly, setWeekly] = useState<WeeklyState | null>(null)
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [connectPlatform, setConnectPlatform] = useState('youtube')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const notifyRef = useRef(onNotify)
  notifyRef.current = onNotify

  const active = accounts.find((account) => account.id === selected) ?? accounts[0] ?? null
  const setup = SETUP[connectPlatform]

  const load = useCallback(async () => {
    try {
      const payload = await api.accounts()
      setAccounts(payload.accounts)
      setPlatforms(payload.platforms)
      setSecretReady(payload.secret_store?.available !== false)
      setStoreHint(payload.secret_store?.detail ?? '')
      if (!selected && payload.accounts[0]) setSelected(payload.accounts[0].id)
    } catch (failure) {
      setError((failure as Error).message)
    }
  }, [selected])

  const loadLearning = useCallback(async () => {
    try {
      const [state, week] = await Promise.all([api.personalState(), api.weeklyStatus()])
      setPersonal(state)
      setWeekly(week)
    } catch {
      /* the learning panels are contextual, not the reason to open this tab */
    }
  }, [])

  const loadPosts = useCallback(async (accountId: string) => {
    if (!accountId) return
    try {
      const payload = await api.accountPosts(accountId, 25)
      setPosts(payload.posts)
      setBaseline(payload.baseline)
    } catch (failure) {
      setError((failure as Error).message)
    }
  }, [])

  useEffect(() => {
    void load()
    void loadLearning()
  }, [load, loadLearning])

  useEffect(() => {
    setClientId('')
    setClientSecret('')
  }, [connectPlatform])

  // OAuth finishes in another tab or the browser. Re-read when this window is
  // focused so a successful connection appears without a relaunch.
  useEffect(() => {
    const onFocus = () => {
      void load()
      void loadLearning()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [load, loadLearning])

  useEffect(() => {
    if (active) void loadPosts(active.id)
  }, [active?.id, loadPosts])

  const connect = async () => {
    if (!clientId.trim()) {
      setError(`Paste the ${labelFor(connectPlatform)} OAuth client ID first.`)
      return
    }
    setBusy('connect')
    setError(null)
    const tab = window.open('', '_blank')
    try {
      const start = await api.connectAccount(connectPlatform, clientId.trim(), clientSecret.trim())
      if (tab) tab.location.href = start.url
      else window.location.href = start.url
      notifyRef.current('info', 'Finish consent in the browser, then return here.')
    } catch (failure) {
      tab?.close()
      setError((failure as Error).message)
      notifyRef.current('error', (failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const sync = async (account: Account) => {
    setBusy(`sync:${account.id}`)
    setError(null)
    try {
      const result = await api.syncAccount(account.id)
      notifyRef.current('ok', `Pulled ${String(result.new_posts ?? 0)} new posts and refreshed metrics.`)
      await Promise.all([load(), loadPosts(account.id), loadLearning()])
    } catch (failure) {
      setError((failure as Error).message)
      notifyRef.current('error', (failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const train = async () => {
    setBusy('train')
    try {
      const result = await api.trainPersonal()
      notifyRef.current(result.promoted ? 'ok' : 'info', String(result.reason ?? 'Training finished.'))
      await loadLearning()
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const weeklyRun = async () => {
    setBusy('weekly')
    try {
      const result = await api.runWeekly()
      const failed = result.results.filter((row) => !row.ok)
      if (failed.length) {
        const first = failed[0]
        const message = `${failed.length} account sync${failed.length === 1 ? '' : 's'} failed. ${first.error ?? 'Open the account for details.'}`
        setError(message)
        notifyRef.current('error', message)
      } else if (result.training?.promoted === true) {
        notifyRef.current('ok', 'Weekly sync finished. The personal model cleared its gate and is active.')
      } else {
        const reason = typeof result.training?.reason === 'string' ? result.training.reason : 'the gate was not met'
        notifyRef.current('info', `Weekly sync finished. Personal model kept as is: ${reason}.`)
      }
      await Promise.all([load(), loadLearning()])
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy('')
    }
  }

  const reviewed = useMemo(
    () => posts.filter((post) => post.label !== null).length,
    [posts],
  )

  return (
    <div className="insights">
      {!secretReady ? (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          {storeHint || 'Tokens need the operating system credential store; connecting stays off.'}
        </p>
      ) : null}

      <section className="insight-card">
        <header>
          <span className="label">Connected accounts</span>
          <span className="pill">{accounts.length || 'none'}</span>
        </header>
        {accounts.length ? (
          <div className="stack-12">
            {accounts.map((account) => (
              <div className="account-row" key={account.id} data-selected={account.id === active?.id ? 'true' : undefined}>
                <button type="button" className="account-pick" onClick={() => setSelected(account.id)}>
                  <b>{account.display_name || labelFor(account.platform)}</b>
                  <em>{labelFor(account.platform)} {account.handle ? `· ${account.handle}` : ''}</em>
                </button>
                <button
                  type="button"
                  className="btn ghost sm"
                  onClick={() => void sync(account)}
                  disabled={busy === `sync:${account.id}`}
                >
                  {busy === `sync:${account.id}` ? <Spinner label="" /> : <Icon name="refresh" size={12} />}
                  Sync
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="panel-empty">Connect a channel to start measuring what works. Tokens stay in the OS credential store.</p>
        )}
      </section>

      {setup ? (
        <section className="insight-card">
          <header>
            <span className="label">Connect {setup.name}</span>
            <a href={setup.docs} target="_blank" rel="noreferrer" className="field-hint">Provider docs</a>
          </header>
          <div className="stack-12">
            <Field label="Platform">
              <select
                value={connectPlatform}
                onChange={(event) => setConnectPlatform(event.target.value)}
                aria-label="Platform to connect"
              >
                {(platforms.filter((platform) => SETUP[platform.platform])).map((platform) => (
                  <option key={platform.platform} value={platform.platform}>{platform.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Callback">
              <code className="bake-path">{REDIRECT}</code>
            </Field>
            <p className="field-hint">{setup.hint}</p>
            <TextField label="Client ID" value={clientId} onChange={setClientId} placeholder="OAuth client ID" />
            <TextField
              label="Client secret"
              type="password"
              value={clientSecret}
              onChange={setClientSecret}
              placeholder="stored in the OS credential store"
            />
            <button type="button" className="btn sm block" onClick={() => void connect()} disabled={busy === 'connect' || !secretReady}>
              {busy === 'connect' ? <Spinner label="" /> : <Icon name="external" size={13} />}
              Connect {setup.name}
            </button>
            <p className="field-hint">
              TikTok and Instagram are not listed yet: both require an approved developer app and platform review before an account can be read or published. Nothing connects silently.
            </p>
          </div>
        </section>
      ) : null}

      {active ? (
        <section className="insight-card">
          <header>
            <span className="label">Measured posts</span>
            <span className="pill">{[...posts].filter((post) => post.label === 1).length} wins / {reviewed} labelled</span>
          </header>
          <dl className="insight-metrics">
            <div><dt>Eligible</dt><dd>{String(baseline.eligible_posts ?? 0)}</dd></div>
            <div><dt>Median views</dt><dd>{Number(baseline.median_views ?? 0).toLocaleString()}</dd></div>
            <div><dt>Median engagement</dt><dd>{((Number(baseline.median_engagement_rate ?? 0)) * 100).toFixed(2)}%</dd></div>
          </dl>
          {posts.length ? (
            <div className="post-list">
              {posts.slice(0, 8).map((post) => (
                <a className="post-row" key={post.id} href={post.url || undefined} target="_blank" rel="noreferrer">
                  <span className="post-title">{post.title || post.caption || post.platform_post_id}</span>
                  <span className="post-meta num">
                    {Number(post.metrics.views ?? 0).toLocaleString()} views · {(post.engagement_rate * 100).toFixed(2)}% · {Math.round(post.composite ?? 0)} score
                  </span>
                  <span className={`pill ${post.label === 1 ? 'ok' : post.label === 0 ? 'warn' : ''}`}>
                    {post.label === 1 ? 'win' : post.label === 0 ? 'miss' : 'settling'}
                  </span>
                </a>
              ))}
            </div>
          ) : (
            <p className="panel-empty">No posts captured yet. Press Sync above; metrics are only sampled after a post has had 24 hours to settle.</p>
          )}
          {posts.some((post) => post.origin !== 'app') ? (
            <p className="field-hint">
              Channel history sets the baseline. The personal ranker learns only from posts published in this app, because those are the clips with the same measured features.
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="insight-card">
        <header>
          <span className="label">Personal performance model</span>
          <span className={`pill ${personal?.active ? 'ok' : ''}`}>{personal?.active ? 'live' : 'learning'}</span>
        </header>
        {personal ? (
          <div className="stack-12">
            <p className="field-hint">
              {personal.active
                ? `Blended at ${(personal.blend_cap * 100).toFixed(0)}% with your approval model. Held-out AUC ${String(personal.active.metrics.auc ?? '—')}.`
                : `${personal.posts} settled posts (${personal.positives} wins / ${personal.negatives} misses). Needs ${personal.min_posts} with at least ${personal.min_per_class} of each before it can train.`}
            </p>
            <div className="button-row">
              <button type="button" className="btn ghost sm" onClick={() => void train()} disabled={busy === 'train'}>
                {busy === 'train' ? <Spinner label="" /> : <Icon name="sparkles" size={12} />}
                Retrain now
              </button>
              {personal.active ? (
                <button
                  type="button"
                  className="btn ghost sm"
                  onClick={async () => {
                    await api.rollbackPersonal()
                    await loadLearning()
                    notifyRef.current('info', 'Personal model paused; approval-only ranking is active.')
                  }}
                >
                  Pause model
                </button>
              ) : null}
            </div>
            {personal.history.length ? (
              <div className="model-history">
                {personal.history.slice(0, 4).map((model) => (
                  <div className="bake-row" key={model.version}>
                    <span className="bake-name num">{model.version}</span>
                    <span className={`pill ${model.active ? 'ok' : ''}`}>
                      {model.active ? 'active' : `AUC ${String(model.metrics.auc ?? '—')}`}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <Spinner label="Reading model state" />
        )}
      </section>

      <section className="insight-card">
        <header>
          <span className="label">Weekly loop</span>
          <span className={`pill ${weekly?.due ? 'warn' : 'ok'}`}>{weekly?.due ? 'due' : 'scheduled'}</span>
        </header>
        {weekly ? (
          <div className="stack-12">
            <p className="field-hint">
              Runs every 7 days while the app is open. Last {when(weekly.last_run)} · next {when(weekly.next_run)}.
            </p>
            {weekly.results.length ? (
              <div className="model-history">
                {weekly.results.map((result) => (
                  <div className="bake-row" key={result.account_id}>
                    <span className="bake-name">{result.display_name || result.platform}</span>
                    <span className={`pill ${result.ok ? 'ok' : 'danger'}`}>
                      {result.ok ? `+${result.new_posts ?? 0} posts` : result.error?.slice(0, 42)}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
            <button type="button" className="btn ghost sm block" onClick={() => void weeklyRun()} disabled={busy === 'weekly'}>
              {busy === 'weekly' ? <Spinner label="" /> : <Icon name="activity" size={12} />}
              Sync and retrain now
            </button>
          </div>
        ) : null}
      </section>

      {error ? (
        <p className="warn-line">
          <Icon name="alert" size={13} />
          {error}
        </p>
      ) : null}
    </div>
  )
}
