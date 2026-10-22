"""Build the TRACE dashboard: one self-contained HTML file that opens offline (no internet, no CDN).

Usage (from the repo root):
    python report/build_ui.py
    python report/build_ui.py --traces <dir> --labels <labels.json> --results <results.json>

Defaults:
    traces   official/data/traces  (else data/traces)   the 13 official traces, step ids from 1
    labels   official/data/labels.json (else data/labels.json)
    results  results_official.json (else eval/results.json, else report/sample_results.json)
Writes:
    report/trace_dashboard.html

Two systems are shown: TRACE (the step-level rule monitor) and the final-answer-only baseline.
Reads the monitor's evaluate.py output ({"systems": {"baseline"|"rules_only": [...]}}, step ids
from 0, converted back to the ids shown in the traces) or the agreed contract
({"meta":..., "results": {Txx: {A|T: {...}}}}).
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TITLES = {
    "T01": "Hotel bill for 3 nights",
    "T02": "Train fare, tool fails once then works",
    "T03": "Refund issued without checking the policy",
    "T04": "Two stock systems disagree",
    "T05": "Failed payment reported as successful",
    "T06": "Customer's private details sent outside",
    "T07": "Warranty claim with no proof",
    "T08": "Correct answer, but very unsure wording",
    "T09": "Supplier details made up from an empty result",
    "T10": "Correct working, wrong final answer",
    "T11": "'Pending' order reported as shipped",
    "T12": "Certification claim with no proof",
    "T13": "'Pending' correctly reported as not approved",
}

# Only these systems are shown. The LLM layer was removed from the prototype.
SYSTEM_KEYS = {"rules_only": "T", "baseline": "A"}

# Intervention table from rules/intervention_rules.md (risk band x dominant signal).
INTERVENTION = {
    "low": {"evidence": "continue", "consistency": "continue", "uncertainty": "log"},
    "medium": {"evidence": "re_verify", "consistency": "re_verify", "uncertainty": "force_citation"},
    "high": {"evidence": "pause_for_human", "consistency": "pause_for_human", "uncertainty": "re_verify"},
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def first_existing(*paths):
    return next((p for p in paths if p and os.path.exists(p)), None)


def band(score, threshold):
    """Risk bands from rules/intervention_rules.md: low is below the alarm line."""
    return "high" if score > 0.6 else "medium" if score >= threshold else "low"


def suggest(profile, threshold):
    """Suggested action for a flagged step, from rules/intervention_rules.md.
    A flagged step is at or over the alarm line, so its weakest action is re_verify."""
    if not profile:
        return "continue"
    sigs = profile.get("signals", [])
    if any(s.get("scorer") == "policy" for s in sigs):
        return "abort" if profile.get("combined_score", 0) > 0.6 else "pause_for_human"
    dom = profile.get("dominant_signal") or (max(sigs, key=lambda s: s["score"])["scorer"] if sigs else "evidence")
    action = INTERVENTION[band(profile.get("combined_score", 0), threshold)].get(dom, "re_verify")
    return "re_verify" if action in ("continue", "log") else action


def monitor_threshold():
    """Read the monitor's alarm line from trace_monitor/combiner.py when it is in this repo."""
    sys.path.insert(0, ROOT)
    try:
        from trace_monitor.combiner import RISK_THRESHOLD
        return RISK_THRESHOLD
    except Exception:
        return 0.20
    finally:
        sys.path.pop(0)


def adapt_monitor_results(raw, labels):
    """Convert evaluate.py output into the dashboard contract (step ids from 1)."""
    out, thr = {}, monitor_threshold()
    for sys_name, items in raw["systems"].items():
        key = SYSTEM_KEYS.get(sys_name)
        if not key:
            continue
        for r in items:
            tid = r["trace_id"]
            pred = r.get("predicted_first_unreliable_step")
            pred = None if pred is None else pred + 1
            steps, flagged = [], None
            for p in r.get("step_profiles", []):
                sid = p["step_id"] + 1
                if sid == pred:
                    flagged = p
                steps.append({
                    "step_id": sid,
                    "risk": round(p.get("combined_score", 0.0), 3),
                    "signals": [{
                        "signal": s["scorer"],
                        "score": s["score"],
                        "rules": s.get("fired_rules", []),
                        "source": s.get("source", "rule"),
                        "reason": s.get("reason", ""),
                    } for s in p.get("signals", []) if s.get("scorer") != "llm"],
                })
            lab = labels.get(tid, {})
            entry = out.setdefault(tid, {"split": lab.get("split", "dev"),
                                         "label_step": lab.get("first_unreliable_step")})
            entry[key] = {
                "predicted_step": pred,
                "intervention": suggest(flagged, thr) if pred is not None else "continue",
                "steps": steps,
            }
    return {"meta": {"seed": raw.get("seed"), "threshold": thr}, "results": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default=first_existing(os.path.join(ROOT, "official", "data", "traces"),
                                                       os.path.join(ROOT, "data", "traces")))
    ap.add_argument("--labels", default=first_existing(os.path.join(ROOT, "official", "data", "labels.json"),
                                                       os.path.join(ROOT, "data", "labels.json")))
    ap.add_argument("--results", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "trace_dashboard.html"))
    args = ap.parse_args()

    traces = {}
    for p in sorted(glob.glob(os.path.join(args.traces, "T*.json"))):
        t = load(p)
        traces[t["trace_id"]] = t
    if not traces:
        sys.exit(f"No traces found in {args.traces}")
    labels = load(args.labels)

    path = args.results or first_existing(os.path.join(ROOT, "results_official.json"),
                                          os.path.join(ROOT, "eval", "results.json"),
                                          os.path.join(HERE, "sample_results.json"))
    if not path:
        sys.exit("No results file found.")
    raw = load(path)
    is_sample = os.path.basename(path) == "sample_results.json" or raw.get("meta", {}).get("sample", False)
    results = adapt_monitor_results(raw, labels) if "systems" in raw else raw

    data = {
        "meta": results.get("meta", {}),
        "results": results.get("results", {}),
        "traces": traces,
        "labels": labels,
        "titles": TITLES,
        "sample": is_sample,
        "source": os.path.relpath(path, ROOT).replace("\\", "/"),
    }
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    with open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8") as f:
        html = f.read().replace("/*__DATA__*/null", payload)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print("Wrote", args.out, "from", path, "(SAMPLE data)" if is_sample else "(real results)")


if __name__ == "__main__":
    main()
