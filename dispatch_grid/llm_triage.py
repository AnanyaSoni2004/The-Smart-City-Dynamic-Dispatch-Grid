"""LLM-backed Triage Agent.

Drop-in replacement for the rule-based extractor in triage.py: it
implements the same `extract(call) -> TriageReport` contract, so the
coordinator, dedup, dispatch and metrics are untouched. Selection is a
constructor argument away:

    triage_swarm = [LLMTriageAgent(f"triage-{i}") for i in range(4)]

Design points:
  * Structured output: the model is prompted to emit strict JSON matching
    the TriageReport schema; the response is validated field-by-field and
    clamped to legal ranges before a report is built.
  * Graceful degradation: on API error, timeout, or malformed JSON the
    agent falls back to the deterministic rule-based extractor, so a
    network outage degrades extraction quality instead of halting dispatch.
  * Batching: extract_batch() packs many transcripts into one request,
    cutting cost/latency ~10x for stream processing.
  * Location grounding: the model maps free-text locations onto the city
    gazetteer (the only locations the router can act on); ungrounded
    locations come back null rather than hallucinated.

Requires: ANTHROPIC_API_KEY in the environment. Uses stdlib urllib only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .callgen import LANDMARKS
from .models import EmergencyCall, IncidentType, TriageReport, UnitType
from .triage import TriageAgent

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("TRIAGE_MODEL", "claude-sonnet-4-20250514")

_TYPES = [t.value for t in IncidentType if t != IncidentType.UNKNOWN]
_UNITS = [u.value for u in UnitType]

SYSTEM_PROMPT = f"""You are the triage extraction module of an emergency dispatch system
operating during a large-scale disaster. You receive raw 911 call transcripts that are
panicked, misspelled and incomplete. For EACH transcript, extract:

- location: the matching landmark from this exact gazetteer, or null if none clearly
  matches (never invent one): {json.dumps(list(LANDMARKS))}
- incident_type: one of {json.dumps(_TYPES)} or "Unknown"
- severity: integer 1-5 (5 = mass-casualty / structure-level threat)
- affected_people: best integer estimate (use stated numbers; else infer from type)
- urgency: float 1.0-2.0 from language cues (trapped, screaming, not breathing => high)
- confidence: float 0-1. Hedged secondhand reports ("not sure", "my friend told me")
  must score below 0.4. Clear firsthand reports with a grounded location score above 0.7.
- resources_needed: object mapping unit types {json.dumps(_UNITS)} to integer counts,
  scaled to severity.

Respond ONLY with a JSON array, one object per transcript, in input order, each with key
"id" echoing the transcript id plus the fields above. No markdown, no prose."""


class LLMTriageAgent(TriageAgent):
    """Inherits dedup/merge machinery from TriageAgent; overrides extraction."""

    def __init__(self, agent_id: str = "llm-triage-1", batch_size: int = 10,
                 max_retries: int = 3, **kw):
        super().__init__(agent_id=agent_id, **kw)
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._fallback = TriageAgent(agent_id + "-fallback")
        self.stats = {"llm_ok": 0, "fallbacks": 0, "api_calls": 0}

    # ---------------- public contract ----------------
    def extract(self, call: EmergencyCall) -> TriageReport:
        return self.extract_batch([call])[0]

    def extract_batch(self, calls: list[EmergencyCall]) -> list[TriageReport]:
        out: list[TriageReport] = []
        for i in range(0, len(calls), self.batch_size):
            chunk = calls[i:i + self.batch_size]
            rows = self._call_llm(chunk)
            if rows is None:
                out += [self._fallback.extract(c) for c in chunk]
                self.stats["fallbacks"] += len(chunk)
            else:
                for c, row in zip(chunk, rows):
                    rep = self._to_report(c, row)
                    if rep is None:
                        rep = self._fallback.extract(c)
                        self.stats["fallbacks"] += 1
                    else:
                        self.stats["llm_ok"] += 1
                    out.append(rep)
        return out

    # ---------------- API plumbing ----------------
    def _call_llm(self, chunk: list[EmergencyCall]):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        payload = {
            "model": MODEL, "max_tokens": 220 * len(chunk),
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(
                [{"id": c.call_id, "transcript": c.transcript} for c in chunk])}],
        }
        req = urllib.request.Request(
            API_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"})
        for attempt in range(self.max_retries):
            try:
                self.stats["api_calls"] += 1
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read())
                text = "".join(b.get("text", "") for b in data.get("content", []))
                text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
                rows = json.loads(text)
                if isinstance(rows, list) and len(rows) == len(chunk):
                    return rows
                return None
            except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
                time.sleep(1.5 * (attempt + 1))   # backoff on transient failures
        return None

    # ---------------- validation / clamping ----------------
    def _to_report(self, call: EmergencyCall, row: dict) -> TriageReport | None:
        try:
            loc = row.get("location")
            node = LANDMARKS[loc]["node"] if loc in LANDMARKS else None
            if loc is not None and node is None:
                loc = None                      # refuse hallucinated locations
            try:
                itype = IncidentType(row.get("incident_type", "Unknown"))
            except ValueError:
                itype = IncidentType.UNKNOWN
            needs: dict[UnitType, int] = {}
            for k, v in (row.get("resources_needed") or {}).items():
                try:
                    needs[UnitType(k)] = max(1, min(6, int(v)))
                except (ValueError, TypeError):
                    continue
            if not needs:
                needs = self._fallback._scale_resources(
                    itype, int(row.get("severity", 3)), int(row.get("affected_people", 1)))
            return TriageReport(
                call_id=call.call_id, location=loc, node=node, incident_type=itype,
                severity=max(1, min(5, int(row.get("severity", 3)))),
                affected_people=max(0, min(500, int(row.get("affected_people", 1)))),
                resources_needed=needs,
                urgency=max(0.5, min(2.0, float(row.get("urgency", 1.0)))),
                confidence=max(0.0, min(1.0, float(row.get("confidence", 0.5)))),
                received_at=call.received_at)
        except (TypeError, ValueError):
            return None
