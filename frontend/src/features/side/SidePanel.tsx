import { motion } from 'framer-motion'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { LogLine, RunState } from '../../state/runReducer'
import { label } from '../../shared/ui'
import { PLAN_DETECTIONS, SHOP_DETECTIONS } from '../sheet/detections'
import { SheetThumb } from '../sheet/SheetThumb'
import { usePdfPages } from '../sheet/pdf'

const fmt = (ms: number) => `${(ms / 1000).toFixed(1).padStart(4, '0')}s`

// Right column: the sheet being read (page by page), fixed indicators, and the run log.
export function SidePanel({ state, elapsed, plans, shops }: { state: RunState; elapsed: number; plans: File[]; shops: File[] }) {
  const st = state.stepStatus
  const r = state.result
  // Same count as the report's "To review": non-compliant, missing and needs review.
  const review = r ? r.counts.non_compliant + r.counts.missing + r.counts.needs_review : null
  const onShops = st.extract_shop !== 'pending'
  const previewFile = onShops ? shops[0] ?? null : plans[0] ?? null
  const pages = usePdfPages(previewFile)
  const [page, setPage] = useState(1)
  const [logOpen, setLogOpen] = useState(false)
  const shown = pages ? Math.min(page, pages) : 1
  const boxes = onShops ? SHOP_DETECTIONS : st.extract_plan !== 'pending' ? PLAN_DETECTIONS : []

  const indicators: [string, string | null, string?][] = [
    ['Plan elements', state.details.extract_plan?.split(' ')[0] ?? null],
    ['Shop elements', state.details.extract_shop?.split(' ')[0] ?? null],
    ['Compliant', r ? `${r.counts.compliant}` : null],
    ['To review', review === null ? null : `${review}`, review ? 'text-red' : undefined],
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className={label}>{onShops ? 'Shop sheet' : 'Plan sheet'}</span>
          {previewFile && pages !== null && pages > 1 && (
            <span className="flex items-center gap-1 font-mono text-[13px] tabular-nums">
              <StepButton aria="Previous page" disabled={shown <= 1} onClick={() => setPage(shown - 1)}><ChevronLeft className="size-4" aria-hidden /></StepButton>
              <span className="w-16 text-center text-fg">{shown} / {pages}</span>
              <StepButton aria="Next page" disabled={shown >= pages} onClick={() => setPage(shown + 1)}><ChevronRight className="size-4" aria-hidden /></StepButton>
            </span>
          )}
        </div>
        <div className="flex justify-center">
          <SheetThumb file={previewFile} page={shown} boxes={boxes} width={320} seed={onShops ? 2 : 1} />
        </div>
      </div>

      <div className="border-b border-line">
        <div className={`px-5 py-4 ${label}`}>Indicators</div>
        <dl className="grid grid-cols-2 border-t border-line">
          {indicators.map(([k, v, tone], i) => (
            <div key={k} className={`px-5 py-4 ${i % 2 ? 'border-l border-line' : ''} ${i > 1 ? 'border-t border-line' : ''}`}>
              <dt className={label}>{k}</dt>
              <dd className={`mt-1 min-h-9 font-mono text-3xl tabular-nums ${tone ?? 'text-fg'}`}>
                {v ?? (state.phase === 'running' ? <Skeleton /> : <span className="text-mute">—</span>)}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <button type="button" onClick={() => setLogOpen((o) => !o)} aria-expanded={logOpen} className={`flex items-center justify-between px-5 py-4 text-left hover:text-fg ${label}`}>
          <span>Run log {state.log.length ? `· ${state.log.length}` : ''}</span>
          <span className="font-mono text-sm tabular-nums text-fg">{logOpen ? 'Hide' : fmt(elapsed)}</span>
        </button>
        {logOpen && (
          <ol className="min-h-0 flex-1 overflow-y-auto border-t border-line font-mono text-[13px] leading-relaxed">
            {state.log.length === 0 && <li className="px-5 py-3 text-mute">No run yet.</li>}
            {state.log.map((l, i) => (
              <LogRow key={i} line={l} />
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}

function StepButton({ aria, disabled, onClick, children }: { aria: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={aria} disabled={disabled} onClick={onClick} className="grid size-7 place-items-center text-mute hover:text-fg disabled:opacity-30 disabled:hover:text-mute">
      {children}
    </button>
  )
}

function Skeleton() {
  return <motion.span className="block h-6 w-16 bg-line-2" animate={{ opacity: [0.4, 1, 0.4] }} transition={{ repeat: Infinity, duration: 1.4 }} />
}

function LogRow({ line }: { line: LogLine }) {
  return (
    <li className="flex gap-3 border-b border-line px-5 py-2">
      <span className="shrink-0 tabular-nums text-mute">{fmt(line.t)}</span>
      <span className={line.tone === 'bad' ? 'text-red' : 'text-fg/90'}>{line.text}</span>
    </li>
  )
}
