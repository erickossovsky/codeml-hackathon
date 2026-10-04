import type { ProgressEvent } from '../shared/types'

// The only interface the screen talks to. The mock implements it now;
// the real backend client will implement the same signature later.
export interface RunClient {
  startRun(files: { plans: File[]; shops: File[] }): Promise<{ runId: string }>
  onProgress(runId: string, cb: (event: ProgressEvent) => void): () => void
}
