import { motion } from 'framer-motion'
import { useState } from 'react'
import type { StepStatus } from '../../state/runReducer'
import { ROW, SRC, STATE_FROM_ROUTE, STATE_TO_ROUTE, STN, type Point } from './geometry'
import { label as label_, link } from '../../shared/ui'
import { summarizeFolders } from '../../shared/folders'
import { filesFromDrop } from '../../shared/dropFiles'
import { SheetThumb } from '../sheet/SheetThumb'

const KEY = 'font-mono text-xs uppercase tracking-[0.14em]'

// Source: an input box. Empty it is a drop target. Filled it shows a count, and "Review"
// opens a scrollable list where single files can be removed, so 70 files stay manageable.
export function Source({ row, label, names, file, rejected, reading, onPick, onClear, onRemove, onDrop, onFolder, folders }: {
  row: number; label: string; names: string[]; file: File | null; rejected: boolean; reading: boolean
  onPick: () => void; onClear: () => void; onRemove: (index: number) => void; onDrop: (files: File[]) => void
  onFolder?: () => void; folders?: File[]
}) {
  const [reviewing, setReviewing] = useState(false)
  const groups = Object.entries(summarizeFolders(folders ?? []))
  const filled = names.length > 0
  const open = filled && reviewing
  const h = open ? 330 : filled ? 150 : SRC.minH

  return (
    <motion.div
      initial={false}
      animate={{ top: row - h / 2, height: h }}
      transition={{ type: 'spring', stiffness: 220, damping: 26 }}
      style={{ left: SRC.x, width: SRC.w }}
      onClick={!filled ? onPick : undefined}
      onDragOver={(e) => e.preventDefault()}
      // a dropped folder is walked into; the drop stops here so the stage does not add the files again
      onDrop={(e) => { e.preventDefault(); e.stopPropagation(); void filesFromDrop(e.dataTransfer).then(onDrop) }}
      className={`absolute overflow-hidden border bg-panel transition-colors duration-300 ${
        filled ? 'border-line-2' : 'cursor-pointer border-dashed border-line-2 hover:border-mute'
      }`}
    >
      <div className="absolute inset-x-3 top-3 flex items-center justify-between">
        <span className={label_}>{label}</span>
        {rejected && <span className="font-mono text-[13px] text-red">PDF only</span>}
        {reading && !rejected && <span className="font-mono text-[13px] text-amber">reading</span>}
      </div>

      {!filled && (
        <div className="absolute inset-x-3 top-11">
          <span className="block text-xl leading-snug text-fg/80">Drop PDFs<br /><span className="text-base text-mute">or click to choose</span></span>
        </div>
      )}

      {filled && !open && (
        <>
          <div className="absolute inset-x-3 top-11 flex items-end gap-3">
            <div className="min-w-0 flex-1">
              <span className="block font-mono text-2xl tabular-nums text-fg">{names.length}</span>
              <span className="block font-mono text-[13px] text-mute">{names.length === 1 ? 'file' : 'files'}</span>
              {groups.length > 0 && <span className="mt-1 block truncate font-mono text-[12px] text-mute">{groups.map(([k, v]) => `${k} ${v}`).join(' · ')}</span>}
            </div>
            {file && (
              <div className="shrink-0">
                <SheetThumb file={file} width={48} seed={label.length} />
              </div>
            )}
          </div>
          <div className="absolute inset-x-3 bottom-3 flex gap-4">
            <button type="button" onClick={onPick} className={link}>Add</button>
            <button type="button" onClick={() => setReviewing(true)} className={link}>Review</button>
            {onFolder && <button type="button" onClick={onFolder} className={link}>Folder</button>}
            <button type="button" onClick={onClear} className={`${link} text-mute`}>Clear</button>
          </div>
        </>
      )}

      {open && (
        <>
          <div className="absolute inset-x-3 top-11 flex items-baseline justify-between">
            <span className="font-mono text-base tabular-nums">{names.length} files</span>
            <button type="button" onClick={() => setReviewing(false)} className={link}>Done</button>
          </div>
          <ul className="absolute inset-x-0 top-[72px] bottom-12 overflow-y-auto border-y border-line">
            {names.map((n, i) => (
              <li key={`${n}-${i}`} className="group flex items-center justify-between gap-2 px-3 py-1.5 hover:bg-raised">
                <span className="min-w-0 truncate font-mono text-[13px]" title={n}>{n}</span>
                <button type="button" onClick={() => onRemove(i)} aria-label={`Remove ${n}`} className="shrink-0 px-1 font-mono text-[13px] text-mute hover:text-red">✕</button>
              </li>
            ))}
          </ul>
          <div className="absolute inset-x-3 bottom-3 flex gap-4">
            <button type="button" onClick={onPick} className={link}>Add</button>
            <button type="button" onClick={onClear} className={`${link} text-mute`}>Clear all</button>
          </div>
        </>
      )}
    </motion.div>
  )
}

