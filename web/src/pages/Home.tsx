import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createRun, fetchCities, fetchRuns } from '../api'
import type { CityInfo, RunMeta } from '../types'
import Navbar from '../components/Navbar'

const FLAGS: Record<string, string> = { US: '🇺🇸', IN: '🇮🇳' }

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
  const [demoStarting, setDemoStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cities, setCities] = useState<CityInfo[]>([])
  const [cityKey, setCityKey] = useState('seattle')
  const [useReal, setUseReal] = useState(true)
  const [durationMin, setDurationMin] = useState(60)
  const [incidents, setIncidents] = useState(320)
  const [seed, setSeed] = useState(42)
  const [speed, setSpeed] = useState(120)

  useEffect(() => {
    fetchRuns().then(setRuns).catch(() => {})
    fetchCities().then(cs => {
      setCities(cs)
      if (cs.length && !cs.some(c => c.key === 'seattle')) setCityKey(cs[0].key)
    }).catch(() => {})
  }, [])

  const selectedCity = cities.find(c => c.key === cityKey)
  const mode = useReal ? cityKey : 'synthetic'
  const showScenarioKnobs = !useReal || !selectedCity?.live

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
        mode,
      })
      nav(`/runs/${id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStarting(false)
    }
  }

  async function watchDemo() {
    setDemoStarting(true)
    setError(null)
    try {
      // a live one-minute showcase: dense disaster, brisk pace
      const { id } = await createRun({
        duration: 1800, incidents: 150, seed: 42, speed: 60, tick: 10,
      })
      nav(`/runs/${id}`)
    } catch {
      // slots busy (or backend hiccup): fall back to the newest replay
      const done = runs.find(r => r.status === 'complete')
      if (done) nav(`/runs/${done.id}`)
      else {
        setError('No demo slot free right now — try again in a minute.')
        setDemoStarting(false)
      }
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
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <button onClick={watchDemo} disabled={demoStarting}
              className="rounded-lg bg-orange-600 px-7 py-2.5 font-semibold text-white shadow-lg shadow-orange-950/40 transition hover:bg-orange-500 disabled:opacity-50">
              {demoStarting ? 'Starting…' : '▶  Watch a live demo'}
            </button>
            <a href="#configure"
              className="rounded-lg border border-slate-700 px-6 py-2.5 font-semibold text-slate-300 transition hover:border-orange-500/60 hover:text-white">
              Configure your own
            </a>
          </div>
          {error && !starting && (
            <p className="mt-4 text-sm text-rose-400">{error}</p>
          )}
        </header>

        {/* scenario form */}
        <section id="configure"
          className="scroll-mt-20 rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl shadow-black/20">
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold text-white">Configure a disaster</h2>
            <span className="text-xs text-slate-500">runs server-side · shareable replay</span>
          </div>
          <div className="mb-6 grid gap-3 sm:grid-cols-2">
            <div onClick={() => setUseReal(true)}
              className={`cursor-pointer rounded-xl border p-4 text-left transition ${
                useReal
                  ? 'border-orange-500/70 bg-orange-500/10'
                  : 'border-slate-800 bg-slate-950/40 hover:border-slate-600'}`}>
              <div className="flex items-center gap-2 font-semibold text-white">
                Real city
                {selectedCity?.live ? (
                  <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold tracking-wide text-emerald-400">
                    LIVE 911 DATA
                  </span>
                ) : (
                  <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-bold tracking-wide text-sky-400">
                    REAL MAP
                  </span>
                )}
              </div>
              <select value={cityKey}
                onClick={e => e.stopPropagation()}
                onChange={e => { setCityKey(e.target.value); setUseReal(true) }}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm focus:border-orange-500 focus:outline-none">
                {cities.map(c => (
                  <option key={c.key} value={c.key}>
                    {FLAGS[c.country] ?? ''} {c.city}
                    {c.live ? ' — live 911 feed' : ' — real roads & landmarks'}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-xs leading-relaxed text-slate-400">
                {selectedCity?.live
                  ? 'Replays the latest real 911 calls on the real road network (OpenStreetMap + city open data), time-compressed into your window.'
                  : 'Real road network, fire stations and landmarks from OpenStreetMap; emergencies are simulated at real locations (no public 911 feed exists here).'}
              </p>
            </div>
            <button onClick={() => setUseReal(false)}
              className={`rounded-xl border p-4 text-left transition ${
                !useReal
                  ? 'border-orange-500/70 bg-orange-500/10'
                  : 'border-slate-800 bg-slate-950/40 hover:border-slate-600'}`}>
              <div className="font-semibold text-white">Synthetic disaster</div>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">
                1,000+ generated noisy 911 transcripts on a grid city — exercises
                the full text-triage pipeline with duplicates and false reports.
              </p>
            </button>
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
            {showScenarioKnobs && (
              <label className="block">
                <span className="text-sm text-slate-400">Ground-truth incidents</span>
                <div className="mt-1 flex items-center gap-3">
                  <input type="range" min={20} max={600} step={20} value={incidents}
                    onChange={e => setIncidents(Number(e.target.value))}
                    className="w-full accent-orange-500" />
                  <span className="w-16 text-right font-mono text-sm">{incidents}</span>
                </div>
              </label>
            )}
            {showScenarioKnobs && (
              <label className="block">
                <span className="text-sm text-slate-400">Random seed</span>
                <input type="number" value={seed} min={0}
                  onChange={e => setSeed(Number(e.target.value))}
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-sm focus:border-orange-500 focus:outline-none" />
              </label>
            )}
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
                    {r.params.mode && r.params.mode !== 'synthetic'
                      ? <>{r.params.mode[0].toUpperCase() + r.params.mode.slice(1)} · real city · {Math.round(r.params.duration / 60)} min</>
                      : <>{Math.round(r.params.duration / 60)} min · {r.params.incidents} incidents
                          · seed {r.params.seed}</>}
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
