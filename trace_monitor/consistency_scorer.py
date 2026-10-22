"""
S3 — Tool-Consistency Scorer
=============================
Detects mismatches between tool outputs and what the agent says.

Rules:
  C1: Numerical value in tool_output differs from value in subsequent reasoning/answer
  C2: Status/keyword in tool_output contradicts agent's claim (e.g., "shipped" vs "processing")
  C3: Tool returned an error/empty result but agent proceeds as if it succeeded
  C4: Agent references data that does not appear in any preceding tool_result
  C5: Cross-tool conflict: two tool results contradict each other (agent should note this)
"""

from __future__ import annotations

import re
import json
from typing import Any

from .signals import SignalRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_all_numbers(text: str) -> list[float]:
    """Extract all numbers from text, handling currency, percentages, etc."""
    raw = re.findall(r'-?\$?([\d,]+(?:\.\d+)?)\s*%?', text)
    nums = []
    for r in raw:
        try:
            nums.append(float(r.replace(',', '')))
        except ValueError:
            pass
    return nums


def _flatten_json_values(obj: Any) -> list[str]:
    """Recursively extract all string and numeric values from a JSON object."""
    values = []
    if isinstance(obj, dict):
        for v in obj.values():
            values.extend(_flatten_json_values(v))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_flatten_json_values(item))
    elif isinstance(obj, (int, float)):
        values.append(str(obj))
    elif isinstance(obj, str):
        values.append(obj)
    return values


def _extract_status_keywords(text: str) -> set[str]:
    """Extract status-related keywords from text, with negation awareness.
    
    When a positive status word (e.g., "approved") is preceded by a negation
    ("not", "hasn't", "has not", "not been"), it maps to the negative group
    instead. This prevents "has not been approved" from being treated the
    same as "approved".
    """
    text_lower = text.lower()
    status_words = set()

    # Negation patterns to look for before a keyword
    _NEGATION_PREFIXES = [
        "not ", "not been ", "hasn't ", "hasn't been ", "has not ", "has not been ",
        "wasn't ", "was not ", "isn't ", "is not ", "never ", "no longer ",
        "yet to be ", "not yet ", "still not ",
    ]

    # Positive status words and their negated equivalents
    _POSITIVE_STATUS = {
        "shipped": "not yet shipped",
        "delivered": "not yet shipped",
        "completed": "pending",
        "approved": "pending",
        "confirmed": "pending",
        "accepted": "pending",
        "resolved": "pending",
        "processed": "processing",
    }

    # Multi-word phrases (check these first, they take priority)
    multi_word_phrases = [
        "not yet shipped", "not shipped", "hasn't shipped", "has not shipped",
        "being processed", "still being processed", "not yet",
        "not been approved", "has not been approved", "not approved",
        "in stock", "out of stock", "in_stock", "out_of_stock",
    ]
    for phrase in multi_word_phrases:
        if phrase in text_lower:
            status_words.add(phrase)

    # Single-word status vocab
    single_words = {
        "shipped", "delivered", "completed", "approved", "confirmed",
        "active", "enabled", "success", "found", "available",
        "pending", "processing", "waiting", "queued", "pending_review",
        "denied", "rejected", "failed", "error", "not_found", "unavailable",
        "cancelled", "canceled",
    }

    for word in single_words:
        if word not in text_lower:
            continue

        # Check if this word is negated
        is_negated = False
        word_pos = text_lower.find(word)
        while word_pos >= 0:
            # Look at the text before this occurrence
            prefix = text_lower[max(0, word_pos - 30):word_pos]
            if any(prefix.rstrip().endswith(neg.rstrip()) for neg in _NEGATION_PREFIXES):
                is_negated = True
                break
            # Find next occurrence
            next_pos = text_lower.find(word, word_pos + 1)
            if next_pos == word_pos:
                break
            word_pos = next_pos

        if is_negated and word in _POSITIVE_STATUS:
            # Map negated positive to its negative equivalent
            status_words.add(_POSITIVE_STATUS[word])
        else:
            status_words.add(word)

    return status_words


# Contradictory status pairs
_CONTRADICTIONS: list[tuple[set[str], set[str]]] = [
    ({"shipped", "delivered"}, {"pending", "processing", "waiting", "queued",
                                 "not yet shipped", "not shipped",
                                 "hasn't shipped", "has not shipped",
                                 "being processed", "still being processed"}),
    ({"approved", "confirmed", "accepted"}, {"pending", "pending_review", "denied", "rejected"}),
    ({"completed", "resolved"}, {"pending", "processing", "waiting", "queued"}),
    ({"available", "in_stock", "in stock"}, {"unavailable", "out_of_stock", "out of stock"}),
    ({"success", "found"}, {"error", "not_found", "failed"}),
    ({"active", "enabled"}, {"cancelled", "canceled"}),
]


