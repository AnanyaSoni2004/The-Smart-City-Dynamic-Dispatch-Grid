"""Agent 1 — Triage Agent.

1. Information extraction from unstructured, noisy transcripts.
2. Duplicate detection (semantic similarity + location + time + type).
3. Incident prioritization (Priority = Severity x LivesAtRisk x Urgency).

The extractor is a deterministic NLP pipeline (keyword lattices + fuzzy
location matching) so the simulation is reproducible and dependency-free.
In production this slot is filled by an LLM with the same TriageReport
output contract — the rest of the system is agnostic to which is used.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from .callgen import LANDMARKS
from .models import (EmergencyCall, Incident, IncidentStatus, IncidentType,
                     RESOURCE_PROFILE, TriageReport, UnitType)

TYPE_KEYWORDS = {
    IncidentType.FIRE:     ["fire", "fyre", "flames", "smoke", "burning", "burns"],
    IncidentType.MEDICAL:  ["collapsed", "heart attack", "breathing", "unconscious",
                            "injured", "injur", "hurt bad", "bleeding"],
    IncidentType.ACCIDENT: ["crash", "pileup", "collided", "accident", "flipped"],
    IncidentType.FLOOD:    ["flood", "water rising", "roofs", "floating"],
    IncidentType.COLLAPSE: ["collapsed", "rubble", "caved in", "wall came down",
                            "structure", "ceiling"],
    IncidentType.HAZMAT:   ["chemical", "gas smell", "toxic", "fumes", "leak", "spill"],
}
URGENCY_CUES = ["trapped", "traped", "screaming", "now", "hurry", "help",
                "cant get out", "not breathing", "kids", "children"]
HEDGE_CUES = ["not sure", "i think", "maybe", "my friend told me", "might be", "?"]
NUM_RE = re.compile(r"(\d+)\s*(?:people|ppl|persons|injured|affected)?")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


class TriageAgent:
    """Stateless extraction + a sliding-window incident memory for dedup."""

    def __init__(self, agent_id: str = "triage-1", dedup_window: float = 900.0,
                 dedup_threshold: float = 0.62):
        self.agent_id = agent_id
        self.window = dedup_window
        self.threshold = dedup_threshold
        # pre-compute alias table for fuzzy location matching
        self._alias_table: list[tuple[str, str, int]] = []
        for name, meta in LANDMARKS.items():
            self._alias_table.append((_norm(name), name, meta["node"]))
            for a in meta["aliases"]:
                self._alias_table.append((_norm(a), name, meta["node"]))

    # ------------------- 1. information extraction -------------------
    def extract(self, call: EmergencyCall) -> TriageReport:
        text = _norm(call.transcript)

        # incident type: keyword vote, collapse beats medical on tie-breaker words
        scores = {t: sum(1 for k in kws if k in text) for t, kws in TYPE_KEYWORDS.items()}
        if "rubble" in text or "caved in" in text:
            scores[IncidentType.COLLAPSE] += 2
        itype = max(scores, key=scores.get) if max(scores.values()) > 0 else IncidentType.UNKNOWN

        location, node, loc_score = self._match_location(text)

        # affected people: explicit number, else inferred from type/cues
        m = NUM_RE.search(text)
        people = int(m.group(1)) if m else {
            IncidentType.FIRE: 8, IncidentType.COLLAPSE: 15, IncidentType.FLOOD: 12,
            IncidentType.ACCIDENT: 3, IncidentType.MEDICAL: 1, IncidentType.HAZMAT: 6,
            IncidentType.UNKNOWN: 1}[itype]
        people = min(people, 500)

        urgency_hits = sum(1 for c in URGENCY_CUES if c in text)
        urgency = min(2.0, 1.0 + 0.25 * urgency_hits)
        hedges = sum(1 for c in HEDGE_CUES if c in text)

        base_sev = {IncidentType.FIRE: 4, IncidentType.COLLAPSE: 5, IncidentType.HAZMAT: 4,
                    IncidentType.FLOOD: 3, IncidentType.ACCIDENT: 3,
                    IncidentType.MEDICAL: 3, IncidentType.UNKNOWN: 2}[itype]
        severity = max(1, min(5, base_sev + (1 if urgency_hits >= 2 else 0)
                              + (1 if people > 20 else 0) - (1 if hedges >= 2 else 0)))

        confidence = max(0.05, min(1.0,
                         0.35 + 0.25 * (loc_score or 0) + 0.15 * min(2, max(scores.values()))
                         - 0.2 * hedges))

        needs = self._scale_resources(itype, severity, people)
        return TriageReport(call_id=call.call_id, location=location, node=node,
                            incident_type=itype, severity=severity,
                            affected_people=people, resources_needed=needs,
                            urgency=urgency, confidence=confidence,
                            received_at=call.received_at)

    def _match_location(self, text: str) -> tuple[Optional[str], Optional[int], float]:
        best: tuple[Optional[str], Optional[int], float] = (None, None, 0.0)
        for alias, canonical, node in self._alias_table:
            if alias in text:
                return canonical, node, 1.0
            r = SequenceMatcher(None, alias, text).find_longest_match(
                0, len(alias), 0, len(text))
            score = r.size / max(8, len(alias))
            if score > best[2] and score > 0.72:
                best = (canonical, node, score)
        return best

    @staticmethod
    def _scale_resources(itype: IncidentType, severity: int, people: int) -> dict[UnitType, int]:
        base = dict(RESOURCE_PROFILE[itype])
        scale = 1 + (severity - 3 > 0) + (people > 25)
        return {u: max(1, n * scale if severity >= 4 else n) for u, n in base.items()}

    # ------------------- 2. duplicate detection -------------------
    def similarity(self, rep: TriageReport, inc: Incident, now: float) -> float:
        s = 0.0
        # location match (strongest signal)
        if rep.node is not None and inc.node is not None:
            s += 0.45 if rep.node == inc.node else 0.0
        elif rep.node is None or inc.node is None:
            s += 0.15  # unknown location: weak benefit of the doubt
        # type match
        if rep.incident_type == inc.incident_type:
            s += 0.30
        elif {rep.incident_type, inc.incident_type} & {IncidentType.UNKNOWN}:
            s += 0.10
        # time proximity (decays over the window)
        dt = abs(rep.received_at - inc.last_reported)
        s += 0.25 * max(0.0, 1.0 - dt / self.window)
        return s

    def merge_or_create(self, rep: TriageReport, active: list[Incident],
                        now: float) -> tuple[Incident, bool]:
        """Returns (incident, created_new)."""
        best, best_s = None, 0.0
        for inc in active:
            if inc.status in (IncidentStatus.RESOLVED, IncidentStatus.FALSE_REPORT):
                continue
            sim = self.similarity(rep, inc, now)
            if sim > best_s:
                best, best_s = inc, sim
        if best is not None and best_s >= self.threshold:
            self._merge(best, rep)
            return best, False
        inc = Incident(incident_id=Incident.next_id(),
                       incident_type=rep.incident_type, location=rep.location,
                       node=rep.node, severity=rep.severity,
                       affected_people=rep.affected_people, urgency=rep.urgency,
                       resources_needed=dict(rep.resources_needed),
                       first_reported=rep.received_at, last_reported=rep.received_at,
                       confidence=rep.confidence)
        return inc, True

    @staticmethod
    def _merge(inc: Incident, rep: TriageReport) -> None:
        inc.report_count += 1
        inc.last_reported = max(inc.last_reported, rep.received_at)
        inc.severity = max(inc.severity, rep.severity)
        inc.urgency = max(inc.urgency, rep.urgency)
        # conflicting people counts: trust the corroborated median-ish blend
        inc.affected_people = int(0.6 * inc.affected_people + 0.4 * rep.affected_people)
        if inc.node is None and rep.node is not None:
            inc.node, inc.location = rep.node, rep.location
        for u, n in rep.resources_needed.items():
            inc.resources_needed[u] = max(inc.resources_needed.get(u, 0), n)
        # corroboration raises confidence
        inc.confidence = min(1.0, inc.confidence + 0.5 * rep.confidence * 0.4)
