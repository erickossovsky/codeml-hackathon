import { describe, expect, it } from 'vitest'
import { elementFolder, summarizeFolders } from './folders'

const file = (path: string) => Object.assign(new File(['%PDF'], path.split('/').pop()!), { webkitRelativePath: path })

describe('folders', () => {
  it('reads the element type from the DA folder path', () => {
    expect(elementFolder(file('DA/Colonnes/C-N2.pdf'))).toBe('Colonnes')
    expect(elementFolder(file('DA/Refends/R-1.pdf'))).toBe('Refends')
    expect(elementFolder(file('DA/Murs/M-1.pdf'))).toBe('Refends')
  })

  it('counts files per element type and keeps unknown folders as Other', () => {
    const files = [file('DA/Colonnes/a.pdf'), file('DA/Colonnes/b.pdf'), file('DA/Poutres/c.pdf'), file('loose.pdf')]
    expect(summarizeFolders(files)).toEqual({ Colonnes: 2, Poutres: 1, Other: 1 })
  })
})
