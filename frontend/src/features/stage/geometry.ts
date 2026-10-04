// The drawing sits on a fixed 1200 x 560 canvas, scaled to fit the window.
// The core is centred on the canvas, so the output reads as the middle of the flow.
export const CANVAS = { w: 1200, h: 560 }

export type Point = { x: number; y: number }

// Lane heights. Wires run along these rows; the core sits between them.
export const ROW = { plan: 160, shop: 400, core: 280 } as const

export const SRC = { x: 0, w: 200, minH: 120 } as const
export const STN = { x: 250, w: 190, closedH: 120, openH: 180 } as const
export const TRUNK_X = 480
export const CORE = { x: 500, w: 200, h: 140 } as const

// Output boxes to the right of the core: findings, then the report.
export const FIND = { x: 800, w: 200, h: 120 } as const
export const REPORT = { x: 1040, w: 160, h: 120 } as const
export const WELL_X = STN.x + STN.w / 2

// Where a file sits inside an open station: the bottom third, centred.
export const wellY = (row: number) => row + STN.openH / 2 - 26

// The full path a file takes down one lane, bend by bend, into the core.
export function routeFor(row: number): Point[] {
  const well = wellY(row)
  return [
    { x: SRC.w, y: row },
    { x: STN.x, y: row },
    { x: STN.x, y: well },
    { x: WELL_X, y: well },
    { x: STN.x + STN.w, y: well },
    { x: STN.x + STN.w, y: row },
    { x: TRUNK_X, y: row },
    { x: TRUNK_X, y: ROW.core },
    { x: CORE.x - 12, y: ROW.core },
  ]
}

// Token state (0 at source, 1 in the station well, 2 at the core) -> route indices.
// A token only moves forward, so each state animates from where the previous one left off.
export const STATE_TO_ROUTE = [0, 3, 8] as const
export const STATE_FROM_ROUTE = [0, 0, 3] as const
