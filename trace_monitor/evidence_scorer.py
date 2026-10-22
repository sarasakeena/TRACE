"""
S2 — Evidence Scorer
====================
Checks whether an agent's citations actually support its claims.

Rules:
  E1: Citation references a step_id that does not exist
  E2: Citation references a step_id that comes AFTER the citing step (temporal violation)
  E3: Citation references a step that has no relevant content (empty or unrelated tool)
  E4: Cited step contradicts the claim being made (numerical or keyword mismatch)
  E5: Answer makes a strong claim with zero citations when tool results are available
"""

from __future__ import annotations

import re
from typing import Any

from .signals import SignalRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_numbers(text: str) -> list[float]:
    """Extract all numbers (including decimals, negatives, percentages) from text."""
    # Match numbers like 29.99, -3%, 4.2B, $49.99, etc.
    raw = re.findall(r'-?\$?(\d+(?:\.\d+)?)\s*%?[BMKbmk]?', text)
    nums = []
    for r in raw:
        try:
            nums.append(float(r))
        except ValueError:
            pass
    return nums


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, lowercased."""
    # Remove punctuation, split, lowercase, drop short words
    words = re.findall(r'[a-zA-Z_]+', text.lower())
    stop = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "but",
            "in", "on", "at", "to", "for", "of", "with", "that", "this", "it",
            "i", "my", "me", "we", "you", "he", "she", "they", "them", "its",
            "let", "will", "should", "can", "do", "does", "did", "has", "have",
            "been", "be", "not", "no", "from", "by", "about", "as", "so", "if"}
    return {w for w in words if len(w) > 2 and w not in stop}


# Negative sentiment / direction keywords
_POSITIVE_DIRECTION = {"increased", "grew", "rose", "higher", "up", "growth",
                        "gained", "surged", "improved", "strong", "positive",
                        "approved", "shipped", "completed", "confirmed"}
_NEGATIVE_DIRECTION = {"decreased", "declined", "fell", "lower", "down", "drop",
                        "lost", "shrunk", "worsened", "weak", "negative",
                        "pending", "denied", "rejected", "failed", "processing"}


def _directional_contradiction(claim_text: str, evidence_text: str) -> bool:
    """Check if the claim and evidence point in opposite directions."""
    claim_kw = _extract_keywords(claim_text)
    ev_kw = _extract_keywords(evidence_text)

    claim_pos = claim_kw & _POSITIVE_DIRECTION
    claim_neg = claim_kw & _NEGATIVE_DIRECTION
    ev_pos = ev_kw & _POSITIVE_DIRECTION
    ev_neg = ev_kw & _NEGATIVE_DIRECTION

    # Claim is positive but evidence is negative, or vice versa
    if claim_pos and ev_neg and not claim_neg and not ev_pos:
        return True
    if claim_neg and ev_pos and not claim_pos and not ev_neg:
        return True
    return False


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

def score_evidence(trace: dict[str, Any]) -> list[SignalRecord]:
    """Score every step for evidence quality. Returns signals for flagged steps."""
    signals: list[SignalRecord] = []
    tid = trace["trace_id"]
    steps = trace["steps"]
    step_map = {s["step_id"]: s for s in steps}

    # Find steps that have tool_results (these are the "evidence" steps)
    tool_result_ids = {s["step_id"] for s in steps if s["type"] == "tool_result"}
    has_evidence = len(tool_result_ids) > 0

    for step in steps:
        sid = step["step_id"]
        fired = []
        reasons = []
        score = 0.0

        # --- Check citations if present ---
        citations = step.get("citations", [])

        if citations:
            for cited_id in citations:
                # E1: Cited step does not exist
                if cited_id not in step_map:
                    fired.append("E1_nonexistent_citation")
                    reasons.append(f"Cites step {cited_id} which does not exist")
                    score = max(score, 0.9)
                    continue

                # E2: Cited step is not earlier
                if cited_id >= sid:
                    fired.append("E2_temporal_violation")
                    reasons.append(f"Cites step {cited_id} which is not earlier than step {sid}")
                    score = max(score, 0.8)
                    continue

                cited_step = step_map[cited_id]

                # E3: Cited step has no meaningful content
                cited_content = cited_step.get("content", "").strip()
                if len(cited_content) < 5:
                    fired.append("E3_empty_citation")
                    reasons.append(f"Cited step {cited_id} has no meaningful content")
                    score = max(score, 0.6)
                    continue

                # E4: Cited step contradicts the claim
                claim_text = step.get("content", "")

                # Check numerical contradiction
                claim_nums = _extract_numbers(claim_text)
                ev_nums = _extract_numbers(cited_content)
                if claim_nums and ev_nums:
                    # Check if any claimed number is absent from evidence
                    for cn in claim_nums:
                        if cn not in ev_nums and cn > 0:
                            # Could be a unit conversion or rounding — check nearby
                            close = any(abs(cn - en) / max(abs(en), 1e-9) < 0.05 for en in ev_nums)
                            if not close:
                                fired.append("E4_numerical_mismatch")
                                reasons.append(
                                    f"Claim mentions {cn} but cited step {cited_id} "
                                    f"has numbers {ev_nums}"
                                )
                                score = max(score, 0.7)

                # Check directional contradiction
                if _directional_contradiction(claim_text, cited_content):
                    fired.append("E4_directional_contradiction")
                    reasons.append(
                        f"Claim direction conflicts with cited step {cited_id}"
                    )
                    score = max(score, 0.85)

        # E5: Answer step with no citations when evidence exists
        if step["type"] == "answer" and has_evidence and not citations:
            # Check if the answer makes strong claims (has numbers or definitive language)
            content = step.get("content", "")
            has_numbers = bool(_extract_numbers(content))
            strong_words = {"definitely", "certainly", "confirmed", "exactly",
                           "precisely", "absolutely", "clearly", "shows"}
            has_strong = bool(_extract_keywords(content) & strong_words)

            if has_numbers or has_strong:
                fired.append("E5_unsourced_strong_claim")
                reasons.append("Answer makes strong claims without citing evidence steps")
                score = max(score, 0.4)  # lower weight — it's suspicious, not definitive

        if fired:
            signals.append(SignalRecord(
                trace_id=tid,
                step_id=sid,
                scorer="evidence",
                score=round(score, 3),
                fired_rules=fired,
                reason="; ".join(reasons),
                source="rule",
            ))

    return signals
