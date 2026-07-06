import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createRun, fetchRuns } from '../api'
import type { RunMeta } from '../types'

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
    <div className="mx-auto max-w-5xl px-6 py-12">
      <header className="mb-10">
        <div className="flex items-center gap-3">
          <span className="inline-block h-3 w-3 rounded-full bg-orange-500" />
          <h1 className="text-3xl font-bold tracking-tight text-white">Dispatch Grid</h1>
        </div>
        <p className="mt-3 max-w-2xl text-slate-400">
          A multi-agent AI swarm for disaster-time emergency dispatch. It ingests a
          high-volume stream of noisy 911 transcripts, triages and deduplicates them
          into incidents, prioritizes by lives at risk, and dispatches scarce units
          over a live city road graph — with dynamic re-routing and preemption.
          Configure a disaster below and watch the swarm work in real time.
        </p>
      </header>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
        <h2 className="text-lg font-semibold text-white">New disaster scenario</h2>
        <div className="mt-5 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
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
            <span className="text-sm text-slate-400">Playback speed</span>
            <select value={speed} onChange={e => setSpeed(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm focus:border-orange-500 focus:outline-none">
              <option value={60}>60× (slow)</option>
              <option value={120}>120× (default)</option>
              <option value={240}>240× (fast)</option>
              <option value={600}>600× (blitz)</option>
            </select>
          </label>
        </div>
        <div className="mt-6 flex items-center gap-4">
          <button onClick={start} disabled={starting}
            className="rounded-lg bg-orange-600 px-6 py-2.5 font-semibold text-white transition hover:bg-orange-500 disabled:opacity-50">
            {starting ? 'Starting…' : 'Launch simulation'}
          </button>
          <span className="text-sm text-slate-500">
            ~{Math.round((durationMin * 60 + 1800) / speed)}s of live streaming
          </span>
          {error && <span className="text-sm text-rose-400">{error}</span>}
        </div>
      </section>

      <section className="mt-10">
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
                className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 transition hover:border-orange-500/50 hover:bg-slate-900">
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

      <footer className="mt-14 border-t border-slate-800/60 pt-6 text-sm text-slate-500">
        Triage swarm · dedup &amp; merge · false-report quarantine · priority queue ·
        atomic allocation · A* routing with live closures · preemption — all running
        server-side in Python, streamed here over WebSocket.
      </footer>
    </div>
  )
}
