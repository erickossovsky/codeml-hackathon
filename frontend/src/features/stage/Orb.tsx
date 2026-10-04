import { motion } from 'framer-motion'
import { AlertTriangle, GitCompare, Play } from 'lucide-react'

const R = 58
const C = 2 * Math.PI * R

// Centre of the pipeline: Run button while idle, a progress ring while running.
export function Orb({ mode, progress, label, onRun, runDisabled, onRetry }: {
  mode: 'idle' | 'running' | 'error'
  progress: number // 0..1
  label: string
  onRun: () => void
  runDisabled: boolean
  onRetry: () => void
}) {
  const tone = mode === 'error' ? 'var(--color-bad)' : 'var(--color-accent)'
  return (
    <div className="relative grid size-40 place-items-center">
      <svg className="absolute inset-0 size-full -rotate-90" viewBox="0 0 140 140" aria-hidden>
        <circle cx="70" cy="70" r={R} fill="none" stroke="var(--color-line)" strokeWidth="2" />
        <motion.circle cx="70" cy="70" r={R} fill="none" stroke={tone} strokeWidth="2.5" strokeLinecap="round"
          strokeDasharray={C} animate={{ strokeDashoffset: C * (1 - progress) }} transition={{ duration: 0.8 }}
          style={{ filter: `drop-shadow(0 0 6px ${tone})` }} />
      </svg>

      <div className="grid size-28 place-items-center rounded-full border border-line bg-surface shadow-[0_0_80px_-20px_var(--color-accent)]">
        {mode === 'idle' && (
          <button type="button" onClick={onRun} disabled={runDisabled}
            className="grid size-16 place-items-center rounded-full bg-accent text-base transition-transform hover:scale-105 disabled:bg-raised disabled:text-muted disabled:hover:scale-100">
            <Play className="size-6 translate-x-0.5" aria-hidden />
          </button>
        )}
        {mode === 'running' && (
          <div className="flex flex-col items-center gap-1.5 text-center">
            <GitCompare className="size-5 text-accent" aria-hidden />
            <span className="max-w-[88px] text-[11px] leading-tight text-muted">{label}</span>
          </div>
        )}
        {mode === 'error' && (
          <button type="button" onClick={onRetry} className="flex flex-col items-center gap-1 text-bad">
            <AlertTriangle className="size-5" aria-hidden />
            <span className="text-[11px]">Retry</span>
          </button>
        )}
      </div>
    </div>
  )
}