const STATUS_WORD: Record<StepStatus, string> = { pending: 'queued', active: 'running', done: 'done' }

// Station: a box on its lane. It opens when a file arrives; the file sits in its well.
export function Station({ row, index, title, status, detail }: {
  row: number; index: string; title: string; status: StepStatus; detail?: string
}) {
  const open = status !== 'pending'
  const h = open ? STN.openH : STN.closedH
  const active = status === 'active'
  const bar = status === 'done' ? STN.w - 24 : active ? 70 : 0

  return (
    <motion.div
      initial={false}
      animate={{ top: row - h / 2, height: h }}
      transition={{ type: 'spring', stiffness: 170, damping: 22 }}
      style={{ left: STN.x, width: STN.w }}
      className={`absolute border bg-panel transition-colors duration-300 ${active ? 'border-amber' : open ? 'border-fg/60' : 'border-line-2'}`}
    >
      <div className={`absolute inset-x-3 top-3 flex items-center justify-between ${KEY} ${active ? 'text-amber' : 'text-mute'}`}>
        <span>{index}</span>
        <span>{STATUS_WORD[status]}</span>
      </div>
      <div className={`absolute inset-x-3 top-9 text-base font-medium ${open ? 'text-fg' : 'text-mute'}`}>{title}</div>
      {detail && status === 'done' && (
        <div className="absolute inset-x-3 top-[58px] font-mono text-[13px] text-mute">{detail}</div>
      )}
      <div className="absolute inset-x-3 top-[92px] h-px bg-line-2" />
      <motion.div className={`absolute left-3 top-[92px] h-px ${active ? 'bg-amber' : 'bg-fg'}`} initial={false}
        animate={{ width: bar }} transition={{ duration: 0.7, ease: 'easeInOut' }} />
    </motion.div>
  )
}

const TOKEN_TEXT = ['PDF', 'ELEM', 'CMP'] as const

// A file is a small amber tag that travels its route and changes its text at each state.
export function Token({ route, state }: { route: Point[]; state: 0 | 1 | 2 }) {
  const hops = route.slice(STATE_FROM_ROUTE[state], STATE_TO_ROUTE[state] + 1)
  const n = hops.length
  return (
    <motion.div
      className="absolute z-20 -translate-x-1/2 -translate-y-1/2"
      initial={false}
      animate={{
        left: n > 1 ? hops.map((p) => p.x) : hops[0].x,
        top: n > 1 ? hops.map((p) => p.y) : hops[0].y,
      }}
      transition={{ duration: 0.4 * Math.max(n - 1, 0.001), ease: 'easeInOut' }}
    >
      <span className="block bg-amber px-2 py-1 font-mono text-xs tracking-wider text-bg">{TOKEN_TEXT[state]}</span>
    </motion.div>
  )
}

// Output box: sits on the core's row, fed from the core or the box before it.
export function OutputBox({ x, w, h, index, title, status, detail }: {
  x: number; w: number; h: number; index: string; title: string; status: StepStatus; detail?: string
}) {
  const active = status === 'active'
  const done = status === 'done'
  return (
    <motion.div
      initial={false}
      animate={{ top: ROW.core - h / 2, opacity: status === 'pending' ? 0.55 : 1, scale: active ? 1.03 : 1 }}
      transition={{ type: 'spring', stiffness: 200, damping: 20 }}
      style={{ left: x, width: w, height: h }}
      className={`absolute border bg-panel transition-colors duration-300 ${active ? 'border-amber' : done ? 'border-fg/60' : 'border-line-2'}`}
    >
      <div className={`absolute inset-x-3 top-3 flex items-center justify-between ${KEY} ${active ? 'text-amber' : 'text-mute'}`}>
        <span>{index}</span>
        <span>{STATUS_WORD[status]}</span>
      </div>
      <div className={`absolute inset-x-3 top-9 text-base font-medium ${status === 'pending' ? 'text-mute' : 'text-fg'}`}>{title}</div>
      {detail && done && <div className="absolute inset-x-3 top-[58px] font-mono text-[13px] text-mute">{detail}</div>}
    </motion.div>
  )
}
