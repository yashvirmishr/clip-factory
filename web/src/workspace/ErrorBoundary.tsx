import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
  detail: string
}

/**
 * Last line of defence for the renderer. The backend and the project files
 * are unaffected by a UI exception, so the recovery copy says exactly that.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, detail: '' }

  static getDerivedStateFromError(error: Error): State {
    return { error, detail: '' }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({
      detail: `${error.stack ?? error.message}\n${info.componentStack ?? ''}` ,
    })
    console.error('Clip Factory interface error', error, info)
  }

  private copy = async () => {
    const { error, detail } = this.state
    try {
      await navigator.clipboard.writeText(`${error?.message ?? ''}\n\n${detail}`)
    } catch {
      /* clipboard can be unavailable in a hardened shell; the text is on screen */
    }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <main className="boot-screen">
        <div className="boot-card">
          <div className="boot-mark" aria-hidden="true">
            CF
          </div>
          <span className="boot-eyebrow">Interface error</span>
          <h1>The interface hit a snag</h1>
          <p>
            Your projects are safe on disk. Reload to reopen the cutting room, or copy the
            details for a bug report.
          </p>
          <code className="boot-detail">{error.message}</code>
          <div className="boot-actions">
            <button
              type="button"
              className="btn primary"
              onClick={() => window.location.reload()}
            >
              Reload Clip Factory
            </button>
            <button type="button" className="btn ghost" onClick={() => void this.copy()}>
              Copy details
            </button>
            <span className="boot-hint">
              The backend keeps running; a reload usually clears this.
            </span>
          </div>
        </div>
      </main>
    )
  }
}
