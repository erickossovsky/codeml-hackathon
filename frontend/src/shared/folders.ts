// Shop drawings live in a DA/ tree grouped by element type (Colonnes, Poutres, Dalles,
// Fondations, Refends or Murs). This reads that grouping from the file's folder path.
const TYPE_FOLDERS: [RegExp, string][] = [
  [/colonne/i, 'Colonnes'],
  [/poutre/i, 'Poutres'],
  [/dalle/i, 'Dalles'],
  [/fondation/i, 'Fondations'],
  [/refend|mur/i, 'Refends'],
]

export function elementFolder(file: File): string | null {
  const parts = (file as File & { webkitRelativePath?: string }).webkitRelativePath?.split('/') ?? []
  for (const part of parts) {
    const hit = TYPE_FOLDERS.find(([re]) => re.test(part))
    if (hit) return hit[1]
  }
  return null
}

// e.g. { Colonnes: 12, Poutres: 9 }. Files without a known folder are counted as "Other".
export function summarizeFolders(files: File[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of files) {
    const key = elementFolder(f) ?? 'Other'
    out[key] = (out[key] ?? 0) + 1
  }
  return out
}
