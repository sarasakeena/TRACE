"""
S4 — Uncertainty Proxy
======================
Detects hedging, overconfidence, and uncertainty in agent reasoning.

NOTE: This is documented as a *proxy* — not a ground-truth uncertainty measure.
It looks for linguistic cues; it does not measure model calibration.

Rules:
  U1: Excessive hedging language (may, might, possibly, perhaps, unclear, etc.)
  U2: Overconfident language without supporting evidence ("definitely", "certainly")
  U3: Self-contradiction within a single reasoning step
  U4: Confidence level mismatches tool reliability signals
"""

from __future__ import annotations

import re
from typing import Any

from .signals import SignalRecord


# ---------------------------------------------------------------------------
# Language patterns
# ---------------------------------------------------------------------------

_HEDGING_WORDS = {
    "maybe", "perhaps", "possibly", "might", "could", "may",
    "uncertain", "unclear", "unsure", "not sure", "not certain",
    "i think", "i believe", "i guess", "seems", "appears",
    "probably", "likely", "unlikely", "roughly", "approximately",
    "it seems", "it appears", "hard to say", "difficult to determine",
    "not entirely clear", "i'm not confident",
}

_OVERCONFIDENT_WORDS = {
    "definitely", "certainly", "absolutely", "clearly", "obviously",
    "undoubtedly", "without a doubt", "guaranteed", "100%", "for sure",
    "no question", "unquestionably", "indisputably",
}

_SELF_CONTRADICTION_PAIRS = [
    (r'\bis\b', r'\bis not\b'),
    (r'\bwill\b', r'\bwill not\b'),
    (r'\bcan\b', r'\bcannot\b'),
    (r'\byes\b', r'\bno\b'),
    (r'\btrue\b', r'\bfalse\b'),
    (r'\bincreased?\b', r'\bdecreased?\b'),
    (r'\bhigher\b', r'\blower\b'),
    (r'\bmore\b', r'\bless\b'),
]


def _count_hedging(text: str) -> tuple[int, list[str]]:
    """Count hedging cues in text. Returns (count, matched_phrases)."""
    text_lower = text.lower()
    matches = []
    for phrase in _HEDGING_WORDS:
        # Use word boundaries for single words, substring for phrases
        if " " in phrase:
            if phrase in text_lower:
                matches.append(phrase)
        else:
            if re.search(rf'\b{re.escape(phrase)}\b', text_lower):
                matches.append(phrase)
    return len(matches), matches


def _count_overconfidence(text: str) -> tuple[int, list[str]]:
    """Count overconfident cues in text."""
    text_lower = text.lower()
    matches = []
    for phrase in _OVERCONFIDENT_WORDS:
        if " " in phrase:
            if phrase in text_lower:
                matches.append(phrase)
        else:
            if re.search(rf'\b{re.escape(phrase)}\b', text_lower):
                matches.append(phrase)
    return len(matches), matches


def _check_self_contradiction(text: str) -> list[str]:
    """Check for self-contradictory statements within a single text."""
    text_lower = text.lower()
    contradictions = []
    sentences = re.split(r'[.!?]+', text_lower)

    for i, sent_a in enumerate(sentences):
        for sent_b in sentences[i + 1:]:
            for pat_pos, pat_neg in _SELF_CONTRADICTION_PAIRS:
                a_has_pos = bool(re.search(pat_pos, sent_a))
                b_has_neg = bool(re.search(pat_neg, sent_b))
                a_has_neg = bool(re.search(pat_neg, sent_a))
                b_has_pos = bool(re.search(pat_pos, sent_b))

                if (a_has_pos and b_has_neg) or (a_has_neg and b_has_pos):
                    contradictions.append(
                        f"'{sent_a.strip()}' vs '{sent_b.strip()}'"
                    )
                    break
    return contradictions


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

def score_uncertainty(trace: dict[str, Any]) -> list[SignalRecord]:
    """Score steps for uncertainty/hedging. Returns signals for notable steps.
    
    Note: This is a PROXY. High hedging is not necessarily wrong, and
    overconfidence is not necessarily right. The signals should be treated
    as risk indicators, not definitive failure markers.
    """
    signals: list[SignalRecord] = []
    tid = trace["trace_id"]
    steps = trace["steps"]

    # Track whether tool results provide strong support
    has_tool_support = False

    for step in steps:
        sid = step["step_id"]
        stype = step["type"]
        content = step.get("content", "")

        if stype == "tool_result":
            has_tool_support = True
            continue

        # Only evaluate reasoning and answer steps
        if stype not in ("reasoning", "answer"):
            continue

        fired = []
        reasons = []
        score = 0.0

        # --- U1: Hedging ---
        hedge_count, hedge_matches = _count_hedging(content)
        if hedge_count >= 2:
            fired.append("U1_excessive_hedging")
            reasons.append(f"Hedging language ({hedge_count}x): {', '.join(hedge_matches[:5])}")
            # Scale: 2 hedges = 0.3, 3 = 0.4, 4+ = 0.5
            score = max(score, min(0.5, 0.2 + hedge_count * 0.1))

        # --- U2: Overconfidence without evidence ---
        overconf_count, overconf_matches = _count_overconfidence(content)
        if overconf_count > 0:
            if not has_tool_support:
                fired.append("U2_overconfident_no_evidence")
                reasons.append(
                    f"Overconfident language without tool support: "
                    f"{', '.join(overconf_matches)}"
                )
                score = max(score, 0.5)
            elif stype == "answer":
                # Even with tool support, extreme overconfidence in final answer
                # when hedging was present in reasoning is suspicious
                fired.append("U2_overconfident_answer")
                reasons.append(
                    f"Overconfident language in answer: {', '.join(overconf_matches)}"
                )
                score = max(score, 0.3)

        # --- U3: Self-contradiction ---
        contradictions = _check_self_contradiction(content)
        if contradictions:
            fired.append("U3_self_contradiction")
            reasons.append(f"Self-contradictory statements: {contradictions[0]}")
            score = max(score, 0.6)

        if fired:
            signals.append(SignalRecord(
                trace_id=tid,
                step_id=sid,
                scorer="uncertainty",
                score=round(score, 3),
                fired_rules=fired,
                reason="; ".join(reasons),
                source="rule",
            ))

    return signals
