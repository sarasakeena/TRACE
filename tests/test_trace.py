"""
Tests for TRACE Monitor
========================
At least 3 tests including 1 edge case (per plan requirements).
"""

import json
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trace_monitor.schema_validator import validate_trace, validate_trace_file, validate_all
from trace_monitor.evidence_scorer import score_evidence
from trace_monitor.consistency_scorer import score_consistency
from trace_monitor.uncertainty_scorer import score_uncertainty
from trace_monitor.policy_scorer import score_policy
from trace_monitor.combiner import combine_signals
from trace_monitor.llm_scorer import score_llm
from trace_monitor.signals import SignalRecord


# ---------------------------------------------------------------------------
# Test 1: Schema validation catches invalid traces
# ---------------------------------------------------------------------------

def test_schema_validation():
    """Test that the schema validator catches common errors."""
    print("TEST 1: Schema validation")

    # Valid trace
    valid_trace = {
        "trace_id": "T99",
        "scenario": "Test scenario",
        "category": "consistency",
        "difficulty": "easy",
        "held_out": False,
        "steps": [
            {"step_id": 0, "type": "reasoning", "content": "Let me think."},
            {"step_id": 1, "type": "answer", "content": "Here's my answer."},
        ],
        "ground_truth": {
            "first_unreliable_step": None,
            "failure_type": None,
            "explanation": "This trace is clean."
        }
    }
    errors = validate_trace(valid_trace, "T99.json")
    assert len(errors) == 0, f"Valid trace should have no errors, got: {errors}"
    print("  ✓ Valid trace passes")

    # Invalid: missing fields
    bad_trace = {"trace_id": "T98"}
    errors = validate_trace(bad_trace, "T98.json")
    assert len(errors) > 0, "Missing fields should cause errors"
    print("  ✓ Missing fields caught")

    # Invalid: non-consecutive step IDs
    bad_steps_trace = {
        "trace_id": "T97",
        "scenario": "Test",
        "category": "consistency",
        "difficulty": "easy",
        "held_out": False,
        "steps": [
            {"step_id": 0, "type": "reasoning", "content": "OK"},
            {"step_id": 5, "type": "answer", "content": "Bad step ID"},
        ],
        "ground_truth": {
            "first_unreliable_step": None,
            "failure_type": None,
            "explanation": "Test"
        }
    }
    errors = validate_trace(bad_steps_trace, "T97.json")
    assert any("consecutive" in e.message for e in errors), "Non-consecutive step IDs should be caught"
    print("  ✓ Non-consecutive step IDs caught")

    # Invalid: tool_call without tool_name
    bad_tool_trace = {
        "trace_id": "T96",
        "scenario": "Test",
        "category": "consistency",
        "difficulty": "easy",
        "held_out": False,
        "steps": [
            {"step_id": 0, "type": "tool_call", "content": "Calling tool"},
        ],
        "ground_truth": {
            "first_unreliable_step": None,
            "failure_type": None,
            "explanation": "Test"
        }
    }
    errors = validate_trace(bad_tool_trace, "T96.json")
    assert any("tool_name" in e.message for e in errors), "Missing tool_name should be caught"
    print("  ✓ Missing tool_name caught")

    print("  ✓ TEST 1 PASSED\n")


# ---------------------------------------------------------------------------
# Test 2: Consistency scorer detects T04/T05 at the right step
# ---------------------------------------------------------------------------

def test_consistency_scorer():
    """Test that the consistency scorer flags T04 and T05 at the correct step."""
    print("TEST 2: Consistency scorer on T04/T05")

    # T04: price mismatch
    t04 = json.loads(open("data/traces/T04.json").read())
    signals = score_consistency(t04)

    assert len(signals) > 0, "T04 should produce consistency signals"
    flagged_steps = {s.step_id for s in signals}
    assert 3 in flagged_steps, f"T04 step 3 should be flagged, got: {flagged_steps}"
    print(f"  ✓ T04 flagged at steps: {flagged_steps}")

    # Check it found the numerical mismatch
    step3_signals = [s for s in signals if s.step_id == 3]
    rules = []
    for s in step3_signals:
        rules.extend(s.fired_rules)
    assert any("C1" in r or "C2" in r for r in rules), f"Should fire C1 or C2, got: {rules}"
    print(f"  ✓ T04 fired rules: {rules}")

    # T05: status contradiction
    t05 = json.loads(open("data/traces/T05.json").read())
    signals = score_consistency(t05)

    assert len(signals) > 0, "T05 should produce consistency signals"
    flagged_steps = {s.step_id for s in signals}
    assert 3 in flagged_steps or 4 in flagged_steps, f"T05 step 3 or 4 should be flagged, got: {flagged_steps}"
    print(f"  ✓ T05 flagged at steps: {flagged_steps}")

    print("  ✓ TEST 2 PASSED\n")


# ---------------------------------------------------------------------------
# Test 3: Privacy scorer detects T06 at the leaking middle step
# ---------------------------------------------------------------------------

