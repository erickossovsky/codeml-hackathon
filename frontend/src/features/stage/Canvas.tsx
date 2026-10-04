import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { CANVAS } from './geometry'

const PAD = 28

// Scales the fixed-size drawing to fill the space it is given, keeping its proportions.
export function Canvas({ children }: { children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const fit = () => {
      const s = Math.min((el.clientWidth - PAD * 2) / CANVAS.w, (el.clientHeight - PAD * 2) / CANVAS.h)
      setScale(s)
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div ref={box} className="relative h-full w-full overflow-hidden">
      <div
        className="absolute left-1/2 top-1/2"
        style={{ width: CANVAS.w, height: CANVAS.h, transform: `translate(-50%, -50%) scale(${scale})`, transformOrigin: 'center' }}
      >
        {children}
      </div>
    </div>
  )
}
