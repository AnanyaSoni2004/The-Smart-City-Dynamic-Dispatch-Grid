export default function Sparkline({ values, color, label, current }: {
  values: (number | null)[]
  color: string
  label: string
  current: string
}) {
  const W = 240
  const H = 44
  const nums = values.filter((v): v is number => v != null)
  const max = Math.max(1, ...nums)
  const pts = values
    .map((v, i) => v == null ? null
      : `${(i / Math.max(1, values.length - 1)) * W},${H - (v / max) * (H - 4) - 2}`)
    .filter(Boolean)
    .join(' ')
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-wide text-slate-500">{label}</span>
        <span className="font-mono text-sm" style={{ color }}>{current}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 h-11 w-full" preserveAspectRatio="none">
        {pts && <polyline points={pts} fill="none" stroke={color} strokeWidth={1.8} />}
      </svg>
    </div>
  )
}
