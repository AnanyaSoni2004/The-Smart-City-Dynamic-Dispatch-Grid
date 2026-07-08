export interface Graph {
  city?: string | null
  width: number
  height: number
  nodes: Record<string, [number, number]>
  edges: [number, number][]
  stations: number[]
  landmarks: Record<string, number>
}

export interface Metrics {
  calls: number
  incidents_created: number
  duplicates_merged: number
  false_quarantined: number
  dispatches: number
  preemptions: number
  resolved: number
  active: number
  backlog: number
  avg_response_min: number | null
  lives_saved_est: number
}

export interface IncidentView {
  id: string
  type: string
  loc: string | null
  node: number | null
  sev: number
  people: number
  status: string
  pri: number
  reports: number
  units: string[]
}

export interface UnitView {
  id: string
  type: string
  status: string
  x: number
  y: number
  fuel: number
  inc: string | null
}

export interface FeedEvent {
  t: number
  kind: 'created' | 'dispatch' | 'resolved'
  text: string
}

export interface Frame {
  t: number
  metrics: Metrics
  resources: Record<string, { available: number; dispatched: number; returning: number; out: number }>
  incidents: IncidentView[]
  units: UnitView[]
  closed: [number, number][]
  congestion: [number, number, number][]
  events: FeedEvent[]
}

export interface RunParams {
  duration: number
  incidents: number
  seed: number
  tick: number
  speed: number
  mode?: string
}

export interface CityInfo {
  key: string
  city: string
  country: string
  live: boolean
}

export interface RunMeta {
  id: string
  created_at: string
  status: 'running' | 'complete'
  params: RunParams
  summary: Record<string, unknown> | null
}

export interface RunDetail extends RunMeta {
  graph: Graph | null
  timeline: Frame[]
}
