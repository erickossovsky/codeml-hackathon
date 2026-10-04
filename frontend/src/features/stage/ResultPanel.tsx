import { useState } from 'react'
import { X } from 'lucide-react'
import type { Finding, FindingStatus, RunResult, SheetRef } from '../../shared/types'
import { btn, btnGhost, label } from '../../shared/ui'
import { usePdfPages } from '../sheet/pdf'

// Review sheet: laid out like an engineering title block. Each finding is one register line:
// where it is (grid and level), what differs (plan value vs shop value), and where to look.
// Outputs are findings.json and report.pdf.
const CODE: Record<FindingStatus, string> = { compliant: 'OK', non_compliant: 'NC', missing: 'MS', added: 'AD', needs_review: 'NR' }
const WORD: Record<FindingStatus, string> = {
  compliant: 'Compliant',
  non_compliant: 'Non-compliant',
  missing: 'Missing in shop',
  added: 'Added in shop',
  needs_review: 'Needs review',
}
// Red is for things that are wrong. Needs review is amber-free and dashed: it is a question, not a fault.
const TONE: Record<FindingStatus, string> = {
  compliant: 'text-fg',
  non_compliant: 'text-red',
  missing: 'text-red',
  added: 'text-fg',
  needs_review: 'text-fg/80',
}

const CELL = 'relative border-r border-b border-line-2 px-6 pb-6 pt-9'
const LABEL = `absolute left-6 top-3.5 ${label}`

export function ResultPanel({ result, file, onReset }: { result: RunResult; file: File | null; onReset: () => void }) {
  const [open, setOpen] = useState<Finding | null>(null)
  const json = `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(result, null, 2))}`
  const review = result.counts.non_compliant + result.counts.missing + result.counts.needs_review
  const planPages = usePdfPages(file)

  return (
    <div className="absolute inset-0 overflow-y-auto bg-bg">
      <div className="mx-auto max-w-6xl px-6 pb-12 pt-8 md:px-10">
        {/* Actions sit left, so the finding drawer on the right never covers them. */}
        <div className="mb-6 flex flex-col gap-4">
          <p className={label}>Review sheet · {result.run_id} · {result.project}</p>
          <div className="flex flex-wrap gap-3">
            <a href={json} download={`${result.run_id}-findings.json`} className={btn}>findings.json</a>
            <a href="/fixtures/report.pdf" download={`${result.run_id}-report.pdf`} className={btn}>report.pdf</a>
            <button type="button" onClick={onReset} className={btnGhost}>New run</button>
          </div>
        </div>

        <div className="border-l border-t-2 border-fg">
          <div className="grid grid-cols-1 border-b border-line-2 md:grid-cols-[2fr_1fr_1fr]">
            <div className={CELL}>
              <span className={LABEL}>Check</span>
              <p className="text-3xl font-semibold">Plan against shop drawings</p>
              <p className="mt-2 text-base text-mute">
                {file?.name ?? result.plan}{planPages ? ` · ${planPages} pages` : ''} · {result.shop_drawings.length} shop folders
              </p>
            </div>
            <div className={CELL}>
              <span className={LABEL}>To review</span>
              <p className={`font-mono text-7xl leading-none tabular-nums ${review ? 'text-red' : 'text-fg'}`}>{review}</p>
            </div>
            <div className={CELL}>
              <span className={LABEL}>Compliant</span>
              <p className="font-mono text-7xl leading-none tabular-nums">{result.counts.compliant}</p>
            </div>
          </div>
          <div className="border-b border-line-2 px-6 py-4 font-mono text-base text-fg/85">
            {result.counts.non_compliant} non-compliant <span className="text-mute">·</span> {result.counts.missing} missing
            <span className="text-mute"> · </span>{result.counts.added} added <span className="text-mute">·</span> {result.counts.needs_review} needs review
          </div>

          {result.findings.length === 0 ? (
            <p className="px-6 py-12 text-center text-lg text-mute">No differences found between the plan and the shop drawings.</p>
          ) : (
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-line-2 font-mono text-[13px] uppercase tracking-[0.12em] text-mute">
                  <th className="border-r border-line-2 px-6 py-3.5 font-normal">Ref</th>
                  <th className="border-r border-line-2 px-6 py-3.5 font-normal">Element · grid · level</th>
                  <th className="border-r border-line-2 px-6 py-3.5 font-normal">Plan value</th>
                  <th className="border-r border-line-2 px-6 py-3.5 font-normal">Shop value</th>
                  <th className="px-6 py-3.5 font-normal">Status</th>
                </tr>
              </thead>
              <tbody>
                {result.findings.map((f) => (
                  <FindingRow key={f.id} f={f} onOpen={() => setOpen(f)} />
                ))}
              </tbody>
            </table>
          )}
        </div>
        <p className="mt-4 font-mono text-[13px] text-mute">
          OK compliant · NC non-compliant · MS missing · AD added · NR needs review. Anything uncertain is NR, never silently OK.
        </p>
      </div>
      {open && (
        <aside className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col gap-6 border-l border-line-2 bg-panel p-6" role="dialog" aria-label={`Finding ${open.id}`}>
          <div className="flex items-start justify-between">
            <div>
              <p className={label}>{open.id} · {open.check_type}</p>
              <p className="mt-1 text-2xl font-semibold">{open.type_element.replace('_', ' ')} {open.grid ?? 'no grid'}</p>
            </div>
            <button type="button" onClick={() => setOpen(null)} aria-label="Close" className="p-2 text-mute hover:text-fg">
              <X className="size-5" aria-hidden />
            </button>
          </div>
          <p className={`font-mono text-base uppercase tracking-wider ${TONE[open.status]}`}>{WORD[open.status]}{open.notes ? ` · ${open.notes}` : ''}</p>
          {open.diffs.length > 0 && (
            <dl className="border-t border-line-2">
              {open.diffs.map((d) => (
                <div key={d.field} className="grid grid-cols-[1fr_1fr] gap-4 border-b border-line-2 py-3 font-mono text-sm">
                  <dt className="col-span-2 text-mute">{d.field}</dt>
                  <dd>plan <span className="text-fg">{d.plan ?? '—'}</span></dd>
                  <dd>shop <span className="text-fg">{d.shop ?? '—'}</span></dd>
                </div>
              ))}
            </dl>
          )}
          <RefLine label="Plan reference" r={open.plan_ref} />
          <RefLine label="Shop reference" r={open.shop_ref} />
          {open.confidence !== undefined && <p className="font-mono text-sm text-mute">Confidence {(open.confidence * 100).toFixed(0)}%</p>}
        </aside>
      )}
    </div>
  )
}

