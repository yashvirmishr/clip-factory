export type TourStepId = 'welcome' | 'ready' | 'add' | 'analyze' | 'read' | 'decide' | 'finish'

export type TourActionId = 'next' | 'demo' | 'analyze' | 'select' | 'approve' | 'render' | 'finish'

export type TourPanel = 'welcome' | 'readiness'

/** What the app can already show. A step finishes when its fact becomes true. */
export interface TourProgress {
  source: boolean
  analysis: boolean
  clip: boolean
  verdict: boolean
  render: boolean
}

export interface TourStep {
  id: TourStepId
  title: string
  /** Empty when a panel carries the copy instead. */
  body?: string
  /** Rendered instead of plain body text: the two setup screens. */
  panel?: TourPanel
  /** Which [data-tour] element to point at. Missing means a centred card. */
  anchor?: string
  action?: { label: string; id: TourActionId }
  /** Advance on its own once this fact is true, without a click. */
  doneWhen?: keyof TourProgress
  secondary?: { label: string; id: TourActionId }
}

export type TourStatus = 'unseen' | 'running' | 'paused' | 'done'

export interface TourState {
  status: TourStatus
  step: number
}
