#!/usr/bin/env python3
"""
validate.py  —  TRACE Phase 1 validator
Validates every trace JSON against the schema, checks structural invariants,
and confirms every trace has a label entry.

Usage:  python validate.py
Returns exit code 0 on success, 1 on any failure.
"""

import json
import sys
import pathlib

# ---------------------------------------------------------------------------
# Try to import jsonschema; fall back to a minimal structural check if absent.
# ---------------------------------------------------------------------------
try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    print("[WARN] jsonschema not installed — schema validation skipped; structural checks only.\n")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = pathlib.Path(__file__).parent
SCHEMA_PATH  = BASE / "schema" / "trace_schema.json"
TRACES_DIR   = BASE / "data" / "traces"
LABELS_PATH  = BASE / "data" / "labels.json"

VALID_TYPES   = {"reasoning", "tool_call", "tool_result", "retrieval", "final"}
REQUIRED_STEP = {"step_id", "type", "content", "cites"}

errors   = []   # list of (trace_id_or_file, message)
warnings = []   # list of (trace_id_or_file, message)


def err(trace_id, msg):
    errors.append((trace_id, msg))
    print(f"  [ERROR] {msg}")


def warn(trace_id, msg):
    warnings.append((trace_id, msg))
    print(f"  [WARN]  {msg}")


# ---------------------------------------------------------------------------
# Load schema
# ---------------------------------------------------------------------------
with open(SCHEMA_PATH, encoding="utf-8") as f:
    schema = json.load(f)

# ---------------------------------------------------------------------------
# Load labels
# ---------------------------------------------------------------------------
with open(LABELS_PATH, encoding="utf-8") as f:
    labels = json.load(f)

labelled_ids = set(labels.keys())

# ---------------------------------------------------------------------------
# Validate each trace file
# ---------------------------------------------------------------------------
trace_files = sorted(TRACES_DIR.glob("*.json"))
if not trace_files:
    print("ERROR: no trace files found in", TRACES_DIR)
    sys.exit(1)

found_ids = set()

for tf in trace_files:
    print(f"\n-- {tf.name} " + "-" * 40)
    with open(tf, encoding="utf-8") as f:
        try:
            trace = json.load(f)
        except json.JSONDecodeError as exc:
            err(tf.name, f"JSON parse error: {exc}")
            continue

    tid = trace.get("trace_id", tf.stem)
    found_ids.add(tid)
    print(f"  trace_id : {tid}")

    # ── 1. JSON Schema validation ──────────────────────────────────────────
    if HAS_JSONSCHEMA:
        v = jsonschema.Draft7Validator(schema)
        schema_errs = sorted(v.iter_errors(trace), key=lambda e: list(e.path))
        if schema_errs:
            for se in schema_errs:
                err(tid, f"Schema: {se.message}  (path: {list(se.path)})")
        else:
            print("  schema   : OK")
    else:
        # minimal required-field check for the trace root
        for rf in ["trace_id", "task", "domain", "steps"]:
            if rf not in trace:
                err(tid, f"Missing required root field '{rf}'")

    steps = trace.get("steps", [])

    # ── 2. step_ids are 1..n with no gaps or duplicates ───────────────────
    ids_seen = []
    for s in steps:
        sid = s.get("step_id")
        if sid is None:
            err(tid, "A step is missing step_id")
        else:
            ids_seen.append(sid)

    expected = list(range(1, len(steps) + 1))
    if ids_seen != expected:
        err(tid, f"step_ids {ids_seen} are not sequential 1..{len(steps)}")
    else:
        print(f"  step_ids : {ids_seen} OK")

    # ── 3. Trace length 4–8 steps (T09 is 4 steps to start at step 1) ─────
    n = len(steps)
    if n < 4:
        err(tid, f"Only {n} steps; minimum is 4")
    elif n > 8:
        err(tid, f"{n} steps; maximum is 8")
    else:
        print(f"  length   : {n} steps OK")

    # ── 4. tool_call steps have tool_name + tool_args ─────────────────────
    for s in steps:
        stype = s.get("type", "")
        sid   = s.get("step_id", "?")
        if stype == "tool_call":
            if "tool_name" not in s:
                err(tid, f"step {sid} is tool_call but missing tool_name")
            if "tool_args" not in s:
                err(tid, f"step {sid} is tool_call but missing tool_args")
            elif not isinstance(s["tool_args"], dict):
                err(tid, f"step {sid} tool_args must be an object")

    # ── 5. cites only reference earlier steps ─────────────────────────────
    cite_ok = True
    for s in steps:
        sid   = s.get("step_id", 0)
        cites = s.get("cites", [])
        if not isinstance(cites, list):
            err(tid, f"step {sid} cites must be an array")
            cite_ok = False
            continue
        for c in cites:
            if not isinstance(c, int):
                err(tid, f"step {sid} cite '{c}' is not an integer")
                cite_ok = False
            elif c >= sid:
                err(tid, f"step {sid} cites step {c} which is not earlier")
                cite_ok = False
    if cite_ok:
        print("  cites    : all forward-references absent OK")

    # ── 6. reasoning / final steps have stated_confidence ─────────────────
    for s in steps:
        stype = s.get("type", "")
        sid   = s.get("step_id", "?")
        if stype in ("reasoning", "final"):
            if "stated_confidence" not in s:
                warn(tid, f"step {sid} ({stype}) has no stated_confidence")

    # ── 7. Label exists and is structurally valid ──────────────────────────
    if tid not in labelled_ids:
        err(tid, "No label entry in labels.json")
    else:
        label = labels[tid]
        fus = label.get("first_unreliable_step")
        ft  = label.get("failure_type")
        sp  = label.get("split")

        # first_unreliable_step must be null or a valid step_id
        if fus is not None:
            if fus not in ids_seen:
                err(tid, f"first_unreliable_step={fus} is not a valid step_id in this trace")
            else:
                print(f"  label    : step {fus}, {ft}, split={sp} OK")
        else:
            print(f"  label    : null ({ft}), split={sp} OK")

        if ft is None:
            err(tid, "Label missing failure_type")
        if sp not in ("dev", "held_out"):
            err(tid, f"Label split='{sp}' must be 'dev' or 'held_out'")

# ---------------------------------------------------------------------------
# Check no label is orphaned (refers to a trace file that doesn't exist)
# ---------------------------------------------------------------------------
orphans = labelled_ids - found_ids
if orphans:
    for o in sorted(orphans):
        err("labels.json", f"Label entry '{o}' has no corresponding trace file")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"Traces validated : {len(found_ids)}")
print(f"Errors           : {len(errors)}")
print(f"Warnings         : {len(warnings)}")

if errors:
    print("\nFAILED — errors found:")
    for tid, msg in errors:
        print(f"  [{tid}] {msg}")
    sys.exit(1)
else:
    if warnings:
        print("\nWarnings (not failures):")
        for tid, msg in warnings:
            print(f"  [{tid}] {msg}")
    print("\nAll traces PASSED validation OK")
    sys.exit(0)
