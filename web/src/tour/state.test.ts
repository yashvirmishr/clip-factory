import { describe, expect, it } from 'vitest'
import type { TourState } from './types'
import { backTour, closeTour, finishTour, nextTour, startTour } from './state'
import { TOUR_STEPS } from './steps'

const LAST_STEP = TOUR_STEPS.length - 1

function unseen(): TourState {
  return { status: 'unseen', step: 0 }
}

function done(): TourState {
  return { status: 'done', step: LAST_STEP }
}

describe('startTour', () => {
  it('begins at the first step', () => {
    expect(startTour(unseen())).toEqual({ status: 'running', step: 0 })
  })

  it('never resumes a tour that was never started', () => {
    expect(startTour(unseen(), true)).toEqual({ status: 'running', step: 0 })
  })

  it('resumes an in-progress tour at its step', () => {
    expect(startTour({ status: 'paused', step: 3 }, true)).toEqual({
      status: 'running',
      step: 3,
    })
  })

  it('clamps a resumed step inside the cards', () => {
    expect(startTour({ status: 'running', step: 99 }, true)).toEqual({
      status: 'running',
      step: LAST_STEP,
    })
  })
})

describe('nextTour', () => {
  it('advances one card', () => {
    expect(nextTour({ status: 'running', step: 0 })).toEqual({
      status: 'running',
      step: 1,
    })
  })

  it('finishes on the last card instead of stepping past it', () => {
    expect(nextTour({ status: 'running', step: LAST_STEP })).toEqual({
      status: 'done',
      step: LAST_STEP,
    })
  })

  it('stays finished', () => {
    expect(nextTour(done())).toEqual(done())
  })
})

describe('backTour', () => {
  it('goes back one card', () => {
    expect(backTour({ status: 'running', step: 2 })).toEqual({
      status: 'running',
      step: 1,
    })
  })

  it('never drops below zero', () => {
    expect(backTour(unseen())).toEqual({ status: 'running', step: 0 })
  })

  it('moves backward from the last card without leaving range', () => {
    expect(backTour(done())).toEqual({ status: 'running', step: LAST_STEP - 1 })
  })
})

describe('closeTour', () => {
  it('pauses a running tour without losing its step', () => {
    expect(closeTour({ status: 'running', step: 2 })).toEqual({
      status: 'paused',
      step: 2,
    })
  })

  it('leaves an unseen tour unseen', () => {
    expect(closeTour(unseen())).toEqual(unseen())
  })

  it('leaves a finished tour finished', () => {
    expect(closeTour(done())).toEqual(done())
  })
})

describe('finishTour', () => {
  it('marks the last card as done', () => {
    expect(finishTour()).toEqual({ status: 'done', step: LAST_STEP })
  })
})
