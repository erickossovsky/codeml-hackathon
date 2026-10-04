import { describe, expect, it } from 'vitest'
import { splitProject } from './dropFiles'

const file = (path: string) => {
  const f = new File(['%PDF'], path.split('/').at(-1)!, { type: 'application/pdf' })
  Object.defineProperty(f, 'webkitRelativePath', { value: path })
  return f
}

describe('splitProject', () => {
  it('takes the plans from the top of a project folder and the shop drawings from DA/', () => {
    const files = [file('P1/STR_SET.pdf'), file('P1/DA/Colonnes/C1.pdf'), file('P1/DA/Dalles/S1.pdf')]
    const { plans, shops } = splitProject(files)
    expect(plans.map((f) => f.name)).toEqual(['STR_SET.pdf'])
    expect(shops.map((f) => f.name)).toEqual(['C1.pdf', 'S1.pdf'])
  })

  it('sorts loose files by name when there is no DA/ folder', () => {
    const { plans, shops } = splitProject([file('PLAN_A.pdf'), file('beams.pdf')])
    expect(plans.map((f) => f.name)).toEqual(['PLAN_A.pdf'])
    expect(shops.map((f) => f.name)).toEqual(['beams.pdf'])
  })
})
