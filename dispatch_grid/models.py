"""Core data models / schemas for the Smart City Dynamic Dispatch Grid."""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IncidentType(str, Enum):
    FIRE = "Fire"
    MEDICAL = "Medical"
    ACCIDENT = "Accident"
    FLOOD = "Flood"
    COLLAPSE = "Building Collapse"
    HAZMAT = "Hazardous Material"
    UNKNOWN = "Unknown"


class IncidentStatus(str, Enum):
    PENDING = "pending"          # triaged, waiting for resources
    DISPATCHED = "dispatched"    # units en route
    ON_SCENE = "on_scene"        # units arrived, being handled
    RESOLVED = "resolved"
    FALSE_REPORT = "false_report"


class UnitType(str, Enum):
    AMBULANCE = "Ambulance"
    FIRE_TRUCK = "FireTruck"
    POLICE = "PoliceUnit"
    HAZMAT_TEAM = "HazmatTeam"
    RESCUE_BOAT = "RescueBoat"


class UnitStatus(str, Enum):
    AVAILABLE = "available"
    EN_ROUTE = "en_route"
    ON_SCENE = "on_scene"
    RETURNING = "returning"
    REFUELING = "refueling"
    OUT_OF_SERVICE = "out_of_service"


# Which unit types an incident type needs, scaled later by severity.
RESOURCE_PROFILE: dict[IncidentType, dict[UnitType, int]] = {
    IncidentType.FIRE:     {UnitType.FIRE_TRUCK: 1, UnitType.AMBULANCE: 1},
    IncidentType.MEDICAL:  {UnitType.AMBULANCE: 1},
    IncidentType.ACCIDENT: {UnitType.POLICE: 1, UnitType.AMBULANCE: 1},
    IncidentType.FLOOD:    {UnitType.RESCUE_BOAT: 1, UnitType.POLICE: 1},
    IncidentType.COLLAPSE: {UnitType.FIRE_TRUCK: 2, UnitType.AMBULANCE: 2, UnitType.POLICE: 1},
    IncidentType.HAZMAT:   {UnitType.HAZMAT_TEAM: 1, UnitType.FIRE_TRUCK: 1, UnitType.POLICE: 1},
    IncidentType.UNKNOWN:  {UnitType.POLICE: 1},
}

_call_seq = itertools.count(1)
_inc_seq = itertools.count(1)


@dataclass
class EmergencyCall:
    """A single raw 911 call transcript entering the system."""
    call_id: str
    transcript: str
    received_at: float                 # sim time, seconds
    caller_location_hint: Optional[str] = None
    # ground truth used only for scoring the simulation, never by agents:
    truth_incident_key: Optional[str] = None
    truth_is_false_report: bool = False

    @staticmethod
    def new(transcript: str, t: float, **kw) -> "EmergencyCall":
        return EmergencyCall(call_id=f"CALL{next(_call_seq):05d}",
                             transcript=transcript, received_at=t, **kw)


@dataclass
class TriageReport:
    """Structured extraction produced by the Triage Agent for one call."""
    call_id: str
    location: Optional[str]
    node: Optional[int]                # resolved graph node, if location known
    incident_type: IncidentType
    severity: int                      # 1-5
    affected_people: int
    resources_needed: dict[UnitType, int]
    urgency: float                     # 0.5 - 2.0 from language cues
    confidence: float                  # 0-1 extraction confidence
    received_at: float


@dataclass
class Incident:
    """A merged, deduplicated incident record in the global queue."""
    incident_id: str
    incident_type: IncidentType
    location: Optional[str]
    node: Optional[int]
    severity: int
    affected_people: int
    urgency: float
    resources_needed: dict[UnitType, int]
    first_reported: float
    last_reported: float
    report_count: int = 1
    status: IncidentStatus = IncidentStatus.PENDING
    confidence: float = 0.5
    assigned_units: list[str] = field(default_factory=list)
    dispatch_time: Optional[float] = None
    arrival_time: Optional[float] = None
    resolve_time: Optional[float] = None
    escalations: int = 0

    @staticmethod
    def next_id() -> str:
        return f"INC{next(_inc_seq):04d}"

    def priority(self, now: float) -> float:
        """Priority = Severity x LivesAtRisk x Urgency, with aging to
        prevent starvation of lower-priority incidents."""
        lives = max(1, self.affected_people)
        lives_factor = 1.0 + (lives ** 0.5)            # diminishing returns
        wait = max(0.0, now - self.first_reported)
        aging = 1.0 + min(1.0, wait / 600.0)           # +100% after 10 min
        corroboration = min(1.5, 0.8 + 0.1 * self.report_count)
        return self.severity * lives_factor * self.urgency * aging * corroboration


@dataclass
class Unit:
    """A physical emergency resource unit."""
    unit_id: str
    unit_type: UnitType
    home_node: int
    node: int                          # current position
    status: UnitStatus = UnitStatus.AVAILABLE
    fuel: float = 1.0                  # 0..1
    assigned_incident: Optional[str] = None
    eta: Optional[float] = None        # sim time of arrival
    return_eta: Optional[float] = None
    route: list[int] = field(default_factory=list)

    @property
    def dispatchable(self) -> bool:
        return self.status == UnitStatus.AVAILABLE and self.fuel > 0.15


@dataclass
class DispatchOrder:
    incident_id: str
    assigned_resources: list[str]
    eta_minutes: float
    routes: dict[str, list[int]]
    issued_at: float
    preempted_from: Optional[str] = None
