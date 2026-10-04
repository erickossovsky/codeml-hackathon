// Files from a drop, walking into dropped folders (a plain drop only lists the folder itself).
// Each file keeps its path inside the drop in `webkitRelativePath`, as the folder picker does,
// so the shop drawings' element folders (Colonnes, Dalles...) and a project's DA/ tree are known.

type Rel = File & { webkitRelativePath?: string }

function withPath(file: File, path: string): File {
  Object.defineProperty(file, 'webkitRelativePath', { value: path, configurable: true })
  return file
}

function fileOf(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

async function readAll(dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = dir.createReader()
  const out: FileSystemEntry[] = []
  // readEntries returns the listing in batches; an empty batch ends it
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
    if (batch.length === 0) return out
    out.push(...batch)
  }
}

async function walk(entry: FileSystemEntry, prefix: string, out: File[]) {
  if (entry.isFile) {
    out.push(withPath(await fileOf(entry as FileSystemFileEntry), prefix + entry.name))
  } else if (entry.isDirectory) {
    for (const child of await readAll(entry as FileSystemDirectoryEntry)) await walk(child, `${prefix}${entry.name}/`, out)
  }
}

export async function filesFromDrop(dt: DataTransfer): Promise<File[]> {
  // the entries must be taken while the drop event is still being handled, before any await
  const entries = Array.from(dt.items ?? [])
    .map((item) => item.webkitGetAsEntry?.() ?? null)
    .filter((e): e is FileSystemEntry => e !== null)
  if (entries.length === 0) return Array.from(dt.files)
  const out: File[] = []
  for (const e of entries) await walk(e, '', out)
  return out
}

export const relPath = (f: File) => (f as Rel).webkitRelativePath || f.name

// A project folder holds the plans at its top and the shop drawings under DA/. Without a DA/
// folder in the drop, a file is a plan when its name says so.
export function splitProject(files: File[]): { plans: File[]; shops: File[] } {
  const inDA = (f: File) => relPath(f).split('/').slice(0, -1).some((p) => p.toUpperCase() === 'DA')
  if (files.some(inDA)) return { plans: files.filter((f) => !inDA(f)), shops: files.filter(inDA) }
  return { plans: files.filter((f) => /plan/i.test(f.name)), shops: files.filter((f) => !/plan/i.test(f.name)) }
}
