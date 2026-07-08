import { useMemo } from 'react'
import type { Frame, Graph } from '../types'
import { INCIDENT_COLORS, UNIT_COLORS, UNIT_LABELS } from '../theme'

const PAD = 40

function edgeKey(a: number, b: number) {
  return a < b ? `${a}-${b}` : `${b}-${a}`
}

export default function CityMap({ graph, frame }: { graph: Graph; frame: Frame }) {
  // grid cities are ~12 units wide, real cities ~25 km tall: fit either
  const SCALE = Math.min(64, Math.max(34, 950 / Math.max(graph.width, graph.height)))
  const w = (graph.width - 1) * SCALE + PAD * 2
  const h = (graph.height - 1) * SCALE + PAD * 2
  const manyNodes = Object.keys(graph.nodes).length > 600
  const px = (x: number) => PAD + x * SCALE
  const py = (y: number) => PAD + y * SCALE
  const nodeXY = (n: number) => {
    const c = graph.nodes[String(n)]
    return [px(c[0]), py(c[1])] as const
  }

  // stable digests: frame arrays are fresh objects every tick, but their
  // contents change rarely — keep the Set/Map (and road layer) cached
  const closedKey = frame.closed.map(e => e.join('.')).join(',')
  const congKey = frame.congestion.map(e => e.join('.')).join(',')
  const closed = useMemo(
    () => new Set(frame.closed.map(([a, b]) => edgeKey(a, b))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [closedKey])
  const congestion = useMemo(() => {
    const m = new Map<string, number>()
    for (const [a, b, mult] of frame.congestion) m.set(edgeKey(a, b), mult)
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [congKey])

  const nodeOfLandmark = useMemo(() => {
    const m = new Map<number, string>()
    for (const [name, node] of Object.entries(graph.landmarks)) m.set(node, name)
    return m
  }, [graph.landmarks])

  const activeIncidents = frame.incidents.filter(
    i => i.node != null && i.status !== 'resolved')

  // cluster idle units around their station so they don't stack
  const idleOffsets = useMemo(() => {
    const byNode = new Map<string, number>()
    const out = new Map<string, [number, number]>()
    for (const u of frame.units) {
      if (u.status !== 'available' && u.status !== 'refueling') continue
      const k = `${u.x},${u.y}`
      const i = byNode.get(k) ?? 0
      byNode.set(k, i + 1)
      const ang = i * 2.399963
      const rad = (0.18 + 0.09 * (i % 4)) * SCALE
      out.set(u.id, [Math.cos(ang) * rad, Math.sin(ang) * rad])
    }
    return out
  }, [frame.units])

  // the road layer is thousands of lines on real maps: re-render it only
  // when closures/congestion actually change, not on every frame
  const roadLayer = useMemo(() => (
    <g>
      {graph.edges.map(([a, b]) => {
        const [x1, y1] = nodeXY(a)
        const [x2, y2] = nodeXY(b)
        const k = edgeKey(a, b)
        if (closed.has(k)) {
          return <line key={k} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="#f43f5e" strokeWidth={2.5} strokeDasharray="6 5" opacity={0.85} />
        }
        const mult = congestion.get(k)
        if (mult) {
          return <line key={k} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="#f59e0b" strokeWidth={1.5 + mult}
            opacity={Math.min(0.75, 0.25 + mult * 0.12)} />
        }
        return <line key={k} x1={x1} y1={y1} x2={x2} y2={y2}
          stroke="#1e293b" strokeWidth={manyNodes ? 1.2 : 2} />
      })}
      {!manyNodes && Object.entries(graph.nodes).map(([n, [x, y]]) => (
        <circle key={n} cx={px(x)} cy={py(y)} r={2.5} fill="#334155" />
      ))}
    </g>
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ), [graph, closed, congestion])

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
        {roadLayer}

        {/* stations */}
        {graph.stations.map(n => {
          const [x, y] = nodeXY(n)
          return (
            <g key={`st-${n}`}>
              <rect x={x - 8} y={y - 8} width={16} height={16} rx={3}
                fill="#0f172a" stroke="#64748b" strokeWidth={1.5} />
              <text x={x} y={y + 3.5} textAnchor="middle" fontSize={9}
                fill="#94a3b8" fontFamily="monospace">S</text>
            </g>
          )
        })}

        {/* incidents */}
        {activeIncidents.map(inc => {
          const [x, y] = nodeXY(inc.node!)
          const color = INCIDENT_COLORS[inc.type] ?? '#94a3b8'
          const r = 6 + inc.sev * 1.8
          return (
            <g key={inc.id}>
              {inc.status === 'pending' && (
                <circle className="incident-pulse" cx={x} cy={y} r={r}
                  fill={color} opacity={0.5} />
              )}
              <circle cx={x} cy={y} r={r} fill={color}
                opacity={inc.status === 'on_scene' ? 0.55 : 0.85}
                stroke={inc.status === 'on_scene' ? '#f8fafc' : '#0f172a'}
                strokeWidth={inc.status === 'on_scene' ? 2 : 1} />
              <text x={x} y={y - r - 5} fontSize={11}
                textAnchor={x < 100 ? 'start' : x > w - 100 ? 'end' : 'middle'}
                fill="#e2e8f0" fontWeight={600}>
                {inc.loc ?? nodeOfLandmark.get(inc.node!) ?? inc.id}
              </text>
              <title>{`${inc.id} · ${inc.type} · sev ${inc.sev} · ${inc.people} people · ${inc.status} · priority ${inc.pri}`}</title>
            </g>
          )
        })}

        {/* units */}
        {frame.units.map(u => {
          const off = idleOffsets.get(u.id)
          const x = px(u.x) + (off?.[0] ?? 0)
          const y = py(u.y) + (off?.[1] ?? 0)
          const color = UNIT_COLORS[u.type] ?? '#e2e8f0'
          const moving = u.status === 'en_route' || u.status === 'returning'
          const idle = u.status === 'available' || u.status === 'refueling'
          return (
            <g key={u.id}>
              <circle cx={x} cy={y} r={moving ? 5 : 3.5} fill={color}
                opacity={idle ? 0.45 : 1}
                stroke={u.status === 'en_route' ? '#0f172a' : 'none'}
                strokeWidth={1.2} />
              <title>{`${u.id} · ${UNIT_LABELS[u.type] ?? u.type} · ${u.status}${u.inc ? ` → ${u.inc}` : ''} · fuel ${(u.fuel * 100).toFixed(0)}%`}</title>
            </g>
          )
        })}
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs text-slate-500">
        {Object.entries(UNIT_COLORS).map(([t, c]) => (
          <span key={t} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {UNIT_LABELS[t]}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-rose-500" /> closed road
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-amber-500" /> congestion
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm border border-slate-500" /> station
        </span>
      </div>
    </div>
  )
}