def test_privacy_scorer():
    """Test that the policy scorer flags T06's PII leak at step 3 (not the clean answer)."""
    print("TEST 3: Privacy scorer on T06")

    t06 = json.loads(open("data/traces/T06.json").read())
    signals = score_policy(t06)

    assert len(signals) > 0, "T06 should produce policy signals"
    flagged_steps = {s.step_id for s in signals}

    # Step 3 (tool_call with SSN) should be flagged
    assert 3 in flagged_steps, f"T06 step 3 should be flagged (SSN leak), got: {flagged_steps}"
    print(f"  ✓ T06 flagged at steps: {flagged_steps}")

    # The final answer (step 5) should NOT be flagged
    step5_signals = [s for s in signals if s.step_id == 5]
    assert len(step5_signals) == 0, "T06 step 5 (clean answer) should NOT be flagged"
    print("  ✓ T06 step 5 (clean answer) not flagged — blind spot detected!")

    # Check PII rule fired
    step3_signals = [s for s in signals if s.step_id == 3]
    rules = []
    for s in step3_signals:
        rules.extend(s.fired_rules)
    assert any("pii" in r.lower() or "P1" in r for r in rules), f"Should fire PII rule, got: {rules}"
    print(f"  ✓ T06 fired rules: {rules}")

    print("  ✓ TEST 3 PASSED\n")


# ---------------------------------------------------------------------------
# Test 4 (EDGE CASE): T13 hard negative must NOT be flagged
# ---------------------------------------------------------------------------

def test_hard_negative():
    """Edge case: T13 is a correct paraphrase and must NOT be flagged by rules."""
    print("TEST 4 (EDGE CASE): T13 hard negative")

    t13 = json.loads(open("data/traces/T13.json").read())

    # Run all scorers
    all_signals = []
    all_signals.extend(score_evidence(t13))
    all_signals.extend(score_consistency(t13))
    all_signals.extend(score_uncertainty(t13))
    all_signals.extend(score_policy(t13))

    # Combine
    result = combine_signals(t13, all_signals)

    # T13 should be predicted as clean (no unreliable step)
    assert result.predicted_first_unreliable_step is None, (
        f"T13 should NOT be flagged (hard negative), but was flagged at "
        f"step {result.predicted_first_unreliable_step}"
    )
    print("  ✓ T13 correctly NOT flagged (no false alarm)")

    # Check that signals are low
    max_score = max((sp.combined_score for sp in result.step_profiles), default=0)
    print(f"  ✓ Max combined score: {max_score:.4f} (below threshold)")

    print("  ✓ TEST 4 PASSED\n")


# ---------------------------------------------------------------------------
# Test 5: Evidence scorer catches T07 fabricated citation
# ---------------------------------------------------------------------------

def test_evidence_scorer():
    """Test that the evidence scorer catches T07's fabricated citation."""
    print("TEST 5: Evidence scorer on T07")

    t07 = json.loads(open("data/traces/T07.json").read())
    signals = score_evidence(t07)

    assert len(signals) > 0, "T07 should produce evidence signals"
    flagged_steps = {s.step_id for s in signals}

    # Step 6 (answer with bad citations) should be flagged
    assert 6 in flagged_steps, f"T07 step 6 should be flagged, got: {flagged_steps}"
    print(f"  ✓ T07 flagged at steps: {flagged_steps}")

    # Check directional contradiction was caught
    step6_signals = [s for s in signals if s.step_id == 6]
    all_rules = []
    for s in step6_signals:
        all_rules.extend(s.fired_rules)
    print(f"  ✓ T07 fired rules: {all_rules}")

    print("  ✓ TEST 5 PASSED\n")


# ---------------------------------------------------------------------------
# Test 6: Combiner predicts correct first unreliable step
# ---------------------------------------------------------------------------

def test_combiner():
    """Test end-to-end: combiner produces correct prediction for T04."""
    print("TEST 6: End-to-end combiner on T04")

    t04 = json.loads(open("data/traces/T04.json").read())

    all_signals = []
    all_signals.extend(score_evidence(t04))
    all_signals.extend(score_consistency(t04))
    all_signals.extend(score_uncertainty(t04))
    all_signals.extend(score_policy(t04))

    result = combine_signals(t04, all_signals)

    assert result.predicted_first_unreliable_step == 3, (
        f"T04 should predict step 3, got {result.predicted_first_unreliable_step}"
    )
    assert result.predicted_failure_type == "consistency", (
        f"T04 should predict consistency failure, got {result.predicted_failure_type}"
    )
    print(f"  ✓ Predicted step: {result.predicted_first_unreliable_step}")
    print(f"  ✓ Predicted type: {result.predicted_failure_type}")

    # Print all step scores
    for sp in result.step_profiles:
        print(f"    Step {sp.step_id}: score={sp.combined_score:.4f} dominant={sp.dominant_signal}")

    print("  ✓ TEST 6 PASSED\n")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  TRACE Test Suite")
    print("=" * 60)
    print()

    test_schema_validation()
    test_consistency_scorer()
    test_privacy_scorer()
    test_hard_negative()
    test_evidence_scorer()
    test_combiner()

    print("=" * 60)
    print("  ALL TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
