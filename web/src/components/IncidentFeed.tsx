import type { IncidentView } from '../types'
import { INCIDENT_COLORS } from '../theme'

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-rose-500/15 text-rose-400',
  dispatched: 'bg-amber-500/15 text-amber-300',
  on_scene: 'bg-sky-500/15 text-sky-300',
}

export default function IncidentFeed({ incidents }: { incidents: IncidentView[] }) {
  const active = incidents
    .filter(i => i.status !== 'resolved')
    .sort((a, b) => b.pri - a.pri)
  const resolved = incidents.filter(i => i.status === 'resolved').length

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-white">Incident queue</h3>
        <span className="text-xs text-slate-500">{resolved} resolved</span>
      </div>
      {active.length === 0 ? (
        <p className="text-sm text-slate-500">No active incidents.</p>
      ) : (
        <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
          {active.slice(0, 20).map(inc => (
            <li key={inc.id}
              className="flex items-center gap-2 rounded-lg bg-slate-950/60 px-2.5 py-1.5 text-xs">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: INCIDENT_COLORS[inc.type] ?? '#94a3b8' }} />
              <span className="font-mono text-slate-400">{inc.id}</span>
              <span className="truncate text-slate-200">
                {inc.loc ?? 'location unknown'}
              </span>
              <span className="ml-auto shrink-0 text-slate-500">
                sev {inc.sev} · {inc.people}p
              </span>
              <span className={`shrink-0 rounded-full px-1.5 py-0.5 ${STATUS_STYLE[inc.status] ?? 'bg-slate-700/40 text-slate-400'}`}>
                {inc.status.replace('_', ' ')}
              </span>
              <span className="w-10 shrink-0 text-right font-mono text-orange-300">
                {inc.pri.toFixed(0)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
