import { useEffect, useState } from 'react'

// One pdf.js document per file, loaded on first use and reused by every preview of it.
type PdfDoc = import('pdfjs-dist').PDFDocumentProxy
const cache = new WeakMap<File, Promise<PdfDoc>>()

export function loadPdf(file: File): Promise<PdfDoc> {
  let doc = cache.get(file)
  if (!doc) {
    doc = (async () => {
      const pdfjs = await import('pdfjs-dist')
      pdfjs.GlobalWorkerOptions.workerSrc = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
      return pdfjs.getDocument({ data: await file.arrayBuffer() }).promise
    })()
    cache.set(file, doc)
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
