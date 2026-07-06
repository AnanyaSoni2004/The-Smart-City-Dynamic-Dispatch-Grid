export const INCIDENT_COLORS: Record<string, string> = {
  Fire: '#f97316',
  Medical: '#fb7185',
  Accident: '#facc15',
  Flood: '#38bdf8',
  'Building Collapse': '#c084fc',
  'Hazardous Material': '#a3e635',
  Unknown: '#94a3b8',
}

export const UNIT_COLORS: Record<string, string> = {
  Ambulance: '#f1f5f9',
  FireTruck: '#ef4444',
  PoliceUnit: '#3b82f6',
  HazmatTeam: '#a3e635',
  RescueBoat: '#22d3ee',
}

export const UNIT_LABELS: Record<string, string> = {
  Ambulance: 'Ambulance',
  FireTruck: 'Fire truck',
  PoliceUnit: 'Police',
  HazmatTeam: 'Hazmat',
  RescueBoat: 'Rescue boat',
}

export function fmtSimTime(t: number): string {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
