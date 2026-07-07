import type { RunDetail, RunMeta, RunParams } from './types'

export async function createRun(params: Partial<RunParams>): Promise<{ id: string }> {
  const res = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    let msg = `failed to start run (${res.status})`
    try {
      const body = await res.json()
      if (body.detail) msg = String(body.detail)
    } catch { /* non-JSON error body */ }
    throw new Error(msg)
  }
  return res.json()
}

export async function fetchRuns(): Promise<RunMeta[]> {
  const res = await fetch('/api/runs')
  if (!res.ok) throw new Error('failed to list runs')
  return res.json()
}

export async function fetchRun(id: string): Promise<RunDetail> {
  const res = await fetch(`/api/runs/${id}`)
  if (res.status === 404) throw new Error('not_found')
  if (!res.ok) throw new Error('failed to load run')
  return res.json()
}

export function runSocketUrl(id: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/runs/${id}/ws`
}
