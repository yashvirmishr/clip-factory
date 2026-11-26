import { useCallback } from 'react'
import { usePersistentState } from '../workspace/usePersistentState'
import { TOUR_STEPS } from './steps'
import type { TourState } from './types'

export const TOUR_KEY = 'clip-factory.tour.v1'

const INITIAL: TourState = { status: 'unseen', step: 0 }

/**
 * Tour progress lives beside layout in localStorage: it is a preference, not
 * app data, and it must survive a reload so a stopped tour can be resumed.
 */
export function useTour() {
  const [state, setState] = usePersistentState<TourState>(TOUR_KEY, INITIAL)

  const start = useCallback(
    (resume = false) => {
      setState((current) => {
        const resumable = current.status === 'running' || current.status === 'paused'
        const step = resume && resumable && current.step < TOUR_STEPS.length ? current.step : 0
        return { status: 'running', step }
      })
    },
    [setState],
  )

  const next = useCallback(() => {
    setState((current) => {
      const step = current.step + 1
      if (step >= TOUR_STEPS.length) return { status: 'done', step: TOUR_STEPS.length - 1 }
      return { status: 'running', step }
    })
  }, [setState])

  const back = useCallback(() => {
    setState((current) => ({ ...current, status: 'running', step: Math.max(0, current.step - 1) }))
  }, [setState])

  const close = useCallback(() => {
    setState((current) =>
      current.status === 'done' ? current : { ...current, status: current.status === 'unseen' ? 'unseen' : 'paused' },
    )
  }, [setState])

  const finish = useCallback(() => {
    setState({ status: 'done', step: TOUR_STEPS.length - 1 })
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
