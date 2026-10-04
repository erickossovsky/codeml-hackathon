import { describe, expect, it } from 'vitest'
import { STEPS } from './steps'

describe('steps', () => {
  it('follows the backend order: ingest, extract, compare, report', () => {
    expect(STEPS.map((s) => s.id)).toEqual(['ingest', 'extract_plan', 'extract_shop', 'compare', 'report'])
  })
})
