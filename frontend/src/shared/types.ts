import type { StepId } from './steps'

// Statuses from shared/schemas/findings.schema.json. `needs_review` is the safe default for
// any uncertain case, so it is never silently passed as compliant.
export type FindingStatus = 'compliant' | 'non_compliant' | 'missing' | 'added' | 'needs_review'

export type ElementType = 'fondation' | 'poutre' | 'mur_refend' | 'colonne' | 'dalle'

export interface Diff {
  field: string // e.g. quantite, diametre, espacement_mm
  plan: string | number | null
  shop: string | number | null
  delta: number | null
}

export interface SheetRef {
  fichier: string
  page: number
  x: number
  y: number
}

export interface Finding {
  id: string
  status: Exclude<FindingStatus, 'compliant'>
  type_element: ElementType
  grid: string | null // e.g. "J-12"
  level: string // e.g. "N2", "RDC", "FDN"
  check_type: string // e.g. "cross.plan_vs_shop"
  notes: string
  diffs: Diff[]
  plan_ref?: SheetRef
  shop_ref?: SheetRef
  confidence?: number
}

export interface RunResult {
  run_id: string
  project: string
  plan: string
  shop_drawings: string[]
  counts: Record<FindingStatus, number>
  findings: Finding[]
}

export type ProgressEvent =
  | { kind: 'step'; step: StepId; status: 'active' | 'done'; detail?: string }
  | { kind: 'result'; result: RunResult }
  | { kind: 'error'; message: string }
