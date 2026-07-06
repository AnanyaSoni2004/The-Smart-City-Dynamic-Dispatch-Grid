import { fmtSimTime } from '../theme'

export default function PlaybackControls({
  cursor, total, playing, isLive, following, simTime, replaySpeed,
  onPlayPause, onScrub, onFollowLive, onSpeed,
}: {
  cursor: number
  total: number
  playing: boolean
  isLive: boolean
  following: boolean
  simTime: number
  replaySpeed: number
  onPlayPause: () => void
  onScrub: (i: number) => void
  onFollowLive: () => void
  onSpeed: (s: number) => void
}) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/50 px-4 py-2.5">
      {isLive ? (
        <button onClick={onFollowLive}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-1 text-sm font-semibold ${
            following ? 'bg-emerald-500/15 text-emerald-400'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>
          <span className={`inline-block h-2 w-2 rounded-full bg-emerald-400 ${following ? 'live-dot' : ''}`} />
          {following ? 'LIVE' : 'Go live'}
        </button>
      ) : (
        <button onClick={onPlayPause}
          className="rounded-lg bg-orange-600 px-4 py-1 text-sm font-semibold text-white hover:bg-orange-500">
          {playing ? '❚❚' : '▶'}
        </button>
      )}
      <span className="w-14 shrink-0 font-mono text-sm text-slate-400">
        {fmtSimTime(simTime)}
      </span>
      <input type="range" min={0} max={Math.max(0, total - 1)} value={cursor}
        onChange={e => onScrub(Number(e.target.value))}
        className="w-full accent-orange-500" />
      <span className="shrink-0 font-mono text-xs text-slate-500">
        {cursor + 1}/{total}
      </span>
      {!isLive && (
        <select value={replaySpeed} onChange={e => onSpeed(Number(e.target.value))}
          className="shrink-0 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs">
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
          <option value={2}>2×</option>
          <option value={4}>4×</option>
        </select>
      )}
    </div>
  )
}
