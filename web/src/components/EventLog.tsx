import type { FeedEvent } from '../types'
import { fmtSimTime } from '../theme'

const KIND_STYLE: Record<string, string> = {
  created: 'text-rose-400',
  dispatch: 'text-amber-300',
  resolved: 'text-emerald-400',
}
const KIND_ICON: Record<string, string> = {
  created: '⚠',
  dispatch: '→',
  resolved: '✓',
}

export default function EventLog({ events }: { events: FeedEvent[] }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <h3 className="mb-3 text-sm font-semibold text-white">Dispatch log</h3>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500">Waiting for the first incident…</p>
      ) : (
        <ul className="max-h-64 space-y-1 overflow-y-auto pr-1 font-mono text-xs">
          {events.map((e, i) => (
            <li key={`${e.t}-${i}`} className="flex gap-2">
              <span className="shrink-0 text-slate-600">{fmtSimTime(e.t)}</span>
              <span className={`shrink-0 ${KIND_STYLE[e.kind]}`}>{KIND_ICON[e.kind]}</span>
              <span className="text-slate-300">{e.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
