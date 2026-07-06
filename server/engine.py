"""Tick-stepping wrapper around the dispatch_grid simulation.

`simulation.run()` executes the whole event loop at once; the web server
needs to advance one tick at a time and emit a JSON frame per tick so it
can stream a run live. This mirrors run()'s setup exactly (same seeds,
same disruption schedule) and adds per-unit position interpolation so
the frontend can animate units between intersections.
"""
from __future__ import annotations

import random
from typing import Optional

from dispatch_grid.callgen import CallGenerator, LANDMARKS
from dispatch_grid.models import IncidentStatus, UnitStatus
from dispatch_grid.simulation import build_system

DRAIN_SECONDS = 1800.0  # keep ticking after the last call, like run()


class SimulationSession:
    def __init__(self, duration: float = 3600.0, tick: float = 10.0,
                 seed: int = 42, n_incidents: int = 320):
        self.duration = duration
        self.tick = tick
        self.seed = seed
        self.n_incidents = n_incidents

        self.graph, self.bus, self.coord = build_system()
        gen = CallGenerator(n_incidents=n_incidents, duration=duration, seed=seed)
        self.calls = gen.generate()
        rng = random.Random(seed + 1)

        self.disruptions: list[tuple[float, str, int, int]] = []
        nodes = list(self.graph.coords)
        for _ in range(14):
            a = rng.choice(nodes)
            nbrs = list(self.graph.adj[a])
            if nbrs:
                self.disruptions.append(
                    (rng.uniform(0, duration * 0.8), "close", a, rng.choice(nbrs)))
        for _ in range(30):
            a = rng.choice(nodes)
            nbrs = list(self.graph.adj[a])
            if nbrs:
                self.disruptions.append(
                    (rng.uniform(0, duration * 0.9), "congest", a, rng.choice(nbrs)))
        self.disruptions.sort(key=lambda d: d[0])
        self._congest_rng = rng

        self.t = 0.0
        self._ci = 0
        self._di = 0
        self._bus_cursor = 0
        # unit_id -> (depart_time, eta, from_node) for motion interpolation
        self._motion: dict[str, tuple[float, float, int]] = {}
        self._prev_status: dict[str, UnitStatus] = {}
        self.finished = False

    # ---------------- static payload (sent once) ----------------
    def static_payload(self) -> dict:
        edges = []
        seen = set()
        for a, nbrs in self.graph.adj.items():
            for b in nbrs:
                k = (a, b) if a < b else (b, a)
                if k not in seen:
                    seen.add(k)
                    edges.append([k[0], k[1]])
        stations = sorted({u.home_node for u in self.coord.dispatch.units.values()})
        return {
            "width": self.graph.width,
            "height": self.graph.height,
            "nodes": {str(n): [x, y] for n, (x, y) in self.graph.coords.items()},
            "edges": edges,
            "stations": stations,
            "landmarks": {name: d["node"] for name, d in LANDMARKS.items()},
        }

    # ---------------- stepping ----------------
    def step(self) -> Optional[dict]:
        """Advance one tick and return the frame, or None when finished."""
        if self.finished:
            return None
        t = self.t
        while self._ci < len(self.calls) and self.calls[self._ci].received_at <= t:
            self.bus.publish("calls.incoming", {"call": self.calls[self._ci]}, t)
            self._ci += 1
        while self._di < len(self.disruptions) and self.disruptions[self._di][0] <= t:
            _, kind, a, b = self.disruptions[self._di]
            if kind == "close":
                self.graph.close_road(a, b)
            else:
                self.graph.set_congestion(a, b, self._congest_rng.uniform(1.5, 3.5))
            self._di += 1
        self.coord.step(t)
        frame = self._frame(t)
        self.t += self.tick
        if self.t > self.duration + DRAIN_SECONDS:
            self.finished = True
        return frame

    # ---------------- frame construction ----------------
    def _unit_position(self, u, now: float) -> tuple[float, float]:
        coords = self.graph.coords
        prev = self._prev_status.get(u.unit_id)
        if u.status in (UnitStatus.EN_ROUTE, UnitStatus.RETURNING):
            m = self._motion.get(u.unit_id)
            # (re)arm motion when the unit just left, or eta changed (re-route)
            if m is None or prev != u.status:
                self._motion[u.unit_id] = (now, u.eta or now, u.node)
                m = self._motion[u.unit_id]
            depart, eta, from_node = m
            if u.eta is not None and u.eta != eta:
                m = (depart, u.eta, from_node)
                self._motion[u.unit_id] = m
                depart, eta, from_node = m
            span = max(eta - depart, 1e-6)
            frac = min(1.0, max(0.0, (now - depart) / span))
            if u.status == UnitStatus.EN_ROUTE and u.route and len(u.route) > 1:
                return self._along_route(u.route, frac)
            # returning units have no stored route: straight-line home
            dst = u.home_node if u.status == UnitStatus.RETURNING else u.node
            (x1, y1), (x2, y2) = coords[from_node], coords[dst]
            return (x1 + (x2 - x1) * frac, y1 + (y2 - y1) * frac)
        self._motion.pop(u.unit_id, None)
        return coords[u.node]

    def _along_route(self, route: list[int], frac: float) -> tuple[float, float]:
        pts = [self.graph.coords[n] for n in route]
        pos = frac * (len(pts) - 1)
        i = min(int(pos), len(pts) - 2)
        f = pos - i
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        return (x1 + (x2 - x1) * f, y1 + (y2 - y1) * f)

    def _events_since_last_frame(self, now: float) -> list[dict]:
        out = []
        log = self.bus.log
        while self._bus_cursor < len(log):
            t, topic, payload = log[self._bus_cursor]
            self._bus_cursor += 1
            if topic == "incident.created":
                inc = self.coord.incidents.get(payload["incident_id"])
                if inc:
                    out.append({"t": t, "kind": "created",
                                "text": f"{inc.incident_id} · {inc.incident_type.value}"
                                        f" at {inc.location or 'unknown location'}"
                                        f" (sev {inc.severity})"})
            elif topic == "dispatch.order":
                o = payload["order"]
                txt = (f"{o.incident_id} ← {len(o.assigned_resources)} unit(s),"
                       f" ETA {o.eta_minutes} min")
                if o.preempted_from:
                    txt += f" (preempted from {o.preempted_from})"
                out.append({"t": t, "kind": "dispatch", "text": txt})
            elif topic == "incident.resolved":
                out.append({"t": t, "kind": "resolved",
                            "text": f"{payload['incident_id']} resolved"})
        return out[-12:]

    def _frame(self, now: float) -> dict:
        snap = self.coord.snapshot(now)
        incidents = []
        for inc in self.coord.incidents.values():
            if inc.status == IncidentStatus.FALSE_REPORT:
                continue
            incidents.append({
                "id": inc.incident_id,
                "type": inc.incident_type.value,
                "loc": inc.location,
                "node": inc.node,
                "sev": inc.severity,
                "people": inc.affected_people,
                "status": inc.status.value,
                "pri": round(inc.priority(now), 1),
                "reports": inc.report_count,
                "units": list(inc.assigned_units),
            })
        units = []
        for u in self.coord.dispatch.units.values():
            x, y = self._unit_position(u, now)
            units.append({
                "id": u.unit_id, "type": u.unit_type.value,
                "status": u.status.value,
                "x": round(x, 3), "y": round(y, 3),
                "fuel": round(u.fuel, 2),
                "inc": u.assigned_incident,
            })
        for u in self.coord.dispatch.units.values():
            self._prev_status[u.unit_id] = u.status
        return {
            "t": now,
            "metrics": {
                "calls": snap["calls"],
                "incidents_created": snap["incidents_created"],
                "duplicates_merged": snap["duplicates_merged"],
                "false_quarantined": snap["false_quarantined"],
                "dispatches": snap["dispatches"],
                "preemptions": snap["preemptions"],
                "resolved": snap["resolved"],
                "active": snap["active"],
                "backlog": snap["backlog"],
                "avg_response_min": snap["avg_response_min"],
                "lives_saved_est": snap["lives_saved_est"],
            },
            "resources": snap["resources"],
            "incidents": incidents,
            "units": units,
            "closed": [list(e) for e in sorted(self.graph.closed)],
            "congestion": [[a, b, round(m, 2)] for (a, b), m
                           in sorted(self.graph.congestion.items()) if m > 1.0],
            "events": self._events_since_last_frame(now),
        }

    def summary(self) -> dict:
        snap = self.coord.snapshot(self.t)
        snap.pop("top_priority", None)
        snap.pop("resources", None)
        return snap
