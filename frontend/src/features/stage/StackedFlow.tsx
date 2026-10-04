import { motion } from 'framer-motion'
import { useRef } from 'react'
import { Check } from 'lucide-react'
import { STEPS, type StepId } from '../../shared/steps'
import type { RunState, StepStatus } from '../../state/runReducer'
import { SheetThumb } from '../sheet/SheetThumb'
import { link } from '../../shared/ui'
import { ResultPanel } from './ResultPanel'

// Phone layout: the same flow as a vertical list. Used below the narrow breakpoint, where the
// drawing would scale too small to read.
export function StackedFlow({ plans, shops, state, onFiles, onRetry, onNewRun }: {
  plans: File[]
  shops: File[]
  state: RunState
  onFiles: (kind: 'plan' | 'shop', files: File[]) => boolean
  onRetry: () => void
  onNewRun: () => void
}) {
  const st = state.stepStatus
  const idle = state.phase === 'idle'
  const done = state.phase === 'done' && !!state.result
  const planInput = useRef<HTMLInputElement>(null)
  const shopInput = useRef<HTMLInputElement>(null)
  const pick = (kind: 'plan' | 'shop', list: FileList | null) => {
    if (list) onFiles(kind, Array.from(list).filter((f) => f.name.toLowerCase().endsWith('.pdf')))
  }

  if (done && state.result) {
    return (
      <div className="relative min-h-[80vh]">
        <ResultPanel result={state.result} file={plans[0] ?? null} files={[...plans, ...shops]} onReset={onNewRun} />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <input ref={planInput} type="file" accept="application/pdf" multiple className="hidden" onChange={(e) => pick('plan', e.target.files)} />
      <input ref={shopInput} type="file" accept="application/pdf" multiple className="hidden" onChange={(e) => pick('shop', e.target.files)} />
      <Card label="Plan" note={plans.length ? `${plans.length} plan file${plans.length > 1 ? 's' : ''}` : 'Add the plan PDF'} disabled={!idle} onOpen={() => planInput.current?.click()} file={plans[0] ?? null} />
      <Card label="Shop drawings" note={shops.length ? `${shops.length} file${shops.length > 1 ? 's' : ''}` : 'Add shop PDFs'} disabled={!idle} onOpen={() => shopInput.current?.click()} file={shops[0] ?? null} />

      <div className="my-2 h-px bg-line" />

      {STEPS.filter((s) => s.id.startsWith('extract') || s.id === 'compare').map((s) => (
        <Row key={s.id} id={s.id} label={s.label} status={st[s.id]} detail={state.details[s.id]} />
      ))}

      {state.phase === 'error' && (
        <div className="mt-3 flex flex-col items-center gap-3 border border-line-2 bg-panel p-4 text-center">
          <p className="font-mono text-sm text-red">{state.error}</p>
          <button type="button" onClick={onRetry} className={link}>Try again</button>
        </div>
      )}

      <div className="mt-2 flex flex-col">
        {STEPS.filter((s) => s.id === 'report').map((s) => (
          <Row key={s.id} id={s.id} label={s.label} status={st[s.id]} detail={state.details[s.id]} />
        ))}
      </div>
    </div>
  )
}

function Card({ label, note, disabled, onOpen, file }: { label: string; note: string; disabled: boolean; onOpen: () => void; file: File | null }) {
  return (
    <button type="button" disabled={disabled} onClick={onOpen} className="flex items-center gap-4 border border-line-2 bg-panel p-3 text-left disabled:cursor-default">
      <SheetThumb file={file} width={52} seed={label.length} />
      <span className="min-w-0">
        <span className="block font-mono text-xs uppercase tracking-[0.12em] text-mute">{label}</span>
        <span className="block truncate text-base">{note}</span>
      </span>
    </button>
  )
}

const WAITING: Partial<Record<StepId, string>> = {
  extract_plan: 'Waiting for the plan',
  extract_shop: 'Waiting for shop drawings',
  compare: 'Waiting for both extractions',
  report: 'Waiting for findings',
}

function Row({ id, label, status, detail }: { id: StepId; label: string; status: StepStatus; detail?: string }) {
  return (
    <div className="flex items-center gap-4 border-b border-line py-3">
      <span className={`grid size-7 shrink-0 place-items-center border ${status === 'done' ? 'border-fg bg-fg text-bg' : status === 'active' ? 'border-amber' : 'border-line-2'}`}>
        {status === 'done' ? <Check className="size-4" strokeWidth={2} aria-hidden /> : status === 'active' ? <motion.span className="size-2 bg-amber" animate={{ opacity: [1, 0.2, 1] }} transition={{ repeat: Infinity, duration: 1 }} /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className={`block text-base ${status === 'pending' ? 'text-mute' : ''}`}>{label}</span>
        <span className="block truncate font-mono text-[13px] text-mute">{detail ?? WAITING[id]}</span>
      </span>
    </div>
  )
}
