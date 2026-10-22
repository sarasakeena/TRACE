"""
S7 — Layer 2: Local LLM (Optional)
====================================
Wraps a small local model (NLI classifier or instruction-tuned LLM)
for semantic consistency checks that rules can't catch.

Key design decisions:
  - ON/OFF switch: can be disabled entirely (rules-only mode)
  - Temperature 0: deterministic outputs
  - Cached JSON: all outputs saved to disk, reproducible from cache
  - Structured output: returns JSON with evidence span and score
  - Only adds flags — NEVER clears rule violations

This layer is designed for cases like T11 (paraphrased contradictions)
where "pending" → "approved" is a semantic mismatch that string rules miss.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from .signals import SignalRecord


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_DIR = Path("data/llm_cache")


def _cache_key(prompt: str) -> str:
    """Generate a cache key from the prompt."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _load_cached(key: str) -> dict | None:
    """Load a cached LLM response."""
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_cache(key: str, response: dict) -> None:
    """Save an LLM response to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(response, f, indent=2)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_nli_prompt(tool_output: str, agent_claim: str) -> str:
    """Build a natural language inference prompt to check consistency."""
    return (
        "You are a consistency checker. Given a PREMISE (tool output) and a "
        "HYPOTHESIS (agent claim), determine if the hypothesis is:\n"
        "- ENTAILMENT: the premise supports the hypothesis\n"
        "- CONTRADICTION: the premise contradicts the hypothesis\n"
        "- NEUTRAL: cannot determine\n\n"
        f"PREMISE: {tool_output}\n\n"
        f"HYPOTHESIS: {agent_claim}\n\n"
        "Respond in JSON format:\n"
        '{"label": "ENTAILMENT|CONTRADICTION|NEUTRAL", '
        '"confidence": 0.0-1.0, '
        '"evidence_span": "the specific part of the premise relevant", '
        '"reason": "brief explanation"}'
    )


# ---------------------------------------------------------------------------
# LLM Backend (pluggable)
# ---------------------------------------------------------------------------

class LLMBackend:
    """Base class for LLM backends. Override `generate` for your model."""

    model_name: str = "none"

    def generate(self, prompt: str) -> str:
        """Generate a response. Returns raw text."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Check if the model is available."""
        return False


class MockLLMBackend(LLMBackend):
    """
    Mock backend for testing. Uses simple heuristics to simulate NLI.
    In production, replace with a real local model (e.g., DeBERTa-v3-base-mnli).
    """

    model_name = "mock-nli-v1"

    def generate(self, prompt: str) -> str:
        """Simple keyword-based mock for testing the pipeline."""
        prompt_lower = prompt.lower()

        # Extract premise and hypothesis
        premise_start = prompt_lower.find("premise:") + len("premise:")
        hypothesis_start = prompt_lower.find("hypothesis:") + len("hypothesis:")
        premise_end = prompt_lower.find("hypothesis:")
        hypothesis_end = prompt_lower.find("respond in json")

        if hypothesis_end < 0:
            hypothesis_end = len(prompt_lower)

        premise = prompt_lower[premise_start:premise_end].strip()
        hypothesis = prompt_lower[hypothesis_start:hypothesis_end].strip()

        # Simple contradiction detection
        contradiction_pairs = [
            ("pending", "approved"), ("pending", "shipped"),
            ("pending", "completed"), ("pending_review", "approved"),
            ("denied", "approved"), ("failed", "success"),
            ("down", "increased"), ("declined", "grew"),
            ("not_assigned", "assigned"),
        ]

        for word_a, word_b in contradiction_pairs:
            if word_a in premise and word_b in hypothesis:
                return json.dumps({
                    "label": "CONTRADICTION",
                    "confidence": 0.85,
                    "evidence_span": f"premise contains '{word_a}' but hypothesis says '{word_b}'",
                    "reason": f"Status mismatch: '{word_a}' vs '{word_b}'"
                })
            if word_b in premise and word_a in hypothesis:
                return json.dumps({
                    "label": "CONTRADICTION",
                    "confidence": 0.85,
                    "evidence_span": f"premise contains '{word_b}' but hypothesis says '{word_a}'",
                    "reason": f"Status mismatch: '{word_b}' vs '{word_a}'"
                })

        # Default to entailment if no contradiction found
        return json.dumps({
            "label": "ENTAILMENT",
            "confidence": 0.7,
            "evidence_span": "no contradiction detected",
            "reason": "Hypothesis appears consistent with premise"
        })

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Try to load a real NLI model via transformers
# ---------------------------------------------------------------------------

