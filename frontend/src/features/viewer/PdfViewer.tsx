import { Minus, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { SheetRef } from '../../shared/types'
import { label } from '../../shared/ui'
import { loadPdfSource } from '../sheet/pdf'

export interface ViewTarget {
  title: string // "Plan" or "Shop drawing"
  ref: SheetRef
  src: File | string // the dropped file, or the API's copy of it
}

const ZOOMS = [0.5, 0.75, 1, 1.5, 2, 3]

// A finding's place on both documents, side by side: each pane opens the exact page and centres a
// marker on the finding's X, Y (PDF points from the page's top-left corner, as the report gives them).
export function PdfViewer({ targets, onClose }: { targets: ViewTarget[]; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg/95" role="dialog" aria-label="Finding on the drawings">
      <div className="flex items-center justify-between border-b border-line px-6 py-3">
        <span className={label}>Finding on the drawings · Esc to close</span>
        <button type="button" onClick={onClose} aria-label="Close" className="p-2 text-mute hover:text-fg">
          <X className="size-5" aria-hidden />
        </button>
      </div>
      <div className={`grid min-h-0 flex-1 gap-px bg-line ${targets.length > 1 ? 'md:grid-cols-2' : ''}`}>
        {targets.map((t) => (
          <Pane key={`${t.title}:${t.ref.fichier}:${t.ref.page}`} target={t} />
        ))}
      </div>
    </div>
  )
}

function Pane({ target }: { target: ViewTarget }) {
  const { ref, src, title } = target
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [zoom, setZoom] = useState(1.5)
  const [state, setState] = useState<{ key: string; size?: { w: number; h: number }; error?: string }>({ key: '' })
  const key = `${typeof src === 'string' ? src : src.name}:${ref.page}:${zoom}`
  const ready = state.key === key && state.size

  useEffect(() => {
    let cancelled = false
    let task: { cancel: () => void } | null = null
    ;(async () => {
      try {
        const doc = await loadPdfSource(src)
        const page = await doc.getPage(Math.min(Math.max(ref.page, 1), doc.numPages))
        const vp = page.getViewport({ scale: zoom })
        const el = canvas.current
        if (!el || cancelled) return
        el.width = vp.width
        el.height = vp.height
        const render = page.render({ canvasContext: el.getContext('2d')!, viewport: vp, canvas: el })
        task = render
        await render.promise
        if (cancelled) return
        setState({ key, size: { w: vp.width, h: vp.height } })
        // centre the marker in the pane
        const b = box.current
        if (b) {
          b.scrollLeft = ref.x * zoom - b.clientWidth / 2
          b.scrollTop = ref.y * zoom - b.clientHeight / 2
        }
      } catch (err) {
        if (!cancelled) setState({ key, error: String(err) })
      }
    })()
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [src, ref.page, ref.x, ref.y, zoom, key])

  const i = ZOOMS.indexOf(zoom)
  return (
    <section className="flex min-h-0 flex-col bg-bg">
      <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-2.5">
        <p className="min-w-0 truncate font-mono text-sm">
          <span className="text-mute">{title} · </span>
          {ref.fichier} · page {ref.page} · x {ref.x.toFixed(0)} y {ref.y.toFixed(0)}
        </p>
        <span className="flex shrink-0 items-center gap-1 font-mono text-[13px] tabular-nums">
          <button type="button" aria-label="Zoom out" disabled={i <= 0} onClick={() => setZoom(ZOOMS[i - 1])} className="grid size-7 place-items-center text-mute hover:text-fg disabled:opacity-30">
            <Minus className="size-4" aria-hidden />
          </button>
          <span className="w-12 text-center">{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="Zoom in" disabled={i >= ZOOMS.length - 1} onClick={() => setZoom(ZOOMS[i + 1])} className="grid size-7 place-items-center text-mute hover:text-fg disabled:opacity-30">
            <Plus className="size-4" aria-hidden />
          </button>
        </span>
      </div>
      <div ref={box} className="relative min-h-0 flex-1 overflow-auto bg-white">
        {state.key === key && state.error && <p className="p-6 font-mono text-sm text-red">Could not open {ref.fichier}: {state.error}</p>}
        {!ready && !state.error && <p className="absolute left-6 top-6 font-mono text-sm text-mute">Opening page {ref.page}…</p>}
        <div className="relative" style={ready ? { width: state.size!.w, height: state.size!.h } : undefined}>
          <canvas ref={canvas} className={ready ? 'block' : 'invisible absolute'} />
          {ready && (
            <span
              aria-hidden
              className="pointer-events-none absolute size-16 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-red shadow-[0_0_0_4px_rgba(255,255,255,0.7)]"
              style={{ left: ref.x * zoom, top: ref.y * zoom }}
            />
          )}
        </div>
      </div>
    </section>
  )
}
