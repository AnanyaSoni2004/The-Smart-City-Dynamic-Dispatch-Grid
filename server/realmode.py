"""Real-data mode: OpenStreetMap road graph + live Seattle Fire 911 calls.

The synthetic mode invents a city and 911 transcripts; this module swaps
both for reality. Roads come from scripts/build_city.py output (committed
JSON); incidents come from Seattle's open CAD feed (data.seattle.gov,
dataset kzjm-xkqj), replayed as structured TriageReports — real call
transcripts are never public, so triage-by-text is bypassed and the rest
of the swarm (dedup, quarantine, priority queue, dispatch, routing,
preemption) runs unchanged on real incidents at real locations.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dispatch_grid.dispatch import DispatchAgent
from dispatch_grid.models import IncidentType, TriageReport, Unit
from dispatch_grid.routing import CityGraph
from dispatch_grid.triage import TriageAgent

CITY_FILE = Path(__file__).resolve().parent / "data" / "seattle_city.json"
SOCRATA_URL = "https://data.seattle.gov/resource/kzjm-xkqj.json"


@lru_cache(maxsize=1)
def load_city() -> dict:
    return json.loads(CITY_FILE.read_text())


class RealCityGraph(CityGraph):
    """CityGraph over real OSM geometry (coords in km, top-left origin)."""

    def __init__(self, city: dict):
        # deliberately no super().__init__ — we load instead of generating
        self.coords = {int(n): (x, y) for n, (x, y) in city["nodes"].items()}
        self.adj = {int(n): {} for n in city["nodes"]}
        for a, b, secs in city["edges"]:
            self.adj[a][b] = secs
            self.adj[b][a] = secs
        self.congestion = {}
        self.closed = set()
        xs = [x for x, _ in self.coords.values()]
        ys = [y for _, y in self.coords.values()]
        self.width = max(xs) + 1
        self.height = max(ys) + 1

    def astar(self, src: int, dst: int, min_block: float = 30.0):
        # coords are km; fastest roads are 90 km/h = 40 s/km, so a
        # 30 s/km heuristic stays admissible
        return super().astar(src, dst, min_block)

    def reroute_if_blocked(self, current, dst, old_route):
        # real mode injects no closures/congestion: the remaining route is
        # always still valid, so skip the expensive per-tick re-route
        if not self.closed and not self.congestion:
            if old_route and current in old_route:
                remaining = old_route[old_route.index(current):]
                t = sum(self.adj[a].get(b, 0.0)
                        for a, b in zip(remaining, remaining[1:]))
                return remaining, t
            return self.route(current, dst)
        return super().reroute_if_blocked(current, dst, old_route)


class RegionalDispatchAgent(DispatchAgent):
    """Ranks candidate units by straight-line ETA estimate instead of exact
    routing — on an 8,000-node real graph, exact-routing every candidate
    for every incident is too slow, and the chosen unit's route is still
    computed exactly at dispatch time."""

    def _cost(self, u: Unit, dst: int) -> float:
        (x1, y1), (x2, y2) = self.graph.coords[u.node], self.graph.coords[dst]
        km = math.hypot(x1 - x2, y1 - y2)
        return km * 60.0 + (1.0 - u.fuel) * 120.0  # ~60 s/km city estimate


# ------------------- Seattle Fire 911 feed -------------------

# CAD call type -> (incident type, severity 1-5)
_TYPE_RULES: list[tuple[tuple[str, ...], IncidentType, int]] = [
    (("multiple casualty", "mci"), IncidentType.MEDICAL, 5),
    (("fire in building", "working fire", "fire in single family"), IncidentType.FIRE, 5),
    (("rescue heavy", "confined space", "building collapse", "rescue extrication"),
     IncidentType.COLLAPSE, 4),
    (("hazmat", "hazardous", "natural gas", "gas leak", "fuel spill"),
     IncidentType.HAZMAT, 4),
    (("water rescue", "rescue water", "flooding", "swimmer"), IncidentType.FLOOD, 3),
    (("mvi", "motor vehicle", "car vs", "bike struck"), IncidentType.ACCIDENT, 3),
    (("medic response", "medic"), IncidentType.MEDICAL, 3),
    (("car fire", "brush fire", "rubbish fire", "dumpster", "encampment fire",
      "chimney"), IncidentType.FIRE, 2),
    (("fire", "smoke", "alarm"), IncidentType.FIRE, 2),
    (("aid response", "aid", "triaged", "amr", "bls"), IncidentType.MEDICAL, 2),
]
_PEOPLE_BY_SEV = {1: 1, 2: 1, 3: 2, 4: 6, 5: 20}


def _classify(cad_type: str) -> tuple[IncidentType, int]:
    t = cad_type.lower()
    for keys, itype, sev in _TYPE_RULES:
        if any(k in t for k in keys):
            return itype, sev
    return IncidentType.UNKNOWN, 2


_cache: dict = {"at": 0.0, "records": None}
CACHE_SECONDS = 180


def fetch_recent_calls(limit: int = 400) -> list[dict]:
    """Latest CAD records, newest first. Cached briefly to be a good API
    citizen when several runs start close together."""
    now = time.time()
    if _cache["records"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["records"]
    qs = urllib.parse.urlencode({"$order": "datetime DESC", "$limit": str(limit)})
    req = urllib.request.Request(f"{SOCRATA_URL}?{qs}",
                                 headers={"User-Agent": "dispatch-grid"})
    with urllib.request.urlopen(req, timeout=20) as r:
        records = json.loads(r.read())
    _cache.update(at=now, records=records)
    return records


def _nearest_node(city: dict, lat: float, lon: float) -> Optional[int]:
    p = city["projection"]
    x = (lon - p["lon0"]) * p["klon"]
    y = (p["lat0"] - lat) * p["klat"]
    best, best_d = None, 4.0  # ignore calls >2 km from any mapped road
    for n, (nx, ny) in city["nodes"].items():
        d = (nx - x) ** 2 + (ny - y) ** 2
        if d < best_d:
            best, best_d = int(n), d
    return best


def build_reports(city: dict, duration: float, max_calls: int = 250) -> list[TriageReport]:
    """Turn the most recent real CAD records into TriageReports whose
    timestamps preserve real relative spacing, compressed into [0, duration]."""
    s, w, n, e = city["bbox"]
    rows = []
    for rec in fetch_recent_calls():
        try:
            lat, lon = float(rec["latitude"]), float(rec["longitude"])
            ts = datetime.fromisoformat(rec["datetime"]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        if not (s <= lat <= n and w <= lon <= e):
            continue
        rows.append((ts, rec, lat, lon))
    rows.sort(key=lambda r: r[0])
    rows = rows[-max_calls:]
    if not rows:
        return []
    t0, t1 = rows[0][0], rows[-1][0]
    span = max(t1 - t0, 1.0)
    reports = []
    for ts, rec, lat, lon in rows:
        node = _nearest_node(city, lat, lon)
        if node is None:
            continue
        itype, sev = _classify(rec.get("type", ""))
        people = _PEOPLE_BY_SEV[sev]
        reports.append(TriageReport(
            call_id=rec.get("incident_number") or f"CAD{int(ts)}",
            location=(rec.get("address") or "unknown address").title(),
            node=node,
            incident_type=itype,
            severity=sev,
            affected_people=people,
            resources_needed=TriageAgent._scale_resources(itype, sev, people),
            urgency=max(0.5, min(2.0, 1.0 + 0.15 * (sev - 3))),
            confidence=0.95,  # CAD-verified: never quarantined
            received_at=(ts - t0) / span * duration * 0.96,
        ))
    return reports
