import { useCallback } from 'react'
import { usePersistentState } from '../workspace/usePersistentState'
import { TOUR_STEPS } from './steps'
import type { TourState } from './types'
import {
  backTour,
  closeTour,
  finishTour,
  nextTour,
  startTour,
  TOUR_INITIAL,
} from './state'

export const TOUR_KEY = 'clip-factory.tour.v1'

/**
 * Tour progress lives beside layout in localStorage: it is a preference, not
 * app data, and it must survive a reload so a stopped tour can be resumed.
 *
 * The transitions themselves are pure functions in `tour/state.ts`, covered by
 * unit tests. This hook only persists and reads them.
 */
export function useTour() {
  const [state, setState] = usePersistentState<TourState>(TOUR_KEY, TOUR_INITIAL)

  const start = useCallback(
    (resume = false) => {
      setState((current) => startTour(current, resume))
    },
    [setState],
  )

  const next = useCallback(() => {
    setState(nextTour)
  }, [setState])

  const back = useCallback(() => {
    setState(backTour)
  }, [setState])

  const close = useCallback(() => {
    setState(closeTour)
  }, [setState])

  const finish = useCallback(() => {
    setState(finishTour)
  }, [setState])

  const step = TOUR_STEPS[Math.min(state.step, TOUR_STEPS.length - 1)] ?? TOUR_STEPS[0]
  return {
    state,
    step,
    index: Math.min(state.step, TOUR_STEPS.length - 1),
    total: TOUR_STEPS.length,
    start,
    next,
    back,
    close,
    finish,
  }
}
