import { motion } from 'framer-motion'
import { link } from '../../shared/ui'
import { CORE, ROW } from './geometry'

// The core: the comparison box in the centre. Run while idle, progress while running, retry on failure.
export function Core({ mode, label, progress, error, summary, onRetry }: {
  mode: 'idle' | 'running' | 'error'
  label: string
  progress: number
  error?: string
  summary: string
  onRetry: () => void
}) {
  return (
    <motion.div
      initial={false}
      animate={{ top: ROW.core - CORE.h / 2, borderColor: mode === 'running' ? '#f2b33d' : mode === 'error' ? '#ff5f4f' : '#3b414c' }}
      style={{ left: CORE.x, width: CORE.w, height: CORE.h }}
      className="absolute border bg-panel"
    >
      {mode === 'idle' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
          <span className="font-mono text-[13px] uppercase tracking-[0.12em] text-mute">Compare</span>
          <span className="px-3 text-base text-fg/85">{summary || 'Waiting for files'}</span>
        </div>
      )}
      {mode === 'running' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
          <span className="font-mono text-[13px] uppercase tracking-[0.12em] text-amber">Running</span>
          <span className="text-lg font-medium">{label}</span>
          <span className="absolute inset-x-3 bottom-3 h-px bg-line-2">
            <motion.span className="block h-px bg-amber" animate={{ width: `${progress * 100}%` }} transition={{ duration: 0.6 }} />
          </span>
        </div>
      )}
      {mode === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-4 text-center">
          <p className="font-mono text-sm text-red">{error}</p>
          <button type="button" onClick={onRetry} className={link}>Try again</button>
        </div>
      )}
    </motion.div>
  )
}
