"""Synthetic 911 call stream generator.

Produces a continuous high-volume stream of noisy transcripts:
duplicates of the same ground-truth incident, panicked language,
misspellings, missing locations, multi-incident calls and false reports.
"""
from __future__ import annotations

import random

from .models import EmergencyCall, IncidentType

# ---- gazetteer: landmark -> (graph node, aliases) ------------------------
LANDMARKS: dict[str, dict] = {
    "Central Mall":        {"node": 66,  "aliases": ["shopping center downtown", "the big mall", "central shoping mall", "downtown mall"]},
    "Riverside Bridge":    {"node": 14,  "aliases": ["the old bridge", "river bridge", "riverside brige"]},
    "Northgate Hospital":  {"node": 9,   "aliases": ["the hospital up north", "northgate medical", "north hospital"]},
    "Maple Street School": {"node": 100, "aliases": ["the elementary school", "maple st school", "school on maple"]},
    "Harbor District":     {"node": 132, "aliases": ["the docks", "harbour district", "down by the harbor"]},
    "City Hall":           {"node": 71,  "aliases": ["town hall", "the city hall plaza"]},
    "Westside Chemical Plant": {"node": 48, "aliases": ["the chemical factory", "westside plant", "chem plant on the west side"]},
    "Sunrise Apartments":  {"node": 90,  "aliases": ["sunrise towers", "the apartment block on 7th", "sunrise apts"]},
    "Grand Station":       {"node": 77,  "aliases": ["the train station", "grand central station", "main station"]},
    "Oakwood Park":        {"node": 27,  "aliases": ["the big park", "oakwood gardens", "oak wood park"]},
    "Highway 9 Interchange": {"node": 11, "aliases": ["the highway ramp", "hwy 9", "interchange on highway nine"]},
    "Eastbank Market":     {"node": 119, "aliases": ["the farmers market", "east bank market", "eastside market"]},
    "Pinecrest Library":   {"node": 38,  "aliases": ["the public library", "pinecrest branch"]},
    "Southport Stadium":   {"node": 127, "aliases": ["the stadium", "southport arena"]},
    "Lakeview Hotel":      {"node": 55,  "aliases": ["the hotel by the lake", "lakeview inn"]},
    "Ferris Industrial Park": {"node": 4, "aliases": ["the industrial park", "ferris warehouses"]},
    "St. Anne Church":     {"node": 93,  "aliases": ["the old church", "saint anne", "st annes"]},
    "Birchwood Cinema":    {"node": 82,  "aliases": ["the movie theater", "birchwood theatre"]},
    "Copper Tower Offices": {"node": 64, "aliases": ["the office tower", "copper tower"]},
    "Greenfield Suburb":   {"node": 140, "aliases": ["greenfield neighborhood", "green field houses"]},
    "Mercer Bus Depot":    {"node": 31,  "aliases": ["the bus depot", "mercer terminal"]},
    "Aurora Power Substation": {"node": 7, "aliases": ["the power station", "aurora substation"]},
    "Kingsway Tunnel":     {"node": 109, "aliases": ["the tunnel", "kings way underpass"]},
    "Bayside Pier":        {"node": 134, "aliases": ["the pier", "bay side boardwalk"]},
}

TYPE_PHRASES = {
    IncidentType.FIRE: [
        "huge fire", "building on fire", "flames everywhere", "lots of smoke",
        "smoke pouring out", "its burning", "fire spreading fast"],
    IncidentType.MEDICAL: [
        "someone collapsed", "heart attack", "person not breathing",
        "lots of injured people", "she's unconscious", "bad injuries"],
    IncidentType.ACCIDENT: [
        "terrible car crash", "multi car pileup", "truck flipped over",
        "two cars collided", "motorcycle accident"],
    IncidentType.FLOOD: [
        "water rising fast", "street is flooding", "people stuck on roofs",
        "flash flood", "cars floating away"],
    IncidentType.COLLAPSE: [
        "building collapsed", "the wall came down", "structure caved in",
        "people trapped under rubble", "ceiling collapsed"],
    IncidentType.HAZMAT: [
        "chemical leak", "weird gas smell", "toxic spill",
        "people coughing from fumes", "tanker leaking something"],
}

PANIC = ["Please help!", "Oh my god,", "HELP!!", "Hurry please,", "I dont know what to do,",
         "Send someone NOW,", "please please", "uh, hi, um,"]
