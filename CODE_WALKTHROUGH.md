# Code Walkthrough — Smart City Dynamic Dispatch Grid

This report explains how the codebase is organized, what each module does, how data flows through the system at runtime, and why the key algorithms are written the way they are. It is meant to be read top-to-bottom alongside the source.

---

## 1. The project at a glance

```
dispatch_grid/
├── README.md                  architecture, schemas, scalability discussion
├── dashboard.html             self-contained live web dashboard (JS port of the swarm)
├── timeline.json              exported metrics timeline from the last Python run
└── dispatch_grid/             the Python package (~1,100 lines, zero dependencies)
    ├── models.py              every dataclass and enum — the system's vocabulary
    ├── callgen.py             synthetic 911 call stream generator + landmark gazetteer
    ├── triage.py              Agent 1: extraction, dedup, merging
    ├── routing.py             city graph, Dijkstra, A*, dynamic re-routing
    ├── dispatch.py            Agent 2: resource DB, allocation, preemption, unit lifecycle
    ├── coordinator.py         swarm layer: event bus, global queue, quarantine, metrics
    ├── simulation.py          event loop, disruption injection, console output
    └── main.py                CLI entry point
```

The architecture follows one organizing idea: **every module owns exactly one kind of state, and modules talk only through typed messages defined in `models.py`**. Triage agents own nothing (they are stateless functions). The dispatch agent owns units. The coordinator owns incidents. The graph owns roads. Because no two components write to the same state, there are no locks, no race conditions, and no conflicting writes anywhere in the system — conflict resolution is achieved by construction rather than by arbitration.

A second idea runs alongside it: **ground truth is quarantined from the agents**. The call generator knows which calls describe the same real event (`truth_incident_key`) and which are false reports, but those fields are only ever read by the scoring code at the end of a run. The agents must work from the noisy transcripts alone, exactly as a production system would. This is what makes the simulation an honest test rather than a demo that grades its own homework.

## 2. `models.py` — the vocabulary

Everything else imports from this file and it imports from nothing (except the standard library), which keeps the dependency graph a clean tree. It defines five enums (`IncidentType`, `IncidentStatus`, `UnitType`, `UnitStatus`, plus the implicit topic names) and five dataclasses that correspond exactly to the messages in the architecture diagram:

`EmergencyCall` is the raw input: a transcript, a timestamp, and the hidden ground-truth fields described above. `TriageReport` is the structured output of Agent 1 for a single call — location, resolved graph node, type, severity 1–5, affected people, required resources, an `urgency` multiplier derived from language cues, and a `confidence` score that drives false-report handling downstream. `Incident` is the merged, deduplicated record the coordinator keeps; several reports collapse into one of these. `Unit` is a row in the dispatch agent's resource database, carrying position, fuel, status, and its current route. `DispatchOrder` is the final product: which units go where, with what ETA.

The most consequential code in the file is `Incident.priority()`:

```python
def priority(self, now):
    lives_factor  = 1.0 + sqrt(max(1, self.affected_people))
    aging         = 1.0 + min(1.0, (now - self.first_reported) / 600.0)
    corroboration = min(1.5, 0.8 + 0.1 * self.report_count)
    return self.severity * lives_factor * self.urgency * aging * corroboration
```

This is the brief's `Priority = Severity × Lives At Risk × Urgency` formula with two engineering corrections. The square root on lives gives diminishing returns, so an incident with 100 people doesn't drown out everything else by a factor of 100. The `aging` term doubles an incident's priority after ten minutes of waiting, which is the anti-starvation mechanism: a severity-2 incident cannot be postponed forever just because severity-4 incidents keep arriving. `corroboration` rewards incidents reported by many independent callers, which both reflects real urgency and further suppresses false reports (which by definition arrive alone). Putting this formula on the model rather than in the coordinator means every component — queueing, preemption, the dashboard — computes priority identically.

Note that `priority()` takes `now` as a parameter rather than caching a value. Priorities drift continuously as incidents age, so the queue is re-sorted on every scheduling pass rather than maintained incrementally.

## 3. `callgen.py` — manufacturing a believable disaster

