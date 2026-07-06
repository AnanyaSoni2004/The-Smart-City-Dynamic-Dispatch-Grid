import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchRun, runSocketUrl } from '../api'
import type { FeedEvent, Frame, Graph, RunParams } from '../types'
import CityMap from '../components/CityMap'
import EventLog from '../components/EventLog'
import IncidentFeed from '../components/IncidentFeed'
import MetricsBar from '../components/MetricsBar'
import Navbar from '../components/Navbar'
import PlaybackControls from '../components/PlaybackControls'
import ResourcePanel from '../components/ResourcePanel'
import Sparkline from '../components/Sparkline'

const BASE_FPS = 12

export default function RunPage() {
  const { id } = useParams<{ id: string }>()
  const [graph, setGraph] = useState<Graph | null>(null)
  const [params, setParams] = useState<RunParams | null>(null)
  const [frames, setFrames] = useState<Frame[]>([])
  const [cursor, setCursor] = useState(0)
  const [status, setStatus] = useState<'loading' | 'running' | 'complete' | 'not_found'>('loading')
  const [playing, setPlaying] = useState(true)
  const [following, setFollowing] = useState(true)
  const [replaySpeed, setReplaySpeed] = useState(1)
  const [copied, setCopied] = useState(false)
  const followingRef = useRef(true)
  followingRef.current = following

  // load run; open a websocket if it is still running
  useEffect(() => {
    if (!id) return
    let ws: WebSocket | null = null
    let cancelled = false
    setStatus('loading')
    setFrames([])
    setCursor(0)
    fetchRun(id).then(run => {
      if (cancelled) return
      setParams(run.params)
      if (run.graph) setGraph(run.graph)
      if (run.status === 'complete') {
        setFrames(run.timeline)
        setStatus('complete')
        setPlaying(true)
        return
      }
      setStatus('running')
      ws = new WebSocket(runSocketUrl(id))
      ws.onmessage = ev => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'init') {
          setGraph(msg.graph)
          setParams(msg.params)
        } else if (msg.type === 'frames') {
          setFrames(prev => {
            const next = [...prev, ...msg.frames]
            if (followingRef.current) setCursor(next.length - 1)
            return next
          })
        } else if (msg.type === 'frame') {
          setFrames(prev => {
            const next = [...prev, msg.frame]
            if (followingRef.current) setCursor(next.length - 1)
            return next
          })
        } else if (msg.type === 'done') {
          setStatus('complete')
        } else if (msg.type === 'error') {
          // run finished between fetch and connect: reload from the API
          fetchRun(id).then(r2 => {
            setFrames(r2.timeline)
            if (r2.graph) setGraph(r2.graph)
            setStatus('complete')
          }).catch(() => setStatus('not_found'))
        }
      }
    }).catch(e => {
      if (!cancelled) setStatus(String(e).includes('not_found') ? 'not_found' : 'loading')
    })
    return () => {
      cancelled = true
      ws?.close()
    }
  }, [id])

  // replay playback timer
  useEffect(() => {
    if (status !== 'complete' || !playing) return
    const iv = setInterval(() => {
      setCursor(c => {
        if (c >= frames.length - 1) {
          setPlaying(false)
          return c
        }
        return c + 1
      })
    }, 1000 / (BASE_FPS * replaySpeed))
    return () => clearInterval(iv)
  }, [status, playing, replaySpeed, frames.length])

  const frame = frames[Math.min(cursor, frames.length - 1)] ?? null

  const events: FeedEvent[] = useMemo(() => {
    const out: FeedEvent[] = []
    const end = Math.min(cursor, frames.length - 1)
    for (let i = 0; i <= end; i++) {
      if (frames[i].events.length) out.push(...frames[i].events)
    }
    return out.slice(-30).reverse()
  }, [frames, cursor])

  const backlogSeries = useMemo(
    () => frames.slice(0, cursor + 1).map(f => f.metrics.backlog),
    [frames, cursor])
  const responseSeries = useMemo(
    () => frames.slice(0, cursor + 1).map(f => f.metrics.avg_response_min),
    [frames, cursor])

  const onScrub = useCallback((i: number) => {
    setFollowing(false)
    setPlaying(false)
    setCursor(i)
  }, [])
  const onFollowLive = useCallback(() => {
    setFollowing(true)
    setCursor(c => Math.max(c, 0))
  }, [])

  if (status === 'not_found') {
    return (
      <>
        <Navbar />
        <div className="mx-auto max-w-xl px-6 py-24 text-center">
          <h1 className="text-2xl font-bold text-white">Run not found</h1>
          <p className="mt-2 text-slate-400">This run id doesn't exist (or the database was reset).</p>
          <Link to="/" className="mt-6 inline-block rounded-lg bg-orange-600 px-5 py-2 font-semibold text-white">
            Launch a new simulation
          </Link>
        </div>
      </>
    )
  }

  return (
    <>
    <Navbar>
      {status === 'complete' && frames.length > 0 && (
        <button
          onClick={() => {
            navigator.clipboard?.writeText(location.href)
            setCopied(true)
            setTimeout(() => setCopied(false), 1800)
          }}
          className={`rounded-lg border px-3 py-1.5 text-xs transition ${
            copied ? 'border-emerald-500/60 text-emerald-400'
                   : 'border-slate-700 text-slate-300 hover:border-orange-500/60'}`}>
          {copied ? '✓ Copied' : 'Copy share link'}
        </button>
      )}
    </Navbar>
    <div className="mx-auto max-w-[1500px] px-4 py-5">
      <header className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="font-mono text-lg font-semibold text-white">
          run <span className="text-orange-400">#{id}</span>
        </h1>
        {status === 'running' && (
          <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold text-emerald-400">
            <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            LIVE
          </span>
        )}
        {status === 'complete' && (
          <span className="rounded-full bg-slate-700/40 px-2.5 py-0.5 text-xs text-slate-400">
            replay
          </span>
        )}
        {params && (
          <div className="flex flex-wrap gap-1.5 text-xs">
            {[`${Math.round(params.duration / 60)} min`,
              `${params.incidents} incidents`,
              `seed ${params.seed}`].map(chip => (
              <span key={chip}
                className="rounded-full border border-slate-800 bg-slate-900/60 px-2.5 py-0.5 text-slate-400">
                {chip}
              </span>
            ))}
          </div>
        )}
      </header>

      {!frame || !graph ? (
        <div className="flex h-96 flex-col items-center justify-center gap-4 text-slate-500">
          <svg className="spinner h-8 w-8 text-orange-500" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
            <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
          {status === 'loading' ? 'Loading run…' : 'Spinning up the swarm…'}
        </div>
      ) : (
        <div className="space-y-3">
          <PlaybackControls
            cursor={cursor} total={frames.length}
            playing={playing} isLive={status === 'running'}
            following={following} simTime={frame.t} replaySpeed={replaySpeed}
            onPlayPause={() => {
              if (cursor >= frames.length - 1) setCursor(0)
              setPlaying(p => !p)
            }}
            onScrub={onScrub} onFollowLive={onFollowLive}
            onSpeed={setReplaySpeed}
          />
          <MetricsBar m={frame.metrics} />
          <div className="grid gap-3 lg:grid-cols-[1fr_340px]">
            <CityMap graph={graph} frame={frame} />
            <div className="space-y-3">
              <div className="grid grid-cols-1 gap-2">
                <Sparkline values={backlogSeries} color="#f59e0b" label="Backlog"
                  current={String(frame.metrics.backlog)} />
                <Sparkline values={responseSeries} color="#38bdf8" label="Avg response (min)"
                  current={frame.metrics.avg_response_min != null ? `${frame.metrics.avg_response_min}m` : '–'} />
              </div>
              <ResourcePanel resources={frame.resources} />
              <IncidentFeed incidents={frame.incidents} />
              <EventLog events={events} />
            </div>
          </div>
        </div>
      )}
    </div>
    </>
  )
}
