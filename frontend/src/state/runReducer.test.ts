import { describe, expect, it } from 'vitest'
import { STEPS } from '../shared/steps'
import { initialRunState, runReducer } from './runReducer'

const step = (step: 'ingest' | 'extract_plan' | 'compare' | 'report' | 'extract_shop', status: 'active' | 'done', detail?: string) =>
  ({ type: 'progress', event: { kind: 'step', step, status, detail }, t: 0 }) as const

describe('runReducer', () => {
  it('starts with every step pending', () => {
    expect(Object.values(initialRunState.stepStatus).every((s) => s === 'pending')).toBe(true)
  })

  it('marks a step active then done and keeps its readout', () => {
    let s = runReducer(initialRunState, { type: 'start', startedAt: 0 })
    s = runReducer(s, step('ingest', 'active'))
    expect(s.stepStatus.ingest).toBe('active')
    s = runReducer(s, step('ingest', 'done', '3 files'))
    expect(s.stepStatus.ingest).toBe('done')
    expect(s.details.ingest).toBe('3 files')
  })

  it('logs each step with its time', () => {
    let s = runReducer(initialRunState, { type: 'start', startedAt: 0 })
    s = runReducer(s, { type: 'progress', event: { kind: 'step', step: 'ingest', status: 'active' }, t: 120 })
    expect(s.log).toEqual([{ t: 120, step: 'ingest', text: 'Ingest started', tone: 'info' }])
  })

  it('moves to error with a message and a red log line', () => {
    const s = runReducer(initialRunState, { type: 'progress', event: { kind: 'error', message: 'boom' }, t: 5 })
    expect(s.phase).toBe('error')
    expect(s.error).toBe('boom')
    expect(s.log.at(-1)?.tone).toBe('bad')
  })

  it('finishes every step on result', () => {
    const result = { run_id: 'x', project: 'p', plan: 'p', shop_drawings: [], counts: { compliant: 0, non_compliant: 0, missing: 0, added: 0, needs_review: 0 }, findings: [] }
    const s = runReducer(initialRunState, { type: 'progress', event: { kind: 'result', result }, t: 9 })
    expect(s.phase).toBe('done')
    expect(STEPS.every((st) => s.stepStatus[st.id] === 'done')).toBe(true)
  })
})
