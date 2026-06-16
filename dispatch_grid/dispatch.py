"""Agent 2 — Dispatch Agent.

Owns the live resource database, plans routes over the city graph, and
solves the allocation problem under the optimization rules:

  1. Highest-priority incidents first (with anti-starvation aging baked
     into Incident.priority).
  2. Allocate the minimum resources needed.
  3. Avoid regional starvation (coverage penalty keeps some units home).
  4. Preempt/reassign en-route units when a far more critical incident appears.
  5. Multi-resource incidents are atomic: dispatch only if every required
     unit type can be sourced, otherwise hold (partial fills waste units).
"""
from __future__ import annotations

import math
from typing import Optional

from .models import (DispatchOrder, Incident, IncidentStatus, Unit,
                     UnitStatus, UnitType)
from .routing import CityGraph

PREEMPT_RATIO = 2.2          # new priority must exceed old by this factor
COVERAGE_RESERVE = 0.12      # keep ~12% of each fleet for fresh incidents
SCENE_TIME = {1: 300, 2: 480, 3: 720, 4: 1080, 5: 1500}  # seconds on scene


class DispatchAgent:
    def __init__(self, graph: CityGraph, fleet: dict[UnitType, int],
                 station_nodes: list[int], agent_id: str = "dispatch-1"):
        self.agent_id = agent_id
        self.graph = graph
        self.units: dict[str, Unit] = {}
        counters: dict[UnitType, int] = {}
        i = 0
        for utype, n in fleet.items():
            for _ in range(n):
                counters[utype] = counters.get(utype, 0) + 1
                home = station_nodes[i % len(station_nodes)]
                uid = f"{utype.value}_{counters[utype]}"
                self.units[uid] = Unit(unit_id=uid, unit_type=utype,
                                       home_node=home, node=home)
                i += 1

    # ------------------- resource views -------------------
    def availability(self) -> dict[UnitType, dict[str, int]]:
        out: dict[UnitType, dict[str, int]] = {}
        for u in self.units.values():
            d = out.setdefault(u.unit_type, {"available": 0, "dispatched": 0,
                                             "returning": 0, "out": 0})
            if u.dispatchable:
                d["available"] += 1
            elif u.status in (UnitStatus.EN_ROUTE, UnitStatus.ON_SCENE):
                d["dispatched"] += 1
            elif u.status == UnitStatus.RETURNING:
                d["returning"] += 1
            else:
                d["out"] += 1
        return out

    def _pool(self, utype: UnitType) -> list[Unit]:
        return [u for u in self.units.values()
                if u.unit_type == utype and u.dispatchable]

    def _fleet_size(self, utype: UnitType) -> int:
        return sum(1 for u in self.units.values() if u.unit_type == utype)

    # ------------------- allocation -------------------
    def try_dispatch(self, inc: Incident, now: float,
                     allow_preempt: bool = True,
                     incidents: Optional[dict[str, Incident]] = None
                     ) -> Optional[DispatchOrder]:
        if inc.node is None:
            return None  # cannot route without a location; coordinator holds it
        chosen: list[tuple[Unit, list[int], float]] = []
        preempted_from = None

        for utype, need in inc.resources_needed.items():
            pool = self._pool(utype)
            reserve = math.ceil(self._fleet_size(utype) * COVERAGE_RESERVE)
            usable = max(0, len(pool) - reserve)
            # rule 2: minimum allocation = exactly `need`
            if usable < need and allow_preempt and incidents is not None:
                pool += self._preemptable(utype, inc, now, incidents)
            ranked = sorted(pool, key=lambda u: self._cost(u, inc.node))
            picks = ranked[:need]
            if len(picks) < need:
                return None  # rule 5: atomic multi-resource dispatch
            for u in picks:
                path, t = self.graph.route(u.node, inc.node)
                if path is None:
                    return None  # unreachable (road closures); hold
                chosen.append((u, path, t))
                if u.assigned_incident and u.assigned_incident != inc.incident_id:
                    preempted_from = u.assigned_incident

        # commit
        routes, worst_eta = {}, 0.0
        for u, path, t in chosen:
            if u.assigned_incident and incidents and u.assigned_incident in incidents:
                old = incidents[u.assigned_incident]
                if u.unit_id in old.assigned_units:
                    old.assigned_units.remove(u.unit_id)
                if not old.assigned_units and old.status == IncidentStatus.DISPATCHED:
                    old.status = IncidentStatus.PENDING
                    old.dispatch_time = None
            u.status = UnitStatus.EN_ROUTE
            u.assigned_incident = inc.incident_id
            u.route = path
            u.eta = now + t
            routes[u.unit_id] = path
            worst_eta = max(worst_eta, t)
            inc.assigned_units.append(u.unit_id)

        inc.status = IncidentStatus.DISPATCHED
        inc.dispatch_time = now
        return DispatchOrder(incident_id=inc.incident_id,
                             assigned_resources=[u.unit_id for u, _, _ in chosen],
                             eta_minutes=round(worst_eta / 60.0, 1),
                             routes=routes, issued_at=now,
                             preempted_from=preempted_from)

    def _cost(self, u: Unit, dst: int) -> float:
        _, t = self.graph.route(u.node, dst)
        fuel_penalty = (1.0 - u.fuel) * 120.0
        return t + fuel_penalty

    def _preemptable(self, utype: UnitType, new_inc: Incident, now: float,
                     incidents: dict[str, Incident]) -> list[Unit]:
        """Rule 4: en-route units serving a far less critical incident."""
        out = []
        p_new = new_inc.priority(now)
        for u in self.units.values():
            if u.unit_type != utype or u.status != UnitStatus.EN_ROUTE:
                continue
            old = incidents.get(u.assigned_incident or "")
            if old and p_new > PREEMPT_RATIO * old.priority(now):
                out.append(u)
        return out

    # ------------------- world tick -------------------
    def tick(self, now: float, incidents: dict[str, Incident],
             on_arrival, on_resolution) -> None:
        for u in self.units.values():
            if u.status == UnitStatus.EN_ROUTE and u.eta is not None:
                # dynamic re-routing check against new closures/congestion
                inc = incidents.get(u.assigned_incident or "")
                if inc and inc.node is not None and u.route:
                    new_route, t_rem = self.graph.reroute_if_blocked(
                        u.route[0], inc.node, u.route)
                    if new_route != u.route and new_route is not None:
                        u.route, u.eta = new_route, now + t_rem
                if now >= u.eta:
                    u.status = UnitStatus.ON_SCENE
                    u.node = inc.node if inc else u.node
                    u.fuel = max(0.0, u.fuel - 0.12)
                    if inc and inc.status == IncidentStatus.DISPATCHED:
                        inc.status = IncidentStatus.ON_SCENE
                        inc.arrival_time = now
                        u.return_eta = now + SCENE_TIME[inc.severity]
                        on_arrival(inc)
                    else:
                        u.return_eta = now + 300
            elif u.status == UnitStatus.ON_SCENE and u.return_eta and now >= u.return_eta:
                inc = incidents.get(u.assigned_incident or "")
                if inc and inc.status == IncidentStatus.ON_SCENE:
                    inc.status = IncidentStatus.RESOLVED
                    inc.resolve_time = now
                    on_resolution(inc)
                u.assigned_incident = None
                path, t = self.graph.route(u.node, u.home_node)
                u.status = UnitStatus.RETURNING
                u.eta = now + (t if path else 600)
            elif u.status == UnitStatus.RETURNING and u.eta and now >= u.eta:
                u.node = u.home_node
                if u.fuel < 0.3:
                    u.status = UnitStatus.REFUELING
                    u.eta = now + 600
                else:
                    u.status = UnitStatus.AVAILABLE
                    u.eta = None
            elif u.status == UnitStatus.REFUELING and u.eta and now >= u.eta:
                u.fuel = 1.0
                u.status = UnitStatus.AVAILABLE
                u.eta = None
