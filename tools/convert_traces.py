"""Convert the official TRACE traces (team schema) into the format the monitor reads.

Format only: no story, number or label is changed. Step ids shift from 1-based to 0-based
(the monitor's validator requires 0..n-1); results are shifted back when reported.

The monitor's validator requires a ground_truth block inside each trace. No scorer reads it
(checked: only schema_validator.py references ground_truth), so the answer key is never
visible to the scoring code.

Usage (from the repo root):
    python tools/convert_traces.py <official_trace_dir> <official_labels.json>
Writes:
    data/official/traces/T01..T13.json
    data/official/labels.json
    data/official/policy_compiled.yaml   (policy_rules.yaml mapped to the scorer's keys)
"""
import glob
import json
import os
import sys

FAILURE_MAP = {
    "none": None,
    "missing_verification": "evidence",
    "cross_tool_contradiction": "consistency",
    "tool_result_contradiction": "consistency",
    "policy_pii_leak": "privacy",
    "unsupported_citation": "evidence",
    "fabrication_from_empty": "hallucination",
    "final_answer_error": "consistency",
    "paraphrased_contradiction": "consistency",
    "unsupported_claim": "evidence",
}
TYPE_MAP = {"final": "answer", "retrieval": "tool_result"}


def shift(x):
    return None if x is None else x - 1


def convert(trace, lab):
    steps, tool_of = [], {}
    for s in trace["steps"]:
        new = {"step_id": s["step_id"] - 1, "type": TYPE_MAP.get(s["type"], s["type"])}
        content = s.get("content", "")
        if s["type"] == "tool_call":
            tool_of[s["step_id"]] = s["tool_name"]
            new["tool_name"] = s["tool_name"]
            new["tool_input"] = s.get("tool_args", {})
            new["content"] = content if isinstance(content, str) else json.dumps(content)
        elif s["type"] in ("tool_result", "retrieval"):
            called = [tool_of[c] for c in s.get("cites", []) if c in tool_of]
            new["tool_name"] = called[-1] if called else "unknown_tool"
            new["tool_output"] = content
            new["content"] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        else:
            new["content"] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        # A tool_result's "cites" only records which call produced it (provenance), not a claim.
        # The monitor treats citations as claims to verify, so they are kept only on
        # reasoning/answer/tool_call steps.
        if s.get("cites") and s["type"] not in ("tool_result", "retrieval"):
            new["citations"] = [c - 1 for c in s["cites"]]
        for k in ("stated_confidence", "probe_score"):
            if k in s:
                new[k] = s[k]
        steps.append(new)

    ftype = FAILURE_MAP.get(lab["failure_type"], lab["failure_type"])
    return {
        "trace_id": trace["trace_id"],
        "scenario": trace["task"],
        "category": ftype or "clean",
        "difficulty": "medium",
        "held_out": lab.get("split") == "held_out",
        "steps": steps,
        "ground_truth": {
            "first_unreliable_step": shift(lab["first_unreliable_step"]),
            "failure_type": ftype,
            "explanation": lab.get("notes", ""),
        },
    }


POLICY_COMPILED = """# Generated from rules/policy_rules.yaml into the keys policy_scorer.py reads.
# P03 (external tool + PII), P05 (allowlist) and P06 (unsourced claim) have no
# equivalent in policy_scorer.py yet; PII in any tool input is caught instead.
pii_patterns:
  email: '[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}'
  phone_in: '\\+91[\\s\\-]?[6-9]\\d{4}[\\s\\-]?\\d{5}'
  national_id_12: '\\b\\d{12}\\b'
  ssn: '\\b\\d{3}-\\d{2}-\\d{4}\\b'
forbidden_tools: [delete_database, transfer_funds]
write_tools: [order_confirm, issue_refund, send_email]
pii_field_names: [ssn, social_security, credit_card, cc_number, password, secret, api_key, token, customer_email, customer_phone]
"""


def main():
    src, labels_path = sys.argv[1], sys.argv[2]
    with open(labels_path, encoding="utf-8") as f:
        labels = json.load(f)
    out_dir = os.path.join("data", "official", "traces")
    os.makedirs(out_dir, exist_ok=True)
    new_labels = {}
    for p in sorted(glob.glob(os.path.join(src, "T*.json"))):
        with open(p, encoding="utf-8") as f:
            t = json.load(f)
        lab = labels[t["trace_id"]]
        c = convert(t, lab)
        with open(os.path.join(out_dir, t["trace_id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(c, f, indent=2, ensure_ascii=False)
        new_labels[t["trace_id"]] = {
            "first_unreliable_step": c["ground_truth"]["first_unreliable_step"],
            "failure_type": c["ground_truth"]["failure_type"],
            "held_out": c["held_out"],
        }
    with open(os.path.join("data", "official", "labels.json"), "w", encoding="utf-8") as f:
        json.dump(new_labels, f, indent=2)
    with open(os.path.join("data", "official", "policy_compiled.yaml"), "w", encoding="utf-8") as f:
        f.write(POLICY_COMPILED)
    print(f"Converted {len(new_labels)} traces into data/official/")


if __name__ == "__main__":
    main()
