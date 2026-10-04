import { useEffect, useRef, useState } from 'react'
import { STEPS } from '../../shared/steps'
import type { RunState, StepStatus } from '../../state/runReducer'
import { Canvas } from './Canvas'
import { Core } from './Core'
import { OutputBox, Source, Station, Token } from './Nodes'
import { CANVAS, CORE, FIND, REPORT, ROW, SRC, STN, TRUNK_X, routeFor } from './geometry'
import { ResultPanel } from './ResultPanel'
import { btn } from '../../shared/ui'
import { filesFromDrop, splitProject } from '../../shared/dropFiles'

interface Props {
  plans: File[]
  shops: File[]
  state: RunState
  onFiles: (kind: 'plan' | 'shop', files: File[]) => boolean // returns true if a non-PDF was rejected
  onClear: (kind: 'plan' | 'shop') => void
  onRemove: (kind: 'plan' | 'shop', index: number) => void
  onRetry: () => void
  onNewRun: () => void
}

const LABEL: Record<string, string> = {
  ingest: 'Reading sheets',
  extract_plan: 'Extracting plan',
  extract_shop: 'Extracting shops',
  compare: 'Comparing',
  report: 'Writing report',
}

const COLUMNS = [
  { x: SRC.x, label: '01 Input' },
  { x: STN.x, label: '02 Extract' },
  { x: CORE.x, label: '03 Compare' },
]

const pdfs = (list: FileList | File[]) => Array.from(list)