def _status_contradicts(tool_status: set[str], agent_status: set[str]) -> str | None:
    """Check if tool and agent status keywords are contradictory.
    Returns a reason string or None."""
    for group_a, group_b in _CONTRADICTIONS:
        if (tool_status & group_a) and (agent_status & group_b):
            return (
                f"Tool says {tool_status & group_a} "
                f"but agent says {agent_status & group_b}"
            )
        if (tool_status & group_b) and (agent_status & group_a):
            return (
                f"Tool says {tool_status & group_b} "
                f"but agent says {agent_status & group_a}"
            )
    return None


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

def score_consistency(trace: dict[str, Any]) -> list[SignalRecord]:
    """Score every step for tool–agent consistency. Returns signals for flagged steps."""
    signals: list[SignalRecord] = []
    tid = trace["trace_id"]
    steps = trace["steps"]

    # Collect all tool results seen so far (causal: step t sees steps <= t)
    tool_results: list[dict[str, Any]] = []

    for step in steps:
        sid = step["step_id"]
        stype = step["type"]

        # Accumulate tool results
        if stype == "tool_result":
            tool_results.append(step)
            continue

        # Only check reasoning and answer steps for consistency
        if stype not in ("reasoning", "answer"):
            continue

        if not tool_results:
            continue  # nothing to compare against yet

        fired = []
        reasons = []
        score = 0.0
        content = step.get("content", "")

        for tr in tool_results:
            tr_content = tr.get("content", "")
            tr_output = tr.get("tool_output", {})
            tool_name = tr.get("tool_name", "unknown")
            tr_sid = tr["step_id"]

            # --- C1: Numerical mismatch ---
            # Extract numbers from tool output (both content string and structured output)
            tool_nums = set(_extract_all_numbers(tr_content))
            if isinstance(tr_output, dict):
                for val_str in _flatten_json_values(tr_output):
                    tool_nums.update(_extract_all_numbers(str(val_str)))

            agent_nums = set(_extract_all_numbers(content))

            if tool_nums and agent_nums:
                # Filter out likely IDs and dates (large integers, years)
                def _is_likely_id_or_date(n: float) -> bool:
                    """Heuristic: skip numbers that look like IDs, dates, or reference numbers."""
                    if n != int(n):
                        return False  # has decimal → probably a quantity
                    n_int = int(n)
                    # Year-like
                    if 1900 <= n_int <= 2100:
                        return True
                    # Large integer with no decimal → likely an ID/reference
                    if n_int >= 1000 and n == float(n_int):
                        return True
                    return False

                quantity_tool_nums = {n for n in tool_nums if not _is_likely_id_or_date(n)}
                quantity_agent_nums = {n for n in agent_nums if not _is_likely_id_or_date(n)}

                # Find numbers the agent mentions that contradict tool numbers
                for anum in quantity_agent_nums:
                    if anum == 0:
                        continue  # skip zero, too common
                    # Check if there's a corresponding tool number that's different
                    for tnum in quantity_tool_nums:
                        if tnum == 0:
                            continue
                        # Same order of magnitude but different value → likely mismatch
                        ratio = anum / tnum if tnum != 0 else float('inf')
                        if 0.1 < ratio < 10 and abs(anum - tnum) > 0.01 and ratio != 1.0:
                            fired.append("C1_numerical_mismatch")
                            reasons.append(
                                f"Tool '{tool_name}' (step {tr_sid}) has {tnum} "
                                f"but agent says {anum}"
                            )
                            score = max(score, 0.85)
                            break  # one mismatch per tool result is enough

            # --- C2: Status keyword contradiction ---
            tool_status = _extract_status_keywords(tr_content)
            if isinstance(tr_output, dict):
                for v in _flatten_json_values(tr_output):
                    tool_status.update(_extract_status_keywords(str(v)))

            agent_status = _extract_status_keywords(content)

            if tool_status and agent_status:
                contradiction = _status_contradicts(tool_status, agent_status)
                if contradiction:
                    fired.append("C2_status_contradiction")
                    reasons.append(f"Step {tr_sid} ({tool_name}): {contradiction}")
                    score = max(score, 0.9)

            # --- C3: Tool error but agent proceeds ---
            tool_output_str = json.dumps(tr_output) if isinstance(tr_output, dict) else str(tr_output)
            error_indicators = {"error", "not_found", "failed", "exception", "null", "none", "empty"}
            tool_text_lower = (tr_content + " " + tool_output_str).lower()

            tool_had_error = any(ind in tool_text_lower for ind in error_indicators)
            if tool_had_error:
                # Check if the agent acknowledges the error
                agent_lower = content.lower()
                acknowledges = any(w in agent_lower for w in
                                   {"error", "failed", "not found", "couldn't", "unable",
                                    "no results", "empty", "issue", "problem"})
                if not acknowledges:
                    fired.append("C3_ignored_error")
                    reasons.append(
                        f"Tool '{tool_name}' (step {tr_sid}) returned an error/empty "
                        f"but agent proceeds as if successful"
                    )
                    score = max(score, 0.75)

        if fired:
            signals.append(SignalRecord(
                trace_id=tid,
                step_id=sid,
                scorer="consistency",
                score=round(score, 3),
                fired_rules=fired,
                reason="; ".join(reasons),
                source="rule",
            ))

    return signals