The generator's job is to produce input that is hard in the same ways real disaster traffic is hard. It works in two layers. First it creates a few hundred `GroundTruthIncident` objects — a type, a landmark, a severity, a casualty count, and a start time drawn from a Beta(2,2) distribution so the call volume swells toward the middle of the run (the "escalating disaster" requirement). Then each ground-truth event emits between 1 and 9 calls, and each call is independently corrupted.

The corruption pipeline is where the realism lives. `_transcript()` assembles a panic prefix ("Oh my god,", "HELP!!"), a type phrase ("flames everywhere"), a location reference that is randomly either the canonical landmark name or one of its colloquial aliases ("shopping center downtown" for Central Mall), an optional urgency fragment ("kids are inside!"), and — for conflicting-information realism — a casualty estimate multiplied by a random factor between 0.4× and 1.8× of the truth, so two callers at the same fire disagree about how many people are trapped. About 4% of calls also append a second, unrelated incident sighting (the multi-incident-call requirement), 12% omit the location entirely, and `_noisify()` then injects misspellings from a typo table ("fyre", "ppl", "traped") and randomly drops 4% of words. Finally, 7% of the total stream is pure false reports, recognizable to a careful reader by their hedged phrasing ("not sure, my friend told me") — phrasing the triage agent is specifically trained to detect.

The `LANDMARKS` gazetteer at the top of the file doubles as the system's geocoder: each landmark maps to a node in the city graph plus its aliases, and `triage.py` imports this same table to resolve locations. There are 25 landmarks, a number chosen deliberately — with too few, distinct real incidents at the same place and time become genuinely indistinguishable and the dedup compression looks worse than it is.

## 4. `routing.py` — the city as a weighted graph

`CityGraph` builds a 12×12 grid of intersections (nodes) connected by roads (edges) whose base weight is travel time in seconds, randomized ±40% per block so routes are asymmetric and interesting, plus a handful of diagonal "arterial" shortcuts. Live conditions are layered on top of the static graph rather than mutating it: `closed` is a set of edge keys, and `congestion` is a dictionary of multipliers. The single accessor `edge_time(a, b)` composes all three — it returns `None` for a closed road and `base × multiplier` otherwise — so every algorithm in the file automatically respects current conditions without knowing they exist.

Both required shortest-path algorithms are implemented. `dijkstra()` is the textbook heap-based version and serves as the always-correct fallback. `astar()` is the default router; its heuristic is the straight-line distance times the *minimum possible* block time, which keeps it admissible (it never overestimates), so A* returns genuinely optimal paths while expanding far fewer nodes than Dijkstra.

The most interesting function is `reroute_if_blocked()`, which implements dynamic re-routing for units already in motion. It walks the *remaining* portion of the unit's current route, summing live edge times. If any remaining edge has closed, re-routing is mandatory. Otherwise it computes a fresh route from the unit's current position and switches only if the new route is more than 40% faster — that hysteresis threshold prevents units from oscillating between two near-equal routes every time a congestion multiplier flickers.

## 5. `triage.py` — Agent 1

The agent has three responsibilities and the file is organized in that order: extraction, duplicate detection, merging.

**Extraction** (`extract()`) is a deterministic NLP pipeline rather than an LLM, a deliberate choice flagged in the module docstring: it makes the simulation reproducible and dependency-free, and because the agent's only contract with the rest of the system is the `TriageReport` schema, swapping in an LLM extractor later changes nothing downstream. The pipeline runs five passes over the normalized transcript. Incident type is a keyword vote across per-type keyword lists, with a tie-breaker nudging ambiguous "collapsed" toward Building Collapse when rubble-related words appear. Location uses the gazetteer two ways: exact substring match on any alias first, then `difflib.SequenceMatcher` longest-common-substring scoring as a fuzzy fallback, which is what catches the misspellings ("central shoping mall" still resolves). Casualty count takes an explicit number if the caller gave one, otherwise falls back to a per-type prior. Urgency counts cue words ("trapped", "screaming", "not breathing") and maps them to a 1.0–2.0 multiplier. Finally, **confidence** is assembled from the strength of all the other signals minus a penalty for hedge phrases ("i think", "maybe", "my friend told me") — and this one number is what later separates false reports from real ones.

