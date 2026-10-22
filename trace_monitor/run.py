"""
Main Runner — TRACE Pipeline
=============================
Orchestrates the full scoring pipeline:
  1. Load and validate traces
  2. Run all four rule-based scorers (evidence, consistency, uncertainty, policy)
  3. Combine signals causally and predict first unreliable step
  4. Output results.json

Usage:
  python -m trace_monitor.run data/traces/ --labels data/labels.json
  python -m trace_monitor.run data/traces/ --labels data/labels.json --system baseline
"""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path
from typing import Any

from .schema_validator import validate_all
from .evidence_scorer import score_evidence
from .consistency_scorer import score_consistency
from .uncertainty_scorer import score_uncertainty
from .policy_scorer import score_policy
from .combiner import combine_signals, sweep_thresholds
from .signals import SignalRecord, TraceResult


# ---------------------------------------------------------------------------
# Trace loading
# ---------------------------------------------------------------------------

def load_traces(traces_dir: str | Path) -> list[dict[str, Any]]:
    """Load all trace JSON files from a directory."""
    traces_dir = Path(traces_dir)
    traces = []
    for trace_file in sorted(traces_dir.glob("T*.json")):
        with open(trace_file, "r", encoding="utf-8") as f:
            traces.append(json.load(f))
    return traces


