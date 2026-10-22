"""
S6 — Signal Combiner + First-Unreliable-Step Logic
===================================================
Aggregates signals from all scorers into a per-step risk profile and
identifies the first unreliable step in a trace.

Key properties:
  - Causal: step t only considers signals from steps <= t
  - Weighted: different scorers contribute different weights
  - Monotonic: once a step is flagged, downstream steps inherit elevated risk

Combiner formula:
  combined_score(step) = Σ(w_scorer * max_signal_from_scorer_at_step)
  
  Weights (documented, not calibrated — calibration is listed as future work):
    evidence:     0.30
    consistency:  0.35
    uncertainty:  0.10   (lower because it's a proxy)
    policy:       0.25
"""

from __future__ import annotations

from typing import Any

from .signals import SignalRecord, StepRiskProfile, TraceResult


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCORER_WEIGHTS: dict[str, float] = {
    "evidence": 0.30,
    "consistency": 0.35,
    "uncertainty": 0.10,
    "policy": 0.25,
}

# Threshold for flagging a step as "unreliable"
RISK_THRESHOLD = 0.20

# How fast risk decays in subsequent clean steps (0 = no decay)
RISK_DECAY = 0.1

# Minimum inherited risk from a previously-flagged step
MIN_INHERITED_RISK = 0.15


# ---------------------------------------------------------------------------
# Combiner
# ---------------------------------------------------------------------------

def combine_signals(
    trace: dict[str, Any],
    all_signals: list[SignalRecord],
    risk_threshold: float = RISK_THRESHOLD,
) -> TraceResult:
    """
    Combine signals from all scorers into a TraceResult.
    
    Args:
        trace: The raw trace dict
        all_signals: All signals from all scorers
        risk_threshold: Score above which a step is considered unreliable
    
    Returns:
        TraceResult with per-step profiles and predicted first unreliable step
    """
    tid = trace["trace_id"]
    steps = trace["steps"]

    # Group signals by step_id
    signals_by_step: dict[int, list[SignalRecord]] = {}
    for sig in all_signals:
        signals_by_step.setdefault(sig.step_id, []).append(sig)

    # Build step profiles (causal: process in order)
    step_profiles: list[StepRiskProfile] = []
    predicted_step: int | None = None
    predicted_failure: str | None = None
    max_upstream_risk = 0.0

    for step in steps:
        sid = step["step_id"]
        step_signals = signals_by_step.get(sid, [])

        # Calculate combined score
        # For each scorer, take the max signal score
        scorer_max: dict[str, float] = {}
        for sig in step_signals:
            scorer = sig.scorer
            if scorer not in scorer_max or sig.score > scorer_max[scorer]:
                scorer_max[scorer] = sig.score

        # Weighted combination
        combined = 0.0
        for scorer, max_score in scorer_max.items():
            weight = SCORER_WEIGHTS.get(scorer, 0.0)
            combined += weight * max_score

        # Inherit risk from upstream (monotonic)
        inherited = max(0.0, max_upstream_risk - RISK_DECAY)
        if inherited > MIN_INHERITED_RISK:
            combined = max(combined, inherited)

        # Determine dominant signal
        dominant = ""
        if scorer_max:
            dominant = max(scorer_max, key=scorer_max.get)

        # Collect all reasons
        reasons = [sig.reason for sig in step_signals if sig.reason]

        profile = StepRiskProfile(
            trace_id=tid,
            step_id=sid,
            signals=step_signals,
            combined_score=round(combined, 4),
            dominant_signal=dominant,
            reasons=reasons,
        )
        step_profiles.append(profile)

        # Update max upstream risk
        max_upstream_risk = max(max_upstream_risk, combined)

        # Flag first unreliable step
        if predicted_step is None and combined >= risk_threshold:
            predicted_step = sid
            predicted_failure = _infer_failure_type(dominant, step_signals)

    return TraceResult(
        trace_id=tid,
        step_profiles=step_profiles,
        predicted_first_unreliable_step=predicted_step,
        predicted_failure_type=predicted_failure,
    )


def _infer_failure_type(dominant_scorer: str, signals: list[SignalRecord]) -> str | None:
    """Infer the failure type from the dominant scorer and its rules."""
    scorer_to_failure: dict[str, str] = {
        "evidence": "evidence",
        "consistency": "consistency",
        "uncertainty": "uncertainty",
        "policy": "privacy",  # policy scorer often catches privacy issues
    }

    if not dominant_scorer:
        return None

    # Check if any policy signal specifically flags privacy
    for sig in signals:
        if sig.scorer == "policy":
            for rule in sig.fired_rules:
                if "pii" in rule.lower():
                    return "privacy"

    return scorer_to_failure.get(dominant_scorer)


# ---------------------------------------------------------------------------
# Threshold sweep (for evaluation)
# ---------------------------------------------------------------------------

def sweep_thresholds(
    traces: list[dict[str, Any]],
    all_signals_per_trace: dict[str, list[SignalRecord]],
    labels: dict[str, dict],
    thresholds: list[float] | None = None,
) -> list[dict[str, Any]]:
    """
    Sweep risk thresholds and compute metrics at each.
    Used for finding optimal threshold on dev traces only.
    
    Returns list of {threshold, accuracy, precision, recall, f1, details}.
    """
    if thresholds is None:
        thresholds = [i * 0.05 for i in range(1, 20)]  # 0.05 to 0.95

    results = []
    for thresh in thresholds:
        tp = fp = tn = fn = 0
        step_matches = 0
        total_flagged = 0

        for trace in traces:
            tid = trace["trace_id"]
            sigs = all_signals_per_trace.get(tid, [])
            label = labels.get(tid, {})
            true_step = label.get("first_unreliable_step")

            result = combine_signals(trace, sigs, risk_threshold=thresh)
            pred_step = result.predicted_first_unreliable_step

            if true_step is not None:
                if pred_step is not None:
                    tp += 1
                    if pred_step == true_step:
                        step_matches += 1
                else:
                    fn += 1
            else:
                if pred_step is not None:
                    fp += 1
                else:
                    tn += 1

            if pred_step is not None:
                total_flagged += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0

        results.append({
            "threshold": round(thresh, 3),
            "accuracy": round(accuracy, 3),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "step_matches": step_matches,
            "total_flagged": total_flagged,
        })

    return results