TRAPPED = ["I think people are trapped!", "people screaming!", "kids are inside!",
           "someone is hurt bad!", "we cant get out!", "many injured!"]

TYPO = {"fire": "fyre", "people": "ppl", "there": "ther", "building": "bilding",
        "street": "streat", "trapped": "traped", "ambulance": "ambulence"}


def _noisify(text: str, rng: random.Random) -> str:
    words = text.split()
    out = []
    for w in words:
        lw = w.lower().strip(",.!")
        if lw in TYPO and rng.random() < 0.25:
            w = w.replace(lw, TYPO[lw])
        if rng.random() < 0.04:
            continue  # dropped word
        out.append(w)
    return " ".join(out)


class GroundTruthIncident:
    def __init__(self, key: str, itype: IncidentType, landmark: str,
                 severity: int, people: int, start: float):
        self.key, self.itype, self.landmark = key, itype, landmark
        self.severity, self.people, self.start = severity, people, start


class CallGenerator:
    def __init__(self, n_incidents: int = 220, duration: float = 3600.0,
                 false_rate: float = 0.07, seed: int = 42):
        self.rng = random.Random(seed)
        self.duration = duration
        self.false_rate = false_rate
        self.truth: list[GroundTruthIncident] = []
        names = list(LANDMARKS)
        for i in range(n_incidents):
            itype = self.rng.choice(list(TYPE_PHRASES))
            sev = self.rng.choices([1, 2, 3, 4, 5], weights=[10, 22, 30, 25, 13])[0]
            people = max(0, int(self.rng.gauss(sev * 6, sev * 3)))
            # escalating disaster: incident rate and severity rise mid-simulation
            t = self.rng.betavariate(2, 2) * duration
            self.truth.append(GroundTruthIncident(
                f"GT{i:04d}", itype, self.rng.choice(names), sev, people, t))

    def _transcript(self, gt: GroundTruthIncident, hide_loc: bool, second: GroundTruthIncident | None) -> str:
        rng = self.rng
        phrase = rng.choice(TYPE_PHRASES[gt.itype])
        loc = "" if hide_loc else (
            f" near {gt.landmark}" if rng.random() < 0.5
            else f" at {rng.choice([gt.landmark] + LANDMARKS[gt.landmark]['aliases'])}")
        parts = [rng.choice(PANIC), f"There is a {phrase}{loc}!"]
        if rng.random() < 0.6:
            parts.append(rng.choice(TRAPPED))
        if gt.people > 10 and rng.random() < 0.5:
            est = max(1, int(gt.people * rng.uniform(0.4, 1.8)))  # conflicting counts
            parts.append(f"Maybe {est} people affected!")
        if second is not None:
            parts.append(f"Also I can see a {rng.choice(TYPE_PHRASES[second.itype])} "
                         f"near {second.landmark}!")
        return _noisify(" ".join(parts), rng)

    def generate(self) -> list[EmergencyCall]:
        calls: list[EmergencyCall] = []
        rng = self.rng
        for gt in self.truth:
            n_dupes = rng.choices([1, 2, 3, 4, 6, 9], weights=[25, 25, 20, 15, 10, 5])[0]
            for d in range(n_dupes):
                t = gt.start + abs(rng.gauss(0, 90)) + d * rng.uniform(5, 40)
                hide = rng.random() < 0.12
                second = rng.choice(self.truth) if rng.random() < 0.04 else None
                calls.append(EmergencyCall.new(
                    self._transcript(gt, hide, second), min(t, self.duration),
                    truth_incident_key=gt.key,
                    caller_location_hint=None if hide else gt.landmark))
        # false reports
        n_false = int(len(calls) * self.false_rate)
        for _ in range(n_false):
            itype = rng.choice(list(TYPE_PHRASES))
            lm = rng.choice(list(LANDMARKS))
            txt = _noisify(f"{rng.choice(PANIC)} I think theres a "
                           f"{rng.choice(TYPE_PHRASES[itype])} at {lm}? not sure, "
                           f"my friend told me", rng)
            calls.append(EmergencyCall.new(txt, rng.uniform(0, self.duration),
                                           truth_is_false_report=True))
        calls.sort(key=lambda c: c.received_at)
        return calls