export function Stage({ plans, shops, state, onFiles, onClear, onRemove, onRetry, onNewRun }: Props) {
  const planInput = useRef<HTMLInputElement>(null)
  const shopInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const [rejected, setRejected] = useState<'plan' | 'shop' | null>(null)
  const [dragging, setDragging] = useState(false)
  // the run (by its start time) whose partial findings are open, so the view never carries over to the next run
  const [partialFor, setPartialFor] = useState<number | null>(null)
  const st = state.stepStatus
  const idle = state.phase === 'idle'
  const running = state.phase === 'running'
  const done = state.phase === 'done' && !!state.result
  const doneCount = STEPS.filter((s) => st[s.id] === 'done').length
  const activeId = STEPS.find((s) => st[s.id] === 'active')?.id
  const plan = plans[0] ?? null
  const showPartial = partialFor !== null && partialFor === state.startedAt
  const hasFiles = plans.length > 0 || shops.length > 0
  const summary = hasFiles ? `${plans.length} plan file${plans.length === 1 ? '' : 's'} · ${shops.length} shop file${shops.length === 1 ? '' : 's'}` : ''

  useEffect(() => {
    if (!rejected) return
    const t = window.setTimeout(() => setRejected(null), 2200)
    return () => window.clearTimeout(t)
  }, [rejected])

  const planState = (st.compare !== 'pending' ? 2 : st.extract_plan !== 'pending' ? 1 : 0) as 0 | 1 | 2
  const shopState = (st.compare !== 'pending' ? 2 : st.extract_shop !== 'pending' ? 1 : 0) as 0 | 1 | 2

  function add(kind: 'plan' | 'shop', list: FileList | File[]) {
    if (!idle) return
    const bad = onFiles(kind, pdfs(list).filter((f) => f.name.toLowerCase().endsWith('.pdf')))
    const any = pdfs(list).some((f) => !f.name.toLowerCase().endsWith('.pdf'))
    if (bad || any) setRejected(kind)
  }

  // Dropping anywhere on the stage: a project folder splits into its plans (top) and its shop
  // drawings (under DA/); loose files are sorted by name ("plan" in the name is a plan sheet).
  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (!idle) return
    void filesFromDrop(e.dataTransfer).then((files) => {
      const { plans: planFiles, shops: shopFiles } = splitProject(files.filter((f) => f.name.toLowerCase().endsWith('.pdf')))
      if (planFiles.length) add('plan', planFiles)
      if (shopFiles.length) add('shop', shopFiles)
    })
  }

  const wire = (s: StepStatus) => (s === 'pending' ? 'stroke-line-2' : s === 'active' ? 'stroke-amber' : 'stroke-fg')
  const srcEnd = SRC.x + SRC.w
  const stnEnd = STN.x + STN.w

  return (
    <div
      className={`panel-grid relative h-full w-full ${dragging ? 'outline outline-2 -outline-offset-8 outline-amber' : ''}`}
      onDragOver={(e) => { if (idle) { e.preventDefault(); setDragging(true) } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false) }}
      onDrop={onDrop}
    >
      {done && state.result ? (
        <ResultPanel result={state.result} file={plan} files={[...plans, ...shops]} onReset={onNewRun} />
      ) : running && showPartial && state.partial ? (
        <ResultPanel result={state.partial} file={plan} files={[...plans, ...shops]} onReset={() => setPartialFor(null)} resetLabel="Back to the run" />
      ) : (
        <Canvas>
          {COLUMNS.map((c) => (
            <span key={c.label} className="absolute font-mono text-[13px] uppercase tracking-[0.12em] text-mute" style={{ left: c.x, top: 10 }}>
              {c.label}
            </span>
          ))}
          <div className="absolute inset-x-0 top-[36px] h-px bg-line" />

          <div className="absolute inset-0">
            <svg className="absolute inset-0" width={CANVAS.w} height={CANVAS.h} viewBox={`0 0 ${CANVAS.w} ${CANVAS.h}`} aria-hidden>
              <path d={`M${srcEnd} ${ROW.plan} H${STN.x}`} fill="none" strokeWidth={1} className={`${wire(st.extract_plan)} transition-colors duration-500`} />
              <path d={`M${stnEnd} ${ROW.plan} H${TRUNK_X} V${ROW.core}`} fill="none" strokeWidth={1} className={`${wire(st.extract_plan)} transition-colors duration-500`} />
              <path d={`M${srcEnd} ${ROW.shop} H${STN.x}`} fill="none" strokeWidth={1} className={`${wire(st.extract_shop)} transition-colors duration-500`} />
              <path d={`M${stnEnd} ${ROW.shop} H${TRUNK_X} V${ROW.core}`} fill="none" strokeWidth={1} className={`${wire(st.extract_shop)} transition-colors duration-500`} />
              <path d={`M${TRUNK_X} ${ROW.core} H${CORE.x}`} fill="none" strokeWidth={1} className={`${wire(st.compare)} transition-colors duration-500`} />
              <path d={`M${CORE.x + CORE.w} ${ROW.core} H${FIND.x}`} fill="none" strokeWidth={1} className={`${wire(st.compare)} transition-colors duration-500`} />
              <path d={`M${FIND.x + FIND.w} ${ROW.core} H${REPORT.x}`} fill="none" strokeWidth={1} className={`${wire(st.report)} transition-colors duration-500`} />
            </svg>

            <Source row={ROW.plan} label="Plan" names={plans.map((f) => f.name)} file={plan}  rejected={rejected === 'plan'} reading={activeId === 'ingest'}
              onPick={() => planInput.current?.click()} onClear={() => idle && onClear('plan')} onRemove={(i) => idle && onRemove('plan', i)} onDrop={(l) => add('plan', l)} />
            <Source row={ROW.shop} label="Shop drawings" names={shops.map((f) => f.name)} file={shops[0] ?? null}  rejected={rejected === 'shop'} reading={activeId === 'ingest'}
              onPick={() => shopInput.current?.click()} onFolder={() => folderInput.current?.click()} folders={shops} onClear={() => idle && onClear('shop')} onRemove={(i) => idle && onRemove('shop', i)} onDrop={(l) => add('shop', l)} />
            <input ref={planInput} type="file" accept="application/pdf" multiple className="hidden" onChange={(e) => { add('plan', e.target.files ? pdfs(e.target.files) : []); e.target.value = '' }} />
            <input ref={folderInput} type="file" accept="application/pdf" multiple className="hidden" {...{ webkitdirectory: '' }} onChange={(e) => { add('shop', e.target.files ? pdfs(e.target.files) : []); e.target.value = '' }} />
            <input ref={shopInput} type="file" accept="application/pdf" multiple className="hidden" onChange={(e) => { add('shop', e.target.files ? pdfs(e.target.files) : []); e.target.value = '' }} />

            <OutputBox x={FIND.x} w={FIND.w} h={FIND.h} index="04" title="Findings" status={st.compare} detail={state.details.compare} />
            <OutputBox x={REPORT.x} w={REPORT.w} h={REPORT.h} index="05" title="Report" status={st.report} detail={state.details.report} />

            <Station row={ROW.plan} index="02" title="Extract plan" status={st.extract_plan} detail={state.details.extract_plan} />
            <Station row={ROW.shop} index="03" title="Extract shops" status={st.extract_shop} detail={state.details.extract_shop} />
          </div>

          {running && plans.length > 0 && <Token route={routeFor(ROW.plan)} state={planState} />}
          {running && shops.length > 0 && <Token route={routeFor(ROW.shop)} state={shopState} />}

          <Core
            mode={state.phase === 'error' ? 'error' : running ? 'running' : 'idle'}
            label={activeId ? LABEL[activeId] : 'Starting'}
            progress={doneCount / STEPS.length}
            error={state.error}
            summary={summary}
            onRetry={onRetry}
          />

          {!hasFiles && idle && (
            <p className="absolute font-mono text-[13px] text-mute" style={{ left: SRC.x, top: 500 }}>Drop your PDFs anywhere. Plans and shop drawings are sorted by file name.</p>
          )}

          {rejected && (
            <p className="absolute bottom-3 left-3 font-mono text-[13px] text-red">Only PDF files can be added.</p>
          )}
        </Canvas>
      )}
      {running && state.partial && !showPartial && (
        <button type="button" onClick={() => setPartialFor(state.startedAt ?? null)} className={`absolute bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 ${btn}`}>
          Partial findings · {state.partial.counts.non_compliant} non-compliant · {state.partial.counts.needs_review} to verify
          {state.partial.partial ? ` · ${state.partial.partial.shop_files_read}/${state.partial.partial.shop_files} shop files read` : ''} · open
        </button>
      )}
    </div>
  )
}
