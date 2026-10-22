"""
Signal Record
=============
Data structures used by all scorers to report their findings.
Each scorer produces one SignalRecord per step it evaluates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SignalRecord:
    """One signal emitted by one scorer for one step."""

    trace_id: str
    step_id: int
    scorer: str          # "evidence", "consistency", "uncertainty", "policy"
    score: float         # risk score in [0.0, 1.0]
    fired_rules: list[str] = field(default_factory=list)
    reason: str = ""
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignalRecord:
        return cls(**d)


@dataclass
class StepRiskProfile:
    """Aggregated risk for a single step across all scorers."""

    trace_id: str
    step_id: int
    signals: list[SignalRecord] = field(default_factory=list)
    combined_score: float = 0.0
    dominant_signal: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d


@dataclass
class TraceResult:
    """Full scoring result for one trace."""

    trace_id: str
    step_profiles: list[StepRiskProfile] = field(default_factory=list)
    predicted_first_unreliable_step: int | None = None
    predicted_failure_type: str | None = None
    system: str = "trace_monitor"  # "trace_monitor", "baseline"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "system": self.system,
            "predicted_first_unreliable_step": self.predicted_first_unreliable_step,
            "predicted_failure_type": self.predicted_failure_type,
            "step_profiles": [sp.to_dict() for sp in self.step_profiles],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