class TransformersNLIBackend(LLMBackend):
    """Uses HuggingFace transformers with a DeBERTa NLI model."""

    model_name = "cross-encoder/nli-deberta-v3-base"

    def __init__(self):
        self._pipeline = None

    def _load(self):
        if self._pipeline is not None:
            return
        try:
            from transformers import pipeline
            self._pipeline = pipeline(
                "zero-shot-classification",
                model=self.model_name,
                device=-1,  # CPU
            )
        except (ImportError, Exception):
            self._pipeline = None

    def generate(self, prompt: str) -> str:
        self._load()
        if self._pipeline is None:
            return json.dumps({
                "label": "NEUTRAL",
                "confidence": 0.0,
                "evidence_span": "",
                "reason": "Model not available"
            })

        # Extract premise and hypothesis
        prompt_lower = prompt.lower()
        premise_start = prompt_lower.find("premise:") + len("premise:")
        hypothesis_start = prompt_lower.find("hypothesis:") + len("hypothesis:")
        premise_end = prompt_lower.find("hypothesis:")
        hypothesis_end = prompt_lower.find("respond in json")
        if hypothesis_end < 0:
            hypothesis_end = len(prompt_lower)

        premise = prompt[premise_start:premise_end].strip()
        hypothesis = prompt[hypothesis_start:hypothesis_end].strip()

        result = self._pipeline(
            hypothesis,
            candidate_labels=["entailment", "contradiction", "neutral"],
            hypothesis_template="{}",
            multi_label=False,
        )

        label = result["labels"][0].upper()
        confidence = result["scores"][0]

        return json.dumps({
            "label": label,
            "confidence": round(confidence, 3),
            "evidence_span": premise[:200],
            "reason": f"NLI model classified as {label}"
        })

    def is_available(self) -> bool:
        try:
            import transformers
            return True
        except ImportError:
            return False


# ---------------------------------------------------------------------------
# Layer 2 Scorer
# ---------------------------------------------------------------------------

def score_llm(
    trace: dict[str, Any],
    enabled: bool = True,
    backend: LLMBackend | None = None,
    use_cache: bool = True,
) -> list[SignalRecord]:
    """
    Use a local LLM to check semantic consistency between tool outputs and
    agent claims. Returns signals for steps where the LLM detects issues.

    Args:
        trace: The trace dict
        enabled: If False, returns empty list (rules-only mode)
        backend: LLM backend to use. Defaults to MockLLMBackend.
        use_cache: If True, cache and reuse LLM outputs.
    """
    if not enabled:
        return []

    if backend is None:
        # Try transformers first, fall back to mock
        tfm = TransformersNLIBackend()
        if tfm.is_available():
            backend = tfm
        else:
            backend = MockLLMBackend()

    signals: list[SignalRecord] = []
    tid = trace["trace_id"]
    steps = trace["steps"]

    # Collect tool results
    tool_results: list[dict[str, Any]] = []

    for step in steps:
        sid = step["step_id"]
        stype = step["type"]

        if stype == "tool_result":
            tool_results.append(step)
            continue

        if stype not in ("reasoning", "answer"):
            continue

        if not tool_results:
            continue

        # Check each tool result against this step's content
        for tr in tool_results:
            tr_content = tr.get("content", "")
            tr_output = tr.get("tool_output", {})
            tool_text = tr_content
            if isinstance(tr_output, dict):
                tool_text += " " + json.dumps(tr_output)

            agent_text = step.get("content", "")

            # Build prompt
            prompt = _build_nli_prompt(tool_text, agent_text)

            # Check cache
            key = _cache_key(prompt)
            cached = _load_cached(key) if use_cache else None

            if cached:
                result = cached
            else:
                try:
                    raw = backend.generate(prompt)
                    result = json.loads(raw)
                except (json.JSONDecodeError, Exception) as e:
                    result = {
                        "label": "NEUTRAL",
                        "confidence": 0.0,
                        "evidence_span": "",
                        "reason": f"LLM error: {e}"
                    }

                if use_cache:
                    # Include metadata in cache
                    result["_meta"] = {
                        "model": backend.model_name,
                        "trace_id": tid,
                        "step_id": sid,
                        "tool_step_id": tr["step_id"],
                    }
                    _save_cache(key, result)

            # Process result
            label = result.get("label", "NEUTRAL")
            confidence = result.get("confidence", 0.0)

            if label == "CONTRADICTION" and confidence > 0.5:
                signals.append(SignalRecord(
                    trace_id=tid,
                    step_id=sid,
                    scorer="llm",
                    score=round(min(confidence, 0.95), 3),
                    fired_rules=[f"LLM_NLI_contradiction_{backend.model_name}"],
                    reason=(
                        f"LLM detected contradiction between tool step "
                        f"{tr['step_id']} and step {sid}: "
                        f"{result.get('reason', 'no reason given')}"
                    ),
                    source="llm",
                ))

    return signals
