import type { RunClient } from './client'
import type { ProgressEvent, RunResult } from '../shared/types'
import { STEPS } from '../shared/steps'

const STEP_MS = 900
const FIXTURE_URL = '/fixtures/findings.json'

// Short readouts shown on each step, as a real backend would report them.
const DETAIL: Partial<Record<(typeof STEPS)[number]['id'], string>> = {
  ingest: '50 plan pages · 40 shop PDFs',
  extract_plan: '118 elements',
  extract_shop: '121 elements',
  compare: '118 matched · 10 to review',
  report: 'findings.json · report.pdf',
}

// Replays the fixture on a timer so the UI can be built before the backend exists.
// Pass `fail: true` to simulate an error on the second step.
export function createMockClient(opts: { fail?: boolean } = {}): RunClient {
  const runs = new Map<string, { timers: number[]; listeners: Set<(e: ProgressEvent) => void> }>()

  return {
    async startRun() {
      const runId = `mock-${Date.now()}`
      runs.set(runId, { timers: [], listeners: new Set() })
      return { runId }
    },

    onProgress(runId, cb) {
      const run = runs.get(runId)
      if (!run) return () => {}
      run.listeners.add(cb)
      const emit = (e: ProgressEvent) => run.listeners.forEach((l) => l(e))

      // Steps run in order. In fail mode the run stops on the second step, so nothing after it fires.
      let t = 0
      for (const [i, step] of STEPS.entries()) {
        run.timers.push(window.setTimeout(() => emit({ kind: 'step', step: step.id, status: 'active' }), t))
        t += STEP_MS
        if (opts.fail && i === 1) {
          run.timers.push(window.setTimeout(() => emit({ kind: 'error', message: 'Could not read shop drawing SHOP-02.pdf' }), t))
          break
        }
        run.timers.push(window.setTimeout(() => emit({ kind: 'step', step: step.id, status: 'done', detail: DETAIL[step.id] }), t))
        t += STEP_MS / 2
      }

      if (!opts.fail) {
        run.timers.push(
          window.setTimeout(async () => {
            const result: RunResult = await fetch(FIXTURE_URL).then((r) => r.json())
            emit({ kind: 'result', result })
          }, t),
        )
      }

      return () => {
        run.timers.forEach(clearTimeout)
        run.listeners.delete(cb)
      }
    },
  }
}
