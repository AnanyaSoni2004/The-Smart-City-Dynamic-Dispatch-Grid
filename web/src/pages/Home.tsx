import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createRun, fetchRuns } from '../api'
import type { RunMeta } from '../types'
import Navbar from '../components/Navbar'

const PIPELINE = [
  {
    step: '01',
    title: 'Triage swarm',
    body: 'Stateless agents extract location, incident type, severity and urgency from noisy, panicked 911 transcripts — typos, hedging and all.',
  },
  {
    step: '02',
    title: 'Coordinate',
    body: 'A single-writer coordinator deduplicates hundreds of reports into incidents, quarantines suspected false reports, and keeps a global priority queue.',
  },
  {
    step: '03',
    title: 'Dispatch',
    body: 'Atomic multi-unit allocation over a live road graph: A* routing around closures, coverage reserves, and preemption when priorities demand it.',
  },
]

export default function Home() {
  const nav = useNavigate()
  const [runs, setRuns] = useState<RunMeta[]>([])
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [durationMin, setDurationMin] = useState(60)
  const [incidents, setIncidents] = useState(320)
  const [seed, setSeed] = useState(42)
  const [speed, setSpeed] = useState(120)

  useEffect(() => {
    fetchRuns().then(setRuns).catch(() => {})
  }, [])

  async function start() {
    setStarting(true)
    setError(null)
    try {
      const { id } = await createRun({
        duration: durationMin * 60,
        incidents,
        seed,
        speed,
        tick: 10,
      })
      nav(`/runs/${id}`)
    } catch (e) {
      setError(String(e))
      setStarting(false)
    }
  }

  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-5xl px-6">
        {/* hero */}
        <header className="pt-16 pb-12 text-center">
          <div className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/60 px-3.5 py-1 text-xs text-slate-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-orange-500" />
            Multi-agent AI swarm · real engine, streamed live
          </div>
          <h1 className="mx-auto max-w-3xl text-4xl font-bold tracking-tight text-white sm:text-5xl">
            1,000 emergency calls.
            <br />
            <span className="bg-gradient-to-r from-orange-400 to-amber-300 bg-clip-text text-transparent">
              76 units. One swarm.
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-[15px] leading-relaxed text-slate-400">
            Dispatch Grid simulates a city-wide disaster: a flood of noisy 911 call
            transcripts is triaged, deduplicated and prioritized by cooperating AI
            agents, which dispatch scarce emergency units across a live road network —
            re-routing around closures and preempting lower-priority missions as the
            crisis unfolds.
          </p>
        </header>

        {/* scenario form */}
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl shadow-black/20">
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold text-white">Configure a disaster</h2>
            <span className="text-xs text-slate-500">runs server-side · shareable replay</span>
          </div>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <label className="block">
              <span className="text-sm text-slate-400">Call stream duration</span>
              <div className="mt-1 flex items-center gap-3">
                <input type="range" min={5} max={120} step={5} value={durationMin}
                  onChange={e => setDurationMin(Number(e.target.value))}
                  className="w-full accent-orange-500" />
                <span className="w-16 text-right font-mono text-sm">{durationMin}m</span>
              </div>
            </label>
            <label className="block">
              <span className="text-sm text-slate-400">Ground-truth incidents</span>
              <div className="mt-1 flex items-center gap-3">
                <input type="range" min={20} max={600} step={20} value={incidents}
                  onChange={e => setIncidents(Number(e.target.value))}
                  className="w-full accent-orange-500" />
                <span className="w-16 text-right font-mono text-sm">{incidents}</span>
              </div>
            </label>
            <label className="block">
              <span className="text-sm text-slate-400">Random seed</span>
              <input type="number" value={seed} min={0}
                onChange={e => setSeed(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-sm focus:border-orange-500 focus:outline-none" />
            </label>
            <label className="block">
              <span className="text-sm text-slate-400">Simulation speed</span>
              <select value={speed} onChange={e => setSpeed(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm focus:border-orange-500 focus:outline-none">
                <option value={60}>60× — detailed</option>
                <option value={120}>120× — default</option>
                <option value={240}>240× — fast</option>
                <option value={600}>600× — blitz</option>
              </select>
            </label>
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-4">
            <button onClick={start} disabled={starting}
              className="rounded-lg bg-orange-600 px-7 py-2.5 font-semibold text-white shadow-lg shadow-orange-950/40 transition hover:bg-orange-500 disabled:opacity-50">
              {starting ? 'Starting…' : 'Launch simulation'}
            </button>
            <span className="text-sm text-slate-500">
              streams live for ~{Math.round((durationMin * 60 + 1800) / speed)}s, then
              becomes a permanent replay
            </span>
            {error && <span className="text-sm text-rose-400">{error}</span>}
          </div>
        </section>

        {/* pipeline explainer */}
        <section className="mt-14 grid gap-4 sm:grid-cols-3">
          {PIPELINE.map(p => (
            <div key={p.step}
              className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-5">
              <div className="font-mono text-xs text-orange-400">{p.step}</div>
              <h3 className="mt-1.5 font-semibold text-white">{p.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">{p.body}</p>
            </div>
          ))}
        </section>

        {/* recent runs */}
        <section className="mt-14 pb-6">
          <h2 className="mb-4 text-lg font-semibold text-white">Recent runs</h2>
          {runs.length === 0 ? (
            <p className="text-sm text-slate-500">
              No runs yet — launch one above. Every completed run gets a permanent
              shareable URL.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {runs.map(r => (
                <Link key={r.id} to={`/runs/${r.id}`}
                  className="group rounded-xl border border-slate-800 bg-slate-900/40 p-4 transition hover:border-orange-500/50 hover:bg-slate-900">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm text-orange-400">#{r.id}</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${
                      r.status === 'running'
                        ? 'bg-emerald-500/15 text-emerald-400'
                        : 'bg-slate-700/40 text-slate-400'}`}>
                      {r.status === 'running' ? '● live' : 'replay'}
                    </span>
                  </div>
                  <div className="mt-2 text-sm text-slate-400">
                    {Math.round(r.params.duration / 60)} min · {r.params.incidents} incidents
                    · seed {r.params.seed}
                  </div>
                  {r.summary != null && (
                    <div className="mt-1 text-xs text-slate-500">
                      {String(r.summary['calls'] ?? '–')} calls →{' '}
                      {String(r.summary['incidents_created'] ?? '–')} incidents ·{' '}
                      {String(r.summary['resolved'] ?? '–')} resolved
                    </div>
                  )}
                  <div className="mt-2 text-xs text-slate-600">
                    {new Date(r.created_at).toLocaleString()}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        <footer className="mt-6 border-t border-slate-800/60 py-8 text-center text-xs leading-relaxed text-slate-600">
          Python swarm engine · FastAPI + WebSocket streaming · React + Tailwind ·
          SQLite replay store
          <br />
          Event-driven architecture: pub/sub bus, single-writer conflict resolution,
          false-report quarantine, atomic allocation, A* with live closures.
        </footer>
      </div>
    </>
  )
}
