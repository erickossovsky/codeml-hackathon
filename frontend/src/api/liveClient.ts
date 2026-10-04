import type { RunClient } from './client'
import type { ProgressEvent, RunResult } from '../shared/types'
import { STEPS } from '../shared/steps'

export function createLiveClient(): RunClient {
  const runs = new Map<string, { listeners: Set<(e: ProgressEvent) => void> }>()

  return {
    async startRun(files) {
      const formData = new FormData()
      files.plans.forEach((f) => formData.append('plans', f))
      files.shops.forEach((f) => formData.append('shops', f))

      const res = await fetch('http://localhost:8000/api/run', {
        method: 'POST',
        body: formData,
      })
      const { runId } = await res.json()
      runs.set(runId, { listeners: new Set() })
      
      // Kick off the polling in the background
      setTimeout(() => pollProgress(runId), 100)
      
      return { runId }
    },

    onProgress(runId, cb) {
      const run = runs.get(runId)
      if (!run) return () => {}
      run.listeners.add(cb)
      return () => run.listeners.delete(cb)
    },
  }

  async function pollProgress(runId: string) {
    const run = runs.get(runId)
    if (!run) return

    const emit = (e: ProgressEvent) => run.listeners.forEach((l) => l(e))

    try {
      while (true) {
        const res = await fetch(`http://localhost:8000/api/status/${runId}`)
        const events: ProgressEvent[] = await res.json()
        
        for (const e of events) {
          emit(e)
          if (e.kind === 'result' || e.kind === 'error') {
            return
          }
        }
        
        await new Promise(r => setTimeout(r, 1000))
      }
    } catch (err) {
      emit({ kind: 'error', message: String(err) })
    }
  }
}
