"""Swarm Coordination Layer.

A central coordinator agent that owns the single source of truth:

  * receives TriageReports from N triage agents over an event bus
  * receives availability snapshots from N dispatch agents
  * maintains the global priority queue of incidents
  * resolves conflicts (two triage agents creating the same incident,
    two dispatch agents claiming the same unit) by being the only writer
  * gates low-confidence single reports (false-report suppression)

The event bus here is an in-process pub/sub; the topic names map 1:1 to
Kafka/NATS topics in the production design (see README).
"""
from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from typing import Callable

from .dispatch import DispatchAgent
from .models import (DispatchOrder, EmergencyCall, Incident, IncidentStatus,
                     TriageReport)
from .triage import TriageAgent

FALSE_REPORT_CONF = 0.42      # below this and uncorroborated => quarantine
QUARANTINE_TIME = 420.0       # seconds a low-confidence report waits for corroboration


class EventBus:
    """Minimal in-process pub/sub with topic-keyed subscribers."""

    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self.log: list[tuple[float, str, dict]] = []

    def subscribe(self, topic: str, fn: Callable) -> None:
        self._subs[topic].append(fn)

    def publish(self, topic: str, payload: dict, t: float) -> None:
        self.log.append((t, topic, payload))
        for fn in self._subs[topic]:
            fn(payload, t)


class SwarmCoordinator:
    def __init__(self, triage_agents: list[TriageAgent],
                 dispatch_agent: DispatchAgent, bus: EventBus):
        self.triage_agents = triage_agents
        self.dispatch = dispatch_agent
        self.bus = bus
        self.incidents: dict[str, Incident] = {}
        self.quarantine: list[tuple[float, TriageReport]] = []
        self.orders: list[DispatchOrder] = []
        self._rr = itertools.cycle(range(len(triage_agents)))
        self.metrics = {
            "calls": 0, "incidents_created": 0, "duplicates_merged": 0,
            "false_quarantined": 0, "dispatches": 0, "preemptions": 0,
            "resolved": 0, "response_times": [], "lives_saved_est": 0.0,
        }
        bus.subscribe("calls.incoming", self._on_call)
        bus.subscribe("triage.report", self._on_report)

    # ---------------- triage path ----------------
    def _on_call(self, payload: dict, t: float) -> None:
        call: EmergencyCall = payload["call"]
        self.metrics["calls"] += 1
        agent = self.triage_agents[next(self._rr)]   # shard across the swarm
        report = agent.extract(call)
        self.bus.publish("triage.report", {"report": report}, t)

    def _on_report(self, payload: dict, t: float) -> None:
        rep: TriageReport = payload["report"]
        # false-report gate: weak, hedged, uncorroborated reports wait
        if rep.confidence < FALSE_REPORT_CONF:
            if not self._corroborates_existing(rep, t):
                self.quarantine.append((t, rep))
                self.metrics["false_quarantined"] += 1
                return
        self._admit(rep, t)

    def _corroborates_existing(self, rep: TriageReport, t: float) -> bool:
        agent = self.triage_agents[0]
        return any(agent.similarity(rep, inc, t) >= agent.threshold
                   for inc in self.incidents.values()
                   if inc.status not in (IncidentStatus.RESOLVED,
                                         IncidentStatus.FALSE_REPORT))

    def _admit(self, rep: TriageReport, t: float) -> None:
        agent = self.triage_agents[0]   # dedup against the global store
        active = [i for i in self.incidents.values()]
        inc, created = agent.merge_or_create(rep, active, t)
        if created:
            self.incidents[inc.incident_id] = inc
            self.metrics["incidents_created"] += 1
            self.bus.publish("incident.created", {"incident_id": inc.incident_id}, t)
        else:
            self.metrics["duplicates_merged"] += 1
            # a merged report may escalate an already-dispatched incident
            self.bus.publish("incident.updated", {"incident_id": inc.incident_id}, t)

    # ---------------- dispatch path ----------------
    def pending_queue(self, now: float) -> list[Incident]:
        q = [i for i in self.incidents.values()
             if i.status == IncidentStatus.PENDING]
        heap = [(-i.priority(now), i.incident_id, i) for i in q]
        heapq.heapify(heap)
        out = []
        while heap:
            out.append(heapq.heappop(heap)[2])
        return out

    def step(self, now: float) -> None:
        # release quarantined reports that got corroborated or timed out
        still = []
        for t0, rep in self.quarantine:
            if self._corroborates_existing(rep, now):
                self._admit(rep, now)
            elif now - t0 > QUARANTINE_TIME:
                pass  # expired: treated as false report, dropped
            else:
                still.append((t0, rep))
        self.quarantine = still

        # drain the global priority queue
        for inc in self.pending_queue(now):
            order = self.dispatch.try_dispatch(inc, now, allow_preempt=True,
                                               incidents=self.incidents)
            if order is None:
                continue
            self.orders.append(order)
            self.metrics["dispatches"] += 1
            if order.preempted_from:
                self.metrics["preemptions"] += 1
            self.bus.publish("dispatch.order", {"order": order}, now)

        # advance unit world-state
        self.dispatch.tick(now, self.incidents,
                           on_arrival=lambda i: self._on_arrival(i, now),
                           on_resolution=lambda i: self._on_resolved(i, now))

    def _on_arrival(self, inc: Incident, now: float) -> None:
        rt = (inc.arrival_time or now) - inc.first_reported
        self.metrics["response_times"].append(rt)
        # lives-saved model: fraction of affected people saved decays with
        # response time; severity raises the stakes.
        frac = max(0.1, 1.0 - rt / 1800.0)
        self.metrics["lives_saved_est"] += inc.affected_people * frac * (inc.severity / 5.0)

    def _on_resolved(self, inc: Incident, now: float) -> None:
        self.metrics["resolved"] += 1
        self.bus.publish("incident.resolved", {"incident_id": inc.incident_id}, now)

    # ---------------- reporting ----------------
    def snapshot(self, now: float) -> dict:
        pend = self.pending_queue(now)
        rts = self.metrics["response_times"]
        return {
            "t": now,
            "active": sum(1 for i in self.incidents.values()
                          if i.status in (IncidentStatus.PENDING,
                                          IncidentStatus.DISPATCHED,
                                          IncidentStatus.ON_SCENE)),
            "backlog": len(pend),
            "top_priority": ([(i.incident_id, round(i.priority(now), 1),
                               i.incident_type.value, i.location) for i in pend[:5]]),
            "resources": {k.value: v for k, v in self.dispatch.availability().items()},
            "avg_response_min": round(sum(rts) / len(rts) / 60.0, 2) if rts else None,
            "lives_saved_est": round(self.metrics["lives_saved_est"], 0),
            **{k: v for k, v in self.metrics.items()
               if k not in ("response_times", "lives_saved_est")},
        }