**Duplicate detection** (`similarity()`) scores a new report against an existing incident as a weighted sum: 0.45 for an exact graph-node match, 0.30 for matching incident type, and up to 0.25 for time proximity, decaying linearly across a 15-minute window. Reports with unknown locations get a small benefit-of-the-doubt term instead of the location weight, so a location-less call can still merge into a corroborated incident. A score above 0.62 merges; below it creates a new incident. The weights encode a judgment call: location agreement is worth more than type agreement because callers misclassify emergencies ("smoke" could be fire or hazmat) far more often than they misplace them.

**Merging** (`_merge()`) defines what happens when callers conflict. Severity and urgency take the maximum (the system errs toward the scarier report), but the casualty count blends 60/40 toward the existing corroborated estimate rather than jumping to each new caller's number — a crude Bayesian update that damps the wild 0.4×–1.8× estimates the generator produces. A missing location fills in from the new report, resource requirements take the element-wise max, and confidence rises with each corroborating report, which is the mechanism that eventually releases quarantined calls.

## 6. `dispatch.py` — Agent 2

This module owns the only mutable fleet state in the system and is structured around two entry points the coordinator calls: `try_dispatch()` (the allocation solver) and `tick()` (the world-state advancer).

`try_dispatch()` implements the five optimization rules from the brief, and the order of operations matters. For each unit type the incident needs, it builds the pool of dispatchable units, then subtracts a **coverage reserve** — `ceil(12% of the fleet)` is held back from any assignment so a fresh emergency in another part of the city never finds the cupboard completely bare (rule 3). If the reserved pool can't cover the need, it widens the pool with **preemption candidates**: en-route units whose current incident's priority is less than 1/2.2 of the new incident's (rule 4 — the 2.2 ratio is hysteresis again, preventing two similar incidents from stealing units back and forth). Units are then ranked by *routed* travel time plus a fuel penalty — not straight-line distance, so a nearby unit on the wrong side of a road closure correctly loses to a farther one — and exactly the needed count is taken, never more (rule 2). Crucially, the whole allocation is **atomic** (rule 5): if any required type can't be fully sourced, or any chosen unit can't reach the scene, the function returns `None` and *nothing* is committed. Without this, a collapse needing two fire trucks and two ambulances could grab the trucks, fail on the ambulances, and leave the trucks uselessly parked at a scene they can't work — partial allocation under scarcity is how dispatch systems deadlock. Only after every unit clears does the commit block run, which is also where a preempted unit is cleanly detached from its old incident (and that incident flipped back to `PENDING` if it lost everything).

`tick()` is a state machine over `UnitStatus`, advanced once per simulation step: `EN_ROUTE` units first get a `reroute_if_blocked()` check against new closures, then arrive when the clock passes their ETA; arrival flips the incident to `ON_SCENE`, burns fuel, fires the response-time metric callback, and books scene time scaled by severity (5 minutes for severity 1 up to 25 for severity 5); finishing the scene resolves the incident and routes the unit home as `RETURNING`; and a unit that arrives home under 30% fuel detours through `REFUELING` for ten minutes before becoming `AVAILABLE` again. Fuel is therefore not decorative — under sustained load it visibly thins the fleet, which is the resource-shortage behavior the brief asked for.

## 7. `coordinator.py` — the swarm layer

`EventBus` is fifteen lines of in-process pub/sub with an append-only log, but its topic names (`calls.incoming`, `triage.report`, `incident.*`, `dispatch.order`) are a one-to-one map to the Kafka topics in the production design — the README's event-architecture table is literally a description of this class scaled up.

`SwarmCoordinator` wires the swarm together. Incoming calls are sharded **round-robin across N triage agents** (the simulation runs four), demonstrating the horizontally-scalable part of the design: because triage agents are stateless, the shard count is a free parameter. The resulting reports flow into the **quarantine gate**: a report with confidence below 0.42 that doesn't corroborate any active incident is parked rather than admitted. Every scheduling pass re-checks the quarantine — a parked report is released the moment an independent report creates a matching incident, and silently expires after seven minutes otherwise. The guarantee this buys is precise: a false report from a single hedging caller never moves a unit, while any real incident reported twice always gets through.

