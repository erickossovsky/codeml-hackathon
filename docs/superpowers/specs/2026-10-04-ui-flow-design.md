# UI Flow: Mock-First Design

Date: 2026-10-04
Branch: `eric/ui-flow` (off `dev`)
Status: draft, awaiting review

## Goal

A single-screen web UI that shows the CodeML flow as it runs, then shows the
final result with downloads. It must be impressive and minimal: one step in
focus at a time, little text, no info overload.

## Scope (this iteration)

In:
- One page in `frontend/`.
- Upload of one plan PDF and one or more shop drawing PDFs (files are held in
  the browser only; nothing is sent anywhere yet).
- A run animation: the flow steps light up in order, with a short label and an
  icon for each.
- A result view: summary counts, findings list, and two downloads
  (`findings.json`, summary `.pdf`).
- All data comes from a mock client that replays fixture JSON on a timer.

Out:
- Real backend calls, auth, persistence, multi-run history, editing, mobile
  polish beyond not breaking.

## Flow steps (display order)

1. Ingest: read the PDFs (page count, file names).
2. Extract plan: elements from the plan.
3. Extract shop: elements from each shop drawing.
4. Compare: match plan vs shop.
5. Findings: compliant / non-compliant / missing / added counts.
6. Report: build the summary PDF.

Step names are placeholders until the lanes confirm them. Keep them in one
constant list so they can change in one place.

## Architecture

```
frontend/
  src/
    App.tsx                 screen state: idle -> running -> done
    api/client.ts           interface: startRun(files) and subscribe(runId)
    api/mockClient.ts       mock implementation, replays fixtures on a timer
    features/upload/        drop zone and file list
    features/flow/          step rail with the animated stepper
    features/result/        summary, findings list, download buttons
    shared/steps.ts         step list constant
    shared/types.ts         types for the run and findings (mirrors shared/schemas)
  public/fixtures/          sample findings.json and report.pdf
```

Data contract: the UI types follow `shared/schemas/findings.schema.json`. The
mock reads a fixture that already matches that schema, so the swap to the real
client later is one file.

Client interface (the only thing the screen calls):
- `startRun(files: File[]): Promise<{ runId: string }>`
- `onProgress(runId, cb)` emits `{ step, status: "active" | "done" }` events,
  then a final `{ result }` event.

## Stack

- Vite, React, TypeScript.
- Tailwind CSS for styling.
- `lucide-react` for icons (no emoji, no hand-drawn SVG icons).
- `framer-motion` for step transitions and the progress line.
- No router, no state library. `useState` and a reducer are enough.

## Visual rules

- Neutral background, one accent colour, sharp type, generous spacing.
- Motion only where it explains state (step activation, result reveal).
- No gradients blobs, no sparkles, no gratuitous glassmorphism.
- Text per step: one short label, one line of detail at most.

## Error handling

- Non-PDF file: rejected in the drop zone with an inline message.
- Mock client error path: a single error state with a retry button. Exercised
  by a `?fail=1` query flag for demo use.

## Testing

- Unit: reducer for run state; step list order.
- Component: upload accepts only PDFs; result renders counts from fixture.
- Manual: run the mock end to end with `npm run dev` and check the animation
  and both downloads.

## Open questions

- Final step names and any extra step (e.g. OCR) from the extraction lane.
- Real backend interface: deferred to the API step after the mock works.
