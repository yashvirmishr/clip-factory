import { TOUR_STEPS } from './steps'
import type { TourState } from './types'

export const TOUR_INITIAL: TourState = { status: 'unseen', step: 0 }

const LAST = TOUR_STEPS.length - 1

/**
 * Tour transitions as plain functions.
 *
 * They live apart from the hook so the bounds and the resume rule can be tested
 * without a DOM: the two bugs worth catching are stepping past the last card and
 * resuming a tour that was never started.
 */
export function startTour(current: TourState, resume = false): TourState {
  const resumable = current.status === 'running' || current.status === 'paused'
  const step = resume && resumable ? Math.min(current.step, LAST) : 0
  return { status: 'running', step }
}

export function nextTour(current: TourState): TourState {
  if (current.step >= LAST) return { status: 'done', step: LAST }
  return { status: 'running', step: current.step + 1 }
}

export function backTour(current: TourState): TourState {
  return { ...current, status: 'running', step: Math.max(0, current.step - 1) }
}

export function closeTour(current: TourState): TourState {
  if (current.status === 'done') return current
  return {
    ...current,
    status: current.status === 'unseen' ? 'unseen' : 'paused',
  }
}

export function finishTour(): TourState {
  return { status: 'done', step: LAST }
}
