"""Triage evaluation harness.

Scores any extractor honoring the `extract(call) -> TriageReport` contract
against the generator's labeled ground truth, so rule-based and LLM triage
can be compared on identical input. Two evaluation levels:

1. Field-level extraction quality (per call):
   - incident type accuracy
   - location accuracy (correct landmark / correctly null)
   - severity MAE and within-1 rate
   - affected-people relative error (median)
   - false-report discrimination: does confidence separate hedged false
     reports from real ones? (reported as AUC + recall at the 0.42 gate)

2. System-level outcomes: run the *full* swarm simulation once per
   extractor on the same seed and compare dedup compression, average
   response time, dispatches and estimated lives saved. Extraction errors
   only matter insofar as they change dispatch outcomes; this measures that.

Usage:
    python -m dispatch_grid.evaluation                    # rule-based baseline
    ANTHROPIC_API_KEY=... python -m dispatch_grid.evaluation --llm --n 120
"""
from __future__ import annotations

import argparse
import json
import statistics

from .callgen import CallGenerator, GroundTruthIncident
from .models import EmergencyCall, TriageReport
from .triage import TriageAgent


# ---------------- field-level scoring ----------------
def _auc(pos: list[float], neg: list[float]) -> float | None:
    """Probability a random real call scores higher confidence than a
    random false report (Mann-Whitney AUC)."""
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def score_extraction(extractor, calls: list[EmergencyCall],
                     truth: dict[str, GroundTruthIncident]) -> dict:
    reports: list[TriageReport] = (
        extractor.extract_batch(calls) if hasattr(extractor, "extract_batch")
        else [extractor.extract(c) for c in calls])

    type_hits = loc_hits = n_real = 0
    sev_err: list[int] = []
    ppl_err: list[float] = []
    conf_real: list[float] = []
    conf_false: list[float] = []

    for call, rep in zip(calls, reports):
        if call.truth_is_false_report:
            conf_false.append(rep.confidence)
            continue
        gt = truth[call.truth_incident_key]
        n_real += 1
        conf_real.append(rep.confidence)
        type_hits += rep.incident_type == gt.itype
        # location: credit a correct landmark; also credit a correct null
        # when the caller genuinely gave no location
        if call.caller_location_hint is None:
            loc_hits += rep.location is None or rep.location == gt.landmark
        else:
            loc_hits += rep.location == gt.landmark
        sev_err.append(abs(rep.severity - gt.severity))
        if gt.people > 0:
            ppl_err.append(abs(rep.affected_people - gt.people) / gt.people)

    gate = 0.42
    return {
        "n_calls": len(calls), "n_real": n_real, "n_false": len(conf_false),
        "type_accuracy": round(type_hits / n_real, 3),
        "location_accuracy": round(loc_hits / n_real, 3),
        "severity_mae": round(statistics.mean(sev_err), 2),
        "severity_within_1": round(sum(e <= 1 for e in sev_err) / n_real, 3),
        "people_median_rel_err": round(statistics.median(ppl_err), 2) if ppl_err else None,
        "false_report_auc": round(_auc(conf_real, conf_false), 3) if conf_false else None,
        "false_caught_at_gate": (round(sum(c < gate for c in conf_false) / len(conf_false), 3)
                                 if conf_false else None),
        "real_lost_at_gate": round(sum(c < gate for c in conf_real) / n_real, 3),
    }


# ---------------- system-level scoring ----------------
def score_system(make_agent, seed: int = 42, n_incidents: int = 160,
                 duration: float = 2400.0) -> dict:
    """Run the full swarm with `make_agent()` supplying the triage swarm."""
    import random

    from .coordinator import EventBus, SwarmCoordinator
    from .dispatch import DispatchAgent
    from .models import UnitType
    from .routing import CityGraph

    graph = CityGraph(seed=7)
    fleet = {UnitType.AMBULANCE: 20, UnitType.FIRE_TRUCK: 12, UnitType.POLICE: 35,
             UnitType.HAZMAT_TEAM: 4, UnitType.RESCUE_BOAT: 5}
    bus = EventBus()
    dispatch = DispatchAgent(graph, fleet, [0, 11, 60, 71, 132, 143, 66, 27])
    coord = SwarmCoordinator([make_agent(i) for i in range(4)], dispatch, bus)
    gen = CallGenerator(n_incidents=n_incidents, duration=duration, seed=seed)
    calls = gen.generate()
    rng = random.Random(seed + 1)
    ci, t = 0, 0.0
    while t <= duration + 1500:
        while ci < len(calls) and calls[ci].received_at <= t:
            bus.publish("calls.incoming", {"call": calls[ci]}, t)
            ci += 1
        if rng.random() < 0.004:
            a = rng.choice(list(graph.coords))
            nbrs = list(graph.adj[a])
            if nbrs:
                graph.close_road(a, rng.choice(nbrs))
        coord.step(t)
        t += 10.0
    return coord.snapshot(t)


# ---------------- CLI ----------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Triage extractor evaluation")
    ap.add_argument("--llm", action="store_true", help="also evaluate LLMTriageAgent")
    ap.add_argument("--n", type=int, default=200, help="calls for field-level eval")
    ap.add_argument("--system", action="store_true", help="also run end-to-end sims")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    gen = CallGenerator(n_incidents=max(40, a.n // 4), duration=3600, seed=a.seed)
    calls = gen.generate()[:a.n]
    truth = {gt.key: gt for gt in gen.truth}

    results = {"rule_based": score_extraction(TriageAgent("eval-rules"), calls, truth)}
    if a.llm:
        from .llm_triage import LLMTriageAgent
        agent = LLMTriageAgent("eval-llm")
        results["llm"] = score_extraction(agent, calls, truth)
        results["llm"]["agent_stats"] = agent.stats
    if a.system:
        results["system_rule_based"] = score_system(
            lambda i: TriageAgent(f"t{i}"), seed=a.seed)
        if a.llm:
            from .llm_triage import LLMTriageAgent
            results["system_llm"] = score_system(
                lambda i: LLMTriageAgent(f"t{i}"), seed=a.seed)

    print(json.dumps(results, indent=2, default=str))
    with open("eval_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
