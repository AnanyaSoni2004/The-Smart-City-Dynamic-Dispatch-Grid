import type { Metrics } from '../types'

function Card({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`font-mono text-lg font-semibold ${accent ?? 'text-slate-100'}`}>
        {value}
      </div>
    </div>
  )
}

export default function MetricsBar({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-9">
      <Card label="Calls" value={String(m.calls)} />
      <Card label="Incidents" value={String(m.incidents_created)} />
      <Card label="Dupes merged" value={String(m.duplicates_merged)} />
      <Card label="Quarantined" value={String(m.false_quarantined)} accent="text-slate-400" />
      <Card label="Dispatches" value={`${m.dispatches}`} />
      <Card label="Backlog" value={String(m.backlog)}
        accent={m.backlog > 5 ? 'text-rose-400' : 'text-amber-300'} />
      <Card label="Resolved" value={String(m.resolved)} accent="text-emerald-400" />
      <Card label="Avg response"
        value={m.avg_response_min != null ? `${m.avg_response_min}m` : '–'} />
      <Card label="Lives saved ~" value={String(Math.round(m.lives_saved_est))}
        accent="text-emerald-300" />
    </div>
  )
}