function RefLine({ label: name, r }: { label: string; r?: SheetRef }) {
  if (!r) return null
  return (
    <div className="border-t border-line-2 pt-4">
      <p className={label}>{name}</p>
      <p className="mt-1 font-mono text-sm">{r.fichier} · page {r.page} · x {r.x.toFixed(1)} y {r.y.toFixed(1)}</p>
    </div>
  )
}

function FindingRow({ f, onOpen }: { f: Finding; onOpen: () => void }) {
  const d = f.diffs[0]
  return (
    <tr onClick={onOpen} className="cursor-pointer border-b border-line-2 hover:bg-panel">
      <td className="whitespace-nowrap border-r border-line-2 px-6 py-5 font-mono text-base text-mute">{f.id}</td>
      <td className="border-r border-line-2 px-6 py-5">
        <span className="block text-xl">{f.type_element.replace('_', ' ')} <span className="font-mono text-base text-mute">{f.grid ?? 'no grid'}</span></span>
        <span className="block font-mono text-[13px] text-mute">{f.level} · {f.notes || f.check_type}</span>
      </td>
      <td className="border-r border-line-2 px-6 py-5 font-mono text-base">{d ? `${d.field} ${d.plan ?? '—'}` : '—'}</td>
      <td className="border-r border-line-2 px-6 py-5 font-mono text-base">{d ? `${d.field} ${d.shop ?? '—'}` : '—'}</td>
      <td className="px-6 py-5">
        <span className={`inline-flex items-center gap-3 whitespace-nowrap font-mono text-base uppercase tracking-wider ${TONE[f.status]}`}>
          <span className={`grid size-9 place-items-center border font-semibold ${f.status === 'needs_review' ? 'border-dashed border-current' : 'border-current'}`}>{CODE[f.status]}</span>
          {WORD[f.status]}
        </span>
      </td>
    </tr>
  )
}
