// The pipeline as the backend runs it: ingest -> extract (plan, shops) -> compare -> report.
export const STEPS = [
  { id: 'ingest', label: 'Ingest', detail: 'Reading PDFs' },
  { id: 'extract_plan', label: 'Plan', detail: 'Extracting elements' },
  { id: 'extract_shop', label: 'Shop drawings', detail: 'Extracting elements' },
  { id: 'compare', label: 'Compare', detail: 'Matching by grid and level' },
  { id: 'report', label: 'Report', detail: 'Writing findings and PDF' },
] as const

export type StepId = (typeof STEPS)[number]['id']
