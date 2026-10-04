import { STEPS, type StepId } from '../../shared/steps'
import type { StepStatus } from '../../state/runReducer'

// Thin progress rail. The diagram already shows each step's detail, so this only shows position.
export function Timeline({ stepStatus }: { stepStatus: Record<StepId, StepStatus> }) {
  return (
    <ol className="grid grid-cols-6 gap-1 border-t border-line px-5 py-3">
      {STEPS.map((s, i) => {
        const st = stepStatus[s.id]
        return (
          <li key={s.id} className="flex min-w-0 flex-col gap-2">
            <span className={`h-[3px] ${st === 'done' ? 'bg-fg' : st === 'active' ? 'bg-amber' : 'bg-line-2'}`} />
            <span className={`truncate font-mono text-[12px] uppercase tracking-[0.1em] ${st === 'pending' ? 'text-mute' : 'text-fg'}`}>
              {String(i + 1).padStart(2, '0')} {s.label}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
