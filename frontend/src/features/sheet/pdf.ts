import { useEffect, useState } from 'react'

// One pdf.js document per file, loaded on first use and reused by every preview of it.
type PdfDoc = import('pdfjs-dist').PDFDocumentProxy
const cache = new WeakMap<File, Promise<PdfDoc>>()

async function pdfjsLib() {
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerSrc = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  return pdfjs
}

export function loadPdf(file: File): Promise<PdfDoc> {
  let doc = cache.get(file)
  if (!doc) {
    doc = (async () => (await pdfjsLib()).getDocument({ data: await file.arrayBuffer() }).promise)()
    cache.set(file, doc)
  }
  return doc
}

// The same for a PDF the API serves (a run's uploaded file, when the browser no longer holds it).
const byUrl = new Map<string, Promise<PdfDoc>>()

export function loadPdfSource(src: File | string): Promise<PdfDoc> {
  if (typeof src !== 'string') return loadPdf(src)
  let doc = byUrl.get(src)
  if (!doc) {
    doc = (async () => (await pdfjsLib()).getDocument({ url: src }).promise)()
    byUrl.set(src, doc)
  }
  return doc
}

// Page count of a PDF: null while loading, 0 when the file can't be read (placeholder or corrupt).
export function usePdfPages(file: File | null): number | null {
  const [pages, setPages] = useState<number | null>(null)
  useEffect(() => {
    if (!file) return
    let cancelled = false
    loadPdf(file)
      .then((d) => !cancelled && setPages(d.numPages))
      .catch(() => !cancelled && setPages(0))
    return () => {
      cancelled = true
    }
  }, [file])
  return file ? pages : null
}
