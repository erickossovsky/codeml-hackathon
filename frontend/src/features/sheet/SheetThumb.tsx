import { motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { loadPdf } from './pdf'

export type Box = { x: number; y: number; w: number; h: number } // 0..1 of the sheet

// Renders one page of a real PDF with pdf.js. If the file can't be read (placeholder or
// corrupt), it draws a generic sheet so the layout still reads as a drawing.
export function SheetThumb({ file, page = 1, boxes = [], highlight, width, seed = 1, className = '' }: {
  file: File | null
  page?: number
  boxes?: Box[]
  highlight?: Box
  width: number
  seed?: number
  className?: string
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [loaded, setLoaded] = useState<{ key: string; mode: 'pdf' | 'drawn' } | null>(null)
  const key = file ? `${file.name}:${file.size}:${page}:${width}` : ''
  const mode = !file ? 'empty' : loaded && loaded.key === key ? loaded.mode : null
  const height = Math.round(width * 0.707)

  useEffect(() => {
    if (!file) return
    let cancelled = false
    ;(async () => {
      try {
        const doc = await loadPdf(file)
        const pg = await doc.getPage(Math.min(page, doc.numPages))
        const base = pg.getViewport({ scale: 1 })
        const vp = pg.getViewport({ scale: (width * 2) / base.width })
        const el = canvas.current
        if (!el || cancelled) return
        el.width = vp.width
        el.height = vp.height
        await pg.render({ canvasContext: el.getContext('2d')!, viewport: vp, canvas: el }).promise
        if (!cancelled) setLoaded({ key, mode: 'pdf' })
      } catch (err) {
        console.warn('sheet preview fell back to drawing:', err)
        if (!cancelled) setLoaded({ key, mode: 'drawn' })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [file, page, width, key])

  return (
    <div className={`relative shrink-0 overflow-hidden border border-line-2 bg-paper ${className}`} style={{ width, height }}>
      {file && <canvas ref={canvas} className={`size-full ${mode === 'pdf' ? '' : 'hidden'}`} />}
      {mode === 'drawn' && <DrawnSheet seed={seed} />}

      {boxes.map((b, i) => (
        <motion.span
          key={i}
          initial={{ opacity: 0, scale: 1.3 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: i * 0.06, duration: 0.25 }}
          className="absolute border border-amber"
          style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}
        />
      ))}
      {highlight && (
        <span
          className="absolute border-2 border-red"
          style={{ left: `${highlight.x * 100}%`, top: `${highlight.y * 100}%`, width: `${highlight.w * 100}%`, height: `${highlight.h * 100}%` }}
        />
      )}
    </div>
  )
}

// A generic structural sheet: grid, a few members, and a title block.
function DrawnSheet({ seed }: { seed: number }) {
  const rnd = (i: number) => {
    const x = Math.sin(seed * 97 + i * 13.7) * 10000
    return x - Math.floor(x)
  }
  const lines = Array.from({ length: 9 }, (_, i) => ({
    x: 0.08 + rnd(i) * 0.6,
    y: 0.1 + rnd(i + 20) * 0.6,
    l: 0.12 + rnd(i + 40) * 0.25,
    v: rnd(i + 60) > 0.5,
  }))
  return (
    <svg viewBox="0 0 100 70" preserveAspectRatio="none" className="size-full" aria-hidden>
      {Array.from({ length: 9 }, (_, i) => (
        <line key={`g${i}`} x1={i * 12.5} y1="0" x2={i * 12.5} y2="70" stroke="#d4cfc4" strokeWidth="0.15" />
      ))}
      {Array.from({ length: 6 }, (_, i) => (
        <line key={`h${i}`} x1="0" y1={i * 12} x2="100" y2={i * 12} stroke="#d4cfc4" strokeWidth="0.15" />
      ))}
      {lines.map((l, i) =>
        l.v ? (
          <line key={i} x1={l.x * 100} y1={l.y * 70} x2={l.x * 100} y2={(l.y + l.l) * 70} stroke="#161513" strokeWidth="0.6" />
        ) : (
          <line key={i} x1={l.x * 100} y1={l.y * 70} x2={(l.x + l.l) * 100} y2={l.y * 70} stroke="#161513" strokeWidth="0.6" />
        ),
      )}
      <rect x="66" y="56" width="32" height="11" fill="none" stroke="#161513" strokeWidth="0.5" />
      <line x1="66" y1="60" x2="98" y2="60" stroke="#161513" strokeWidth="0.4" />
    </svg>
  )
}