The scheduling heart is `step()`, called every tick: release or expire quarantined reports, rebuild the pending queue as a heap ordered by live `priority(now)`, walk it from the top offering each incident to `try_dispatch()` (incidents that can't be served — no location yet, fleet exhausted, scene unreachable — simply stay queued, where aging steadily raises their priority), and finally advance the unit world via `tick()`. The two callbacks passed into `tick()` close the metrics loop: arrival records the response time and credits the **lives-saved estimate** — `affected_people × max(0.1, 1 − response_time/1800) × severity/5`, a survival fraction decaying linearly to a 10% floor at thirty minutes — and resolution increments the resolved count and publishes the event.

`snapshot()` packages everything the brief's display list asks for (active incidents, backlog, top-five queue with priorities, per-fleet utilization, average response time, lives saved) into the dictionary that both the console output and `timeline.json` consume.

## 8. `simulation.py` and `main.py` — the harness

`simulation.py` is a discrete event loop with three interleaved schedules. The call schedule feeds 1,000+ generated calls onto the bus as the clock passes each one's timestamp. The disruption schedule injects 14 road closures and 30 congestion waves at random times, exercising the re-routing paths. And every tick the coordinator runs a full `step()`. The loop runs 30 minutes past the last call so in-flight incidents can drain, prints a dashboard line every 5 simulated minutes, and ends with the final report plus the honesty check: ground-truth incident count versus what the system created (the seed-42 run compresses 1,003 calls into 68 incidents against 320 ground-truth events — the gap is mostly genuinely indistinguishable same-place-same-type collisions, discussed in the README). `main.py` is a thin argparse wrapper exposing duration, incident count, seed, and tick size.

## 9. `dashboard.html` — the same system, live in a browser

The dashboard is a single self-contained file with no build step, organized into the same blocks as the Python package and labeled as such in the source: a city-graph section (the same 12×12 grid and A* router, ported to compact JS), a triage section (a streamlined extraction-plus-dedup using the same location/type/time-window scoring), the dispatch agent (same reserve, same atomic allocation, same 2.2× preemption ratio), and a unit-movement system that interpolates each unit's pixel position along its route edges so vehicles visibly travel rather than teleport. A `requestAnimationFrame` loop converts real time into simulation time at the selected speed, runs one swarm step, and redraws.

The rendering is layered SVG groups — roads (with closed roads dashed red), animated route polylines, stations, pulsing incident markers colored by severity, and unit dots — while the side panels re-render the priority queue (showing each incident's live computed score), stacked fleet-utilization bars, and a categorized dispatch log. The header controls (pause, speed, surge injection, road closure) mutate the same state the loop reads, so they take effect on the next frame. Design-wise it's built as a night-ops console: a deep blue-black palette, Saira Condensed for display numerals, IBM Plex Mono for telemetry, and reduced-motion users get the animations disabled via a media query.

## 10. How a call becomes a rescue — one trace through the code

To tie it together, here is the life of a single severity-5 call, with the function that handles each step: the generator emits *"HELP!! There is a bilding collapsed at sunrise apts! ppl traped under rubble! Maybe 40 people affected!"* (`callgen._transcript` → `_noisify`). The simulation clock reaches its timestamp and publishes it on `calls.incoming` (`simulation.run`). The coordinator shards it to triage agent 3 (`_on_call`), whose extractor fuzzy-matches "sunrise apts" to Sunrise Apartments / node 90, votes Building Collapse, reads 40 people, counts two urgency cues, and emits a confident report (`triage.extract`). Confidence is well above the gate, and the report scores 0.87 against incident INC0042 created by an earlier caller at the same node, so it merges — severity maxes to 5, the casualty estimate blends toward 40, confidence rises (`merge_or_create`, `_merge`). On the next `step()`, INC0042's priority — now boosted by corroboration and a minute of aging — tops the heap. `try_dispatch` needs 3 fire trucks, 3 ambulances, and a police unit; the fire-truck pool minus reserve is one short, but an en-route truck serving a severity-2 accident fails the 2.2× test and is preempted; all seven units route via A*, the slowest ETA is 4.1 minutes, and the order commits atomically. Two ticks later a closure lands on one route and `reroute_if_blocked` swaps that truck onto a detour. Units arrive (`tick`), the response time and lives-saved credit are recorded (`_on_arrival`), scene work runs 25 minutes, the incident resolves, and the units head home — one of them through the refueling bay.
