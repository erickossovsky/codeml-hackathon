import { MotionConfig } from 'framer-motion'
import { btn } from './shared/ui'
import { Logo } from './shared/Logo'
import { useEffect, useReducer, useRef, useState } from 'react'
import type { RunClient } from './api/client'
import { createMockClient } from './api/mockClient'
import { SidePanel } from './features/side/SidePanel'
import { Stage } from './features/stage/Stage'
import { StackedFlow } from './features/stage/StackedFlow'
import type { ProgressEvent } from './shared/types'
import { initialRunState, runReducer, type Phase } from './state/runReducer'

// `?fail=1` forces the mock error path for demos.
const failMode = new URLSearchParams(window.location.search).get('fail') === '1'
const client: RunClient = createMockClient({ fail: failMode })

const STATUS: Record<Phase, { text: string; tone: string }> = {
  idle: { text: 'Idle', tone: 'text-mute' },
  running: { text: 'Running', tone: 'text-amber' },
  done: { text: 'Complete', tone: 'text-fg' },
  error: { text: 'Failed', tone: 'text-red' },
}

// Below this width the drawing would scale too small to read, so the flow becomes a list.
const NARROW = '(max-width: 900px)'

function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches)
  useEffect(() => {
    const mq = window.matchMedia(NARROW)
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}

export default function App() {
  const [plans, setPlans] = useState<File[]>([])
  const [shops, setShops] = useState<File[]>([])
  const [state, dispatch] = useReducer(runReducer, initialRunState)
  const [now, setNow] = useState(() => Date.now())
  const narrow = useNarrow()
  const unsubscribe = useRef<(() => void) | null>(null)
  const startedAt = useRef(0)

  useEffect(() => () => unsubscribe.current?.(), [])

  // Elapsed time only ticks while a run is going.
  useEffect(() => {
    if (state.phase !== 'running') return
    const id = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(id)
  }, [state.phase])

  async function run() {
    if (plans.length === 0) return
    unsubscribe.current?.()
    startedAt.current = Date.now()
    setNow(startedAt.current)
    dispatch({ type: 'start', startedAt: startedAt.current })
    const { runId } = await client.startRun({ plans, shops })
    unsubscribe.current = client.onProgress(runId, (event: ProgressEvent) =>
      dispatch({ type: 'progress', event, t: Date.now() - startedAt.current }),
    )
  }

  // Retry keeps the files the user added; only the run is reset.
  function retry() {
    unsubscribe.current?.()
    dispatch({ type: 'reset' })
  }

  function newRun() {
    retry()
    setPlans([])
    setShops([])
  }

  // Files are appended, so a project can hold any number of plan sheets and shop drawings.
  function onFiles(kind: 'plan' | 'shop', files: File[]) {
    if (files.length === 0) return false
    if (kind === 'plan') setPlans((prev) => [...prev, ...files])
    else setShops((prev) => [...prev, ...files])
    return false
  }

  function remove(kind: 'plan' | 'shop', index: number) {
    if (kind === 'plan') setPlans((prev) => prev.filter((_, i) => i !== index))
    else setShops((prev) => prev.filter((_, i) => i !== index))
  }

  function clear(kind: 'plan' | 'shop') {
    if (kind === 'plan') setPlans([])
    else setShops([])
  }

  const status = STATUS[state.phase]
  const elapsed = !state.startedAt ? 0 : state.phase === 'running' ? now - state.startedAt : state.log.at(-1)?.t ?? 0

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex min-h-dvh flex-col md:h-full">
        <header className="flex h-16 shrink-0 items-center justify-between gap-6 border-b border-line px-6 sm:px-10">
          <div className="flex items-center gap-5">
            <Logo />
            <span className="hidden border-l border-line-2 pl-5 text-base text-mute sm:inline">Plan against shop drawings</span>
          </div>
          <div className="flex items-center gap-5 font-mono text-[13px] uppercase tracking-[0.12em]">
            <span className={`hidden sm:inline ${status.tone}`}>{status.text}</span>
            <button type="button" onClick={run} disabled={plans.length === 0 || state.phase === 'running'} className={`${btn} px-6 py-2.5`}>
              Run check
            </button>
          </div>
        </header>

        {narrow ? (
          <main className="flex-1">
            <StackedFlow plans={plans} shops={shops} state={state} onFiles={onFiles} onRetry={retry} onNewRun={newRun} />
            <div className="border-t border-line">
              <SidePanel state={state} elapsed={Math.max(0, elapsed)} plans={plans} shops={shops} />
            </div>
          </main>
        ) : (
          <>
            <main className="grid min-h-0 flex-1 grid-cols-[1fr_360px] divide-x divide-line">
              <section className="min-h-0 min-w-0">
                <Stage plans={plans} shops={shops} state={state} onFiles={onFiles} onClear={clear} onRemove={remove} onRetry={retry} onNewRun={newRun} />
              </section>
              <aside className="flex min-h-0 flex-col">
                <SidePanel state={state} elapsed={Math.max(0, elapsed)} plans={plans} shops={shops} />
              </aside>
            </main>
          </>
        )}
      </div>
    </MotionConfig>
  )
}
