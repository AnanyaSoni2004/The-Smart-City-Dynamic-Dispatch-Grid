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
  * Observability (optional): if `langfuse` is installed and LANGFUSE_PUBLIC_KEY
    / LANGFUSE_SECRET_KEY are set, every batch LLM call is traced as a Langfuse
    generation (prompt, completion, model, token usage, latency, errors). If the
    package or keys are absent it degrades to a no-op — tracing never breaks
    extraction, matching the fallback philosophy above.

Requires: ANTHROPIC_API_KEY in the environment. Uses stdlib urllib only.
Optional: pip install langfuse + LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
(and LANGFUSE_HOST for self-hosted) to enable tracing.
"""
from __future__ import annotations

import atexit
import json
import os
import time
import urllib.error
import urllib.request

from .callgen import LANDMARKS
from .models import EmergencyCall, IncidentType, TriageReport, UnitType
from .triage import TriageAgent

# Provider is pluggable: "anthropic" (default) or "gemini". Both implement the
# same batched-JSON contract; only the request shape and auth differ.
PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("TRIAGE_MODEL", "claude-sonnet-4-20250514")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

MODEL = GEMINI_MODEL if PROVIDER == "gemini" else ANTHROPIC_MODEL

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


# ---------------- optional Langfuse tracing ----------------
# Fully optional. _langfuse() returns a cached client only when the `langfuse`
# package is importable AND both keys are set; otherwise None, and every trace
# call site becomes a no-op so the extractor behaves exactly as before.
_LF_UNSET = object()
_lf_client = _LF_UNSET


def _langfuse():
    global _lf_client
    if _lf_client is _LF_UNSET:
        _lf_client = None
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import Langfuse
                client = Langfuse()            # reads LANGFUSE_* from the env
                atexit.register(client.flush)  # short-lived CLI runs must flush
                _lf_client = client
            except Exception:
                _lf_client = None              # never let tracing break triage
    return _lf_client


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
        key = self._api_key()
        if not key:
            return None
        user_content = json.dumps(
            [{"id": c.call_id, "transcript": c.transcript} for c in chunk])
        max_tokens = self._max_tokens(len(chunk))
        req = self._build_request(key, user_content, max_tokens)

        gen = self._start_trace(user_content, max_tokens, len(chunk))
        rows = usage = error = None
        for attempt in range(self.max_retries):
            try:
                self.stats["api_calls"] += 1
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read())
                rows, usage, error = self._parse_response(data, len(chunk))
                break                             # got a response: don't retry
            except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError) as e:
                error = f"{type(e).__name__}: {e}"
                time.sleep(1.5 * (attempt + 1))   # backoff on transient failures
        self._end_trace(gen, rows, usage, error)
        return rows

    @staticmethod
    def _api_key() -> str | None:
        if PROVIDER == "gemini":
            return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return os.environ.get("ANTHROPIC_API_KEY")

    @staticmethod
    def _max_tokens(n: int) -> int:
        # Gemini flash "thinks" before answering and thinking spends output
        # tokens, so give it generous headroom or the JSON gets truncated.
        return (1000 + 600 * n) if PROVIDER == "gemini" else 220 * n

    def _build_request(self, key, user_content, max_tokens):
        if PROVIDER == "gemini":
            body = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": user_content}]}],
                "generationConfig": {"maxOutputTokens": max_tokens,
                                     "responseMimeType": "application/json",
                                     "temperature": 0.0},
            }
            return urllib.request.Request(
                GEMINI_URL.format(model=GEMINI_MODEL), data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
        body = {
            "model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        }
        return urllib.request.Request(
            ANTHROPIC_URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"})

    def _parse_response(self, data: dict, n: int):
        """-> (rows|None, usage_dict|None, error|None). rows is None on any
        malformed/blocked response; usage is captured when present for tracing."""
        try:
            if PROVIDER == "gemini":
                cand = data.get("candidates") or []
                if not cand:
                    return None, None, f"no candidates: {data.get('promptFeedback') or data}"
                text = "".join(p.get("text", "")
                               for p in cand[0].get("content", {}).get("parts", []))
                um = data.get("usageMetadata") or {}
                usage = {"input": um.get("promptTokenCount", 0),
                         "output": um.get("candidatesTokenCount", 0)
                         + um.get("thoughtsTokenCount", 0)}
            else:
                text = "".join(b.get("text", "") for b in data.get("content", []))
                um = data.get("usage") or {}
                usage = {"input": um.get("input_tokens", 0),
                         "output": um.get("output_tokens", 0)}
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) == n:
                return parsed, usage, None
            got = len(parsed) if isinstance(parsed, list) else "non-list"
            return None, usage, f"row count mismatch: got {got}, want {n}"
        except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
            return None, None, f"parse error: {type(e).__name__}: {e}"

    def _start_trace(self, user_content, max_tokens, n):
        lf = _langfuse()
        if lf is None:
            return None
        try:
            return lf.start_observation(
                name="triage-extract", as_type="generation", model=MODEL,
                input={"system": SYSTEM_PROMPT, "user": user_content},
                model_parameters={"max_tokens": max_tokens, "provider": PROVIDER},
                metadata={"agent_id": self.agent_id, "batch_size": n})
        except Exception:
            return None

    def _end_trace(self, gen, rows, usage, error):
        if gen is None:
            return
        try:
            usage_details = None
            if usage:
                usage_details = {"input": usage.get("input_tokens", 0),
                                 "output": usage.get("output_tokens", 0)}
            gen.update(output=rows, usage_details=usage_details,
                       level="DEFAULT" if rows is not None else "ERROR",
                       status_message=error)
            gen.end()
        except Exception:
            pass                                  # tracing failures never propagate

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
