import type { Box } from './SheetThumb'

// Mock detections, shown while extraction runs. A real backend would send these per sheet.
export const PLAN_DETECTIONS: Box[] = [
  { x: 0.1, y: 0.14, w: 0.14, h: 0.08 },
  { x: 0.34, y: 0.2, w: 0.1, h: 0.1 },
  { x: 0.56, y: 0.12, w: 0.16, h: 0.07 },
  { x: 0.2, y: 0.46, w: 0.12, h: 0.09 },
  { x: 0.48, y: 0.5, w: 0.15, h: 0.08 },
  { x: 0.72, y: 0.4, w: 0.1, h: 0.12 },
]

export const SHOP_DETECTIONS: Box[] = [
  { x: 0.12, y: 0.2, w: 0.12, h: 0.1 },
  { x: 0.4, y: 0.16, w: 0.14, h: 0.08 },
  { x: 0.25, y: 0.52, w: 0.18, h: 0.08 },
  { x: 0.62, y: 0.46, w: 0.12, h: 0.1 },
]