def load_labels(labels_path: str | Path) -> dict[str, dict]:
    """Load ground-truth labels."""
    with open(labels_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Baseline: final-answer-only scorer
# ---------------------------------------------------------------------------

def score_baseline(trace: dict[str, Any]) -> TraceResult:
    """
    Final-answer-only baseline (S8).
    Only looks at the last answer step — ignores intermediate steps.
    This is what most current monitors do.
    """
    tid = trace["trace_id"]
    steps = trace["steps"]

    # Find the last answer step
    answer_steps = [s for s in steps if s["type"] == "answer"]
    if not answer_steps:
        return TraceResult(
            trace_id=tid,
            predicted_first_unreliable_step=None,
            predicted_failure_type=None,
            system="baseline",
        )

    last_answer = answer_steps[-1]
    content = last_answer.get("content", "")

    # Simple checks on the final answer only
    # This deliberately misses intermediate failures — that's the point
    from .evidence_scorer import _extract_numbers, _extract_keywords
    from .policy_scorer import _find_pii, DEFAULT_POLICY

    flagged = False
    failure_type = None

    # Check for PII in answer
    pii = _find_pii(content, DEFAULT_POLICY["pii_patterns"])
    if pii:
        flagged = True
        failure_type = "privacy"

    # Check for hedging (very basic)
    hedging = {"maybe", "perhaps", "possibly", "i think", "not sure"}
    content_lower = content.lower()
    hedge_count = sum(1 for h in hedging if h in content_lower)
    if hedge_count >= 3:
        flagged = True
        failure_type = "uncertainty"

    result = TraceResult(
        trace_id=tid,
        predicted_first_unreliable_step=last_answer["step_id"] if flagged else None,
        predicted_failure_type=failure_type,
        system="baseline",
    )
    return result


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    traces: list[dict[str, Any]],
    system: str = "trace_monitor",
    policy_path: str | Path | None = None,
) -> list[TraceResult]:
    """
    Run the full TRACE pipeline on a list of traces.
    
    Args:
        traces: List of trace dicts
        system: One of "trace_monitor" (step-level causal monitoring) or "baseline" (final-answer-only)
        policy_path: Path to policy_rules.yaml
    
    Returns:
        List of TraceResult objects
    """
    results: list[TraceResult] = []

    for trace in traces:
        tid = trace["trace_id"]

        if system == "baseline":
            results.append(score_baseline(trace))
            continue

        # Run 4 rule-based scorers across all steps
        all_signals: list[SignalRecord] = []
        all_signals.extend(score_evidence(trace))
        all_signals.extend(score_consistency(trace))
        all_signals.extend(score_uncertainty(trace))
        all_signals.extend(score_policy(trace, policy_path))

        # Combine causally
        result = combine_signals(trace, all_signals)
        result.system = "trace_monitor"
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def results_to_json(results: list[TraceResult]) -> dict[str, Any]:
    """Convert results to the output JSON format."""
    return {
        "system": results[0].system if results else "unknown",
        "traces": {r.trace_id: r.to_dict() for r in results},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TRACE: Trust Risk Assessment across Chained Executions"
    )
    parser.add_argument("traces_dir", help="Directory containing trace JSON files")
    parser.add_argument("--labels", help="Path to labels.json")
    parser.add_argument("--policy", help="Path to policy_rules.yaml")
    parser.add_argument("--system", choices=["trace_monitor", "baseline", "rules_only"],
                        default="trace_monitor", help="Which system to run (trace_monitor or baseline)")
    parser.add_argument("--output", "-o", default="results.json", help="Output file path")
    parser.add_argument("--validate-only", action="store_true", help="Only validate traces, don't score")
    parser.add_argument("--sweep", action="store_true", help="Run threshold sweep on dev traces")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    args = parser.parse_args()

    # --- Validate ---
    print("=" * 60)
    print("TRACE — Trust Risk Assessment across Chained Executions")
    print("=" * 60)

    print(f"\n📁 Loading traces from: {args.traces_dir}")
    errors = validate_all(args.traces_dir, args.labels)

    if errors:
        print("\n⚠ Validation issues:")
        for e in errors:
            print(f"  {e}")
        n_errors = sum(1 for e in errors if e.severity == "error")
        if n_errors:
            print(f"\n✗ {n_errors} error(s) found. Fix them before scoring.")
            sys.exit(1)
    else:
        print("✓ All traces valid.")

    if args.validate_only:
        return

    # --- Load ---
    traces = load_traces(args.traces_dir)
    labels = load_labels(args.labels) if args.labels else {}
    print(f"✓ Loaded {len(traces)} traces")

    # --- Determine system ---
    system = "trace_monitor" if args.system in ("trace_monitor", "rules_only") else "baseline"

    # --- Run ---
    print(f"\n🔍 Running system: {system}")
    results = run_pipeline(traces, system=system, policy_path=args.policy)

    # --- Output ---
    output = results_to_json(results)
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\n📄 Results written to: {output_path}")

    # --- Summary ---
    print(f"\n{'─' * 60}")
    print(f"{'Trace':<8} {'Predicted Step':>15} {'True Step':>12} {'Type':>15} {'Match':>7}")
    print(f"{'─' * 60}")

    correct = 0
    total = 0
    for r in results:
        tid = r.trace_id
        pred = r.predicted_first_unreliable_step
        true_label = labels.get(tid, {})
        true_step = true_label.get("first_unreliable_step")
        pred_str = str(pred) if pred is not None else "clean"
        true_str = str(true_step) if true_step is not None else "clean"
        match = "✓" if pred == true_step else "✗"
        ftype = r.predicted_failure_type or ""

        total += 1
        if pred == true_step:
            correct += 1

        print(f"{tid:<8} {pred_str:>15} {true_str:>12} {ftype:>15} {match:>7}")

    print(f"{'─' * 60}")
    if total > 0:
        print(f"Accuracy: {correct}/{total} = {correct / total:.1%}")
    print()

    # --- Threshold sweep ---
    if args.sweep:
        print("\n📊 Threshold Sweep (dev traces only)")
        dev_traces = [t for t in traces if not t.get("held_out", False)]
        dev_signals = {}
        for t in dev_traces:
            tid = t["trace_id"]
            sigs = []
            sigs.extend(score_evidence(t))
            sigs.extend(score_consistency(t))
            sigs.extend(score_uncertainty(t))
            sigs.extend(score_policy(t))
            dev_signals[tid] = sigs

        sweep = sweep_thresholds(dev_traces, dev_signals, labels)
        print(f"\n{'Thresh':>8} {'Acc':>6} {'Prec':>6} {'Rec':>6} {'F1':>6} {'TP':>4} {'FP':>4} {'TN':>4} {'FN':>4}")
        for row in sweep:
            print(
                f"{row['threshold']:>8.3f} "
                f"{row['accuracy']:>6.3f} "
                f"{row['precision']:>6.3f} "
                f"{row['recall']:>6.3f} "
                f"{row['f1']:>6.3f} "
                f"{row['tp']:>4} "
                f"{row['fp']:>4} "
                f"{row['tn']:>4} "
                f"{row['fn']:>4}"
            )


if __name__ == "__main__":
    main()
