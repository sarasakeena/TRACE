"""
S1 — Schema Validator
=====================
Validates trace JSON files against the TRACE schema.

Validation rules:
  1. trace_id must match the filename (T04.json → "T04")
  2. step_id values must be consecutive starting from 0
  3. tool_call steps must have tool_name and tool_input
  4. tool_result steps must have tool_name and tool_output
  5. citations must reference valid, earlier step_ids
  6. first_unreliable_step must be valid step_id or null
  7. If first_unreliable_step is null, failure_type must also be null
"""

import json
import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = {"trace_id", "scenario", "category", "difficulty", "held_out", "steps", "ground_truth"}
VALID_CATEGORIES = {"consistency", "evidence", "privacy", "uncertainty", "hallucination", "policy", "clean"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_STEP_TYPES = {"reasoning", "tool_call", "tool_result", "answer"}
VALID_FAILURE_TYPES = {"consistency", "evidence", "privacy", "hallucination", "policy"}

REQUIRED_STEP_FIELDS = {"step_id", "type", "content"}
REQUIRED_GROUND_TRUTH = {"first_unreliable_step", "failure_type", "explanation"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError:
    """One validation problem found in a trace."""

    def __init__(self, trace_id: str, message: str, severity: str = "error"):
        self.trace_id = trace_id
        self.message = message
        self.severity = severity  # "error" or "warning"

    def __repr__(self) -> str:
        return f"[{self.severity.upper()}] {self.trace_id}: {self.message}"


def validate_trace(trace: dict[str, Any], filename: str | None = None) -> list[ValidationError]:
    """Validate a single trace dict.  Returns a list of ValidationError."""

    errors: list[ValidationError] = []
    tid = trace.get("trace_id", filename or "UNKNOWN")

    def err(msg: str, severity: str = "error") -> None:
        errors.append(ValidationError(tid, msg, severity))

    # --- Top-level fields ---------------------------------------------------
    missing = REQUIRED_TOP_LEVEL - set(trace.keys())
    if missing:
        err(f"Missing required top-level fields: {missing}")
        return errors  # can't continue without structure

    # trace_id vs filename
    if filename:
        expected_id = Path(filename).stem
        if trace["trace_id"] != expected_id:
            err(f"trace_id '{trace['trace_id']}' does not match filename '{expected_id}'")

    # category
    if trace["category"] not in VALID_CATEGORIES:
        err(f"Invalid category '{trace['category']}'. Must be one of {VALID_CATEGORIES}")

    # difficulty
    if trace["difficulty"] not in VALID_DIFFICULTIES:
        err(f"Invalid difficulty '{trace['difficulty']}'. Must be one of {VALID_DIFFICULTIES}")

    # held_out
    if not isinstance(trace["held_out"], bool):
        err("'held_out' must be a boolean")

    # --- Steps --------------------------------------------------------------
    steps = trace["steps"]
    if not isinstance(steps, list) or len(steps) == 0:
        err("'steps' must be a non-empty list")
        return errors

    step_ids = set()
    for i, step in enumerate(steps):
        # Required fields
        step_missing = REQUIRED_STEP_FIELDS - set(step.keys())
        if step_missing:
            err(f"Step {i}: missing fields {step_missing}")
            continue

        sid = step["step_id"]
        # Consecutive
        if sid != i:
            err(f"Step {i}: step_id is {sid}, expected {i} (must be consecutive from 0)")
        step_ids.add(sid)

        # Type
        if step["type"] not in VALID_STEP_TYPES:
            err(f"Step {sid}: invalid type '{step['type']}'")

        # tool_call requires tool_name + tool_input
        if step["type"] == "tool_call":
            if "tool_name" not in step:
                err(f"Step {sid}: tool_call step missing 'tool_name'")
            if "tool_input" not in step:
                err(f"Step {sid}: tool_call step missing 'tool_input'")

        # tool_result requires tool_name + tool_output
        if step["type"] == "tool_result":
            if "tool_name" not in step:
                err(f"Step {sid}: tool_result step missing 'tool_name'")
            if "tool_output" not in step:
                err(f"Step {sid}: tool_result step missing 'tool_output'")

        # Citations must reference earlier valid steps
        if "citations" in step:
            for cited in step["citations"]:
                if cited not in step_ids:
                    err(f"Step {sid}: cites step {cited} which does not exist yet")
                if isinstance(cited, int) and cited >= sid:
                    err(f"Step {sid}: cites step {cited} which is not earlier")

    # --- Ground truth -------------------------------------------------------
    gt = trace["ground_truth"]
    gt_missing = REQUIRED_GROUND_TRUTH - set(gt.keys())
    if gt_missing:
        err(f"ground_truth missing fields: {gt_missing}")
    else:
        fus = gt["first_unreliable_step"]
        ft = gt["failure_type"]

        if fus is not None:
            if fus not in step_ids:
                err(f"first_unreliable_step {fus} is not a valid step_id")
            if ft is None:
                err("first_unreliable_step is set but failure_type is null")
            elif ft not in VALID_FAILURE_TYPES:
                err(f"Invalid failure_type '{ft}'")
        else:
            if ft is not None:
                err("first_unreliable_step is null but failure_type is not null")

    return errors


def validate_trace_file(filepath: str | Path) -> list[ValidationError]:
    """Load and validate a single trace JSON file."""
    filepath = Path(filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            trace = json.load(f)
    except json.JSONDecodeError as e:
        return [ValidationError(filepath.stem, f"Invalid JSON: {e}")]
    except FileNotFoundError:
        return [ValidationError(filepath.stem, f"File not found: {filepath}")]

    return validate_trace(trace, filename=filepath.name)


def validate_labels_file(labels_path: str | Path, traces_dir: str | Path) -> list[ValidationError]:
    """Validate that labels.json is consistent with the traces directory."""
    errors: list[ValidationError] = []
    labels_path = Path(labels_path)
    traces_dir = Path(traces_dir)

    try:
        with open(labels_path, "r", encoding="utf-8") as f:
            labels = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        return [ValidationError("labels.json", str(e))]

    # Check every trace has a label
    trace_files = sorted(traces_dir.glob("T*.json"))
    trace_ids = {f.stem for f in trace_files}
    label_ids = set(labels.keys())

    for tid in trace_ids - label_ids:
        errors.append(ValidationError(tid, "Trace exists but has no label in labels.json", "warning"))

    for tid in label_ids - trace_ids:
        errors.append(ValidationError(tid, "Label exists but no trace file found", "warning"))

    return errors


def validate_all(traces_dir: str | Path, labels_path: str | Path | None = None) -> list[ValidationError]:
    """Validate all traces in a directory and optionally the labels file."""
    traces_dir = Path(traces_dir)
    all_errors: list[ValidationError] = []

    for trace_file in sorted(traces_dir.glob("T*.json")):
        all_errors.extend(validate_trace_file(trace_file))

    if labels_path:
        all_errors.extend(validate_labels_file(labels_path, traces_dir))

    return all_errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m trace_monitor.schema_validator <traces_dir> [labels.json]")
        sys.exit(1)

    traces_dir = sys.argv[1]
    labels_path = sys.argv[2] if len(sys.argv) > 2 else None

    errors = validate_all(traces_dir, labels_path)

    if not errors:
        print("✓ All traces valid.")
    else:
        for e in errors:
            print(e)
        n_errors = sum(1 for e in errors if e.severity == "error")
        n_warnings = sum(1 for e in errors if e.severity == "warning")
        print(f"\n{n_errors} error(s), {n_warnings} warning(s)")
        if n_errors:
            sys.exit(1)


if __name__ == "__main__":
    main()
