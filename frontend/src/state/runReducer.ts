import { STEPS, type StepId } from '../shared/steps'
import type { ProgressEvent, RunResult } from '../shared/types'

export type Phase = 'idle' | 'running' | 'done' | 'error'
export type StepStatus = 'pending' | 'active' | 'done'

export interface LogLine {
  t: number // ms since the run started
  step?: StepId
  text: string
  tone: 'info' | 'bad'
}

export interface RunState {
  phase: Phase
  stepStatus: Record<StepId, StepStatus>
  details: Partial<Record<StepId, string>>
  log: LogLine[]
  startedAt?: number
  result?: RunResult
  error?: string
}

// `t` is supplied by the caller (ms since start), so the reducer stays pure.
export type RunAction =
  | { type: 'start'; startedAt: number }
  | { type: 'reset' }
  | { type: 'progress'; event: ProgressEvent; t: number }

const pending = () => Object.fromEntries(STEPS.map((s) => [s.id, 'pending'])) as Record<StepId, StepStatus>

export const initialRunState: RunState = { phase: 'idle', stepStatus: pending(), details: {}, log: [] }

const LABEL = Object.fromEntries(STEPS.map((s) => [s.id, s.label])) as Record<StepId, string>

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case 'start':
      return { phase: 'running', stepStatus: pending(), details: {}, log: [], startedAt: action.startedAt }
    case 'reset':
      return initialRunState
    case 'progress': {
      const e = action.event
      if (e.kind === 'step') {
        const details = e.detail ? { ...state.details, [e.step]: e.detail } : state.details
        const text = e.status === 'active' ? `${LABEL[e.step]} started` : `${LABEL[e.step]} done${e.detail ? ` · ${e.detail}` : ''}`
        return {
          ...state,
          stepStatus: { ...state.stepStatus, [e.step]: e.status },
          details,
          log: [...state.log, { t: action.t, step: e.step, text, tone: 'info' }],
        }
      }
      if (e.kind === 'result') {
        const done = Object.fromEntries(STEPS.map((s) => [s.id, 'done'])) as Record<StepId, StepStatus>
        return {
          ...state,
          phase: 'done',
          stepStatus: done,
          result: e.result,
          log: [...state.log, { t: action.t, text: `Run ${e.result.run_id} complete`, tone: 'info' }],
        }
      }
      return { ...state, phase: 'error', error: e.message, log: [...state.log, { t: action.t, text: e.message, tone: 'bad' }] }
    }
  }
}
