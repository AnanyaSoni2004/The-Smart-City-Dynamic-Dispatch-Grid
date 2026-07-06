import { Link } from 'react-router-dom'

export function BeaconMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <circle cx="32" cy="38" r="9" fill="#f97316" />
      <path d="M14 22a24 24 0 0 1 36 0" stroke="#f97316" strokeWidth="5"
        strokeLinecap="round" fill="none" opacity="0.85" />
      <path d="M22 30a14 14 0 0 1 20 0" stroke="#fb923c" strokeWidth="5"
        strokeLinecap="round" fill="none" opacity="0.55" />
    </svg>
  )
}

export default function Navbar({ children }: { children?: React.ReactNode }) {
  return (
    <nav className="sticky top-0 z-20 border-b border-slate-800/60 bg-slate-950/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-3 px-5">
        <Link to="/" className="flex items-center gap-2.5">
          <BeaconMark />
          <span className="text-[15px] font-semibold tracking-tight text-white">
            Dispatch<span className="text-orange-400">Grid</span>
          </span>
        </Link>
        <span className="hidden text-xs text-slate-500 sm:block">
          multi-agent emergency dispatch simulator
        </span>
        <div className="ml-auto flex items-center gap-3">{children}</div>
      </div>
    </nav>
  )
}
