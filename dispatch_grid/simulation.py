"""Simulation driver.

Generates 1000+ calls, injects road closures / congestion / escalations,
runs the swarm in a discrete event loop and prints a live console
dashboard. Exports a timeline JSON consumed by the web dashboard.
"""
from __future__ import annotations

import json
import random

from .callgen import CallGenerator, LANDMARKS
from .coordinator import EventBus, SwarmCoordinator
from .dispatch import DispatchAgent
from .models import UnitType
from .routing import CityGraph
from .triage import TriageAgent


def build_system(seed: int = 7):
    graph = CityGraph(seed=seed)
    fleet = {
        UnitType.AMBULANCE: 20,
        UnitType.FIRE_TRUCK: 12,
        UnitType.POLICE: 35,
        UnitType.HAZMAT_TEAM: 4,
        UnitType.RESCUE_BOAT: 5,
    }
    stations = [0, 11, 60, 71, 132, 143, 66, 27]  # spread across regions
    bus = EventBus()
    triage_swarm = [TriageAgent(f"triage-{i}") for i in range(4)]
    dispatch = DispatchAgent(graph, fleet, stations)
    coord = SwarmCoordinator(triage_swarm, dispatch, bus)
    return graph, bus, coord


def run(duration: float = 3600.0, tick: float = 10.0, seed: int = 42,
        n_incidents: int = 320, verbose: bool = True):
    graph, bus, coord = build_system()
    gen = CallGenerator(n_incidents=n_incidents, duration=duration, seed=seed)
    calls = gen.generate()
    rng = random.Random(seed + 1)

    # schedule disruptions: closures and congestion waves
    disruptions = []
    nodes = list(graph.coords)
    for _ in range(14):
        a = rng.choice(nodes)
        nbrs = list(graph.adj[a])
        if nbrs:
            disruptions.append((rng.uniform(0, duration * 0.8), "close", a, rng.choice(nbrs)))
    for _ in range(30):
        a = rng.choice(nodes)
        nbrs = list(graph.adj[a])
        if nbrs:
            disruptions.append((rng.uniform(0, duration * 0.9), "congest",
                                a, rng.choice(nbrs)))
    disruptions.sort(key=lambda d: d[0])

    timeline = []
    ci = di = 0
    t = 0.0
    while t <= duration + 1800:  # drain period after last call
        while ci < len(calls) and calls[ci].received_at <= t:
            bus.publish("calls.incoming", {"call": calls[ci]}, t)
            ci += 1
        while di < len(disruptions) and disruptions[di][0] <= t:
            _, kind, a, b = disruptions[di]
            if kind == "close":
                graph.close_road(a, b)
            else:
                graph.set_congestion(a, b, rng.uniform(1.5, 3.5))
            di += 1
        coord.step(t)
        if int(t) % 300 == 0:
            snap = coord.snapshot(t)
            timeline.append(snap)
            if verbose:
                print(f"[t={int(t):5d}s] calls={snap['calls']:4d} "
                      f"incidents={snap['incidents_created']:3d} "
                      f"merged={snap['duplicates_merged']:4d} "
                      f"backlog={snap['backlog']:3d} "
                      f"dispatched={snap['dispatches']:3d} "
                      f"resolved={snap['resolved']:3d} "
                      f"avgRT={snap['avg_response_min']}min "
                      f"lives~{int(snap['lives_saved_est'])}")
        t += tick

    final = coord.snapshot(t)
    if verbose:
        print("\n=== FINAL REPORT " + "=" * 50)
        print(json.dumps(final, indent=2, default=str))
        # dedup quality vs ground truth
        truth_keys = {c.truth_incident_key for c in calls if c.truth_incident_key}
        print(f"\nGround-truth incidents: {len(truth_keys)} | "
              f"system created: {final['incidents_created']} | "
              f"compression: {final['calls']} calls -> "
              f"{final['incidents_created']} incidents")
        sample = coord.orders[0] if coord.orders else None
        if sample:
            print("\nSample dispatch order:")
            print(json.dumps({
                "incident_id": sample.incident_id,
                "assigned_resources": sample.assigned_resources,
                "eta": f"{sample.eta_minutes} minutes"}, indent=2))
    return coord, timeline


if __name__ == "__main__":
    coord, timeline = run()
    with open("/home/claude/dispatch_grid/timeline.json", "w") as f:
        json.dump(timeline, f, indent=1)
