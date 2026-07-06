import type { Frame } from '../types'
import { UNIT_COLORS, UNIT_LABELS } from '../theme'

const SEGMENTS = [
  { key: 'available', color: '#10b981', label: 'available' },
  { key: 'dispatched', color: '#f59e0b', label: 'dispatched' },
  { key: 'returning', color: '#38bdf8', label: 'returning' },
  { key: 'out', color: '#475569', label: 'out' },
] as const

export default function ResourcePanel({ resources }: { resources: Frame['resources'] }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <h3 className="mb-3 text-sm font-semibold text-white">Fleet status</h3>
      <div className="space-y-2.5">
        {Object.entries(resources).map(([type, counts]) => {
          const total = SEGMENTS.reduce((s, seg) => s + (counts[seg.key] ?? 0), 0) || 1
          return (
            <div key={type}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-slate-300">
                  <span className="inline-block h-2 w-2 rounded-full"
                    style={{ background: UNIT_COLORS[type] ?? '#e2e8f0' }} />
                  {UNIT_LABELS[type] ?? type}
                </span>
                <span className="font-mono text-slate-500">
                  {counts.available}/{total} free
                </span>
              </div>
              <div className="flex h-2 overflow-hidden rounded-full bg-slate-950">
                {SEGMENTS.map(seg => (
                  <div key={seg.key} style={{
                    width: `${((counts[seg.key] ?? 0) / total) * 100}%`,
                    background: seg.color,
                  }} />
                ))}
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
        {SEGMENTS.map(seg => (
          <span key={seg.key} className="flex items-center gap-1">
            <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: seg.color }} />
            {seg.label}
          </span>
        ))}
      </div>
    </div>
  )
}
