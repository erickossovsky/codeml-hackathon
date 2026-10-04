// Learn2Compare mark: a plan wire and a shop wire meet at one comparison node, and the
// result leaves to the right. It is the pipeline itself, so it reads as the product.
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <rect x="1" y="1" width="30" height="30" stroke="currentColor" strokeWidth="2" />
      <path d="M4 9 H12 Q16 9 16 13 V16" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M28 23 H20 Q16 23 16 19 V16" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <rect x="12" y="12" width="8" height="8" fill="currentColor" />
      <path d="M19 16 H28" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
    </svg>
  )
}

// Wordmark: "Learn" and "Compare" in the sans, the "2" in the mono as the joint between them.
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="flex items-center gap-3 text-fg">
      <LogoMark size={size} />
      <span className="flex items-baseline text-[17px] font-semibold tracking-tight">
        Learn
        <span className="mx-[1px] font-mono text-[15px] font-medium">2</span>
        Compare
      </span>
    </span>
  )
}
