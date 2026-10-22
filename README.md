# TRACE - Trust Risk Assessment across Chained Executions

## Project Overview
**Team**: Sara + Subhiksha | **ID**: LUMINA RA014

Step-level trust monitor that scores every step of an AI agent's reasoning–action loop (not just final output). Combines:
1. Multi-channel leak detection (reasoning, tool, retrieval)
2. Uncertainty proxy (hedging and overconfidence versus support), not the model's true internal uncertainty

### System Architecture
- **Layer 1**: rule engine (privacy patterns, forbidden tools, exact value mismatches, policy rules)
- **Layer 2 (optional)**: local LLM semantic checks, temperature 0, cached outputs, on/off switch
- **Layer 3**: TRACE monitor that merges signals and flags the first unreliable step

> *Note*: Layer 2 performs semantic checks (paraphrased contradictions and claims not supported by evidence). It does not read hidden activations; hidden-state probes are out of scope for this prototype.

## Sara's Tasks (S1–S9)

| # | Task | Done When |
|---|------|-----------|
| S1 | Repo scaffold + schema validator | All traces validate |
| S2 | Evidence scorer (rules): cited steps exist, come earlier, support the claim | Fabricated citation (T07) scores high |
| S3 | Tool-consistency scorer (rules): value mismatches, ignored errors, cross-tool conflicts | T04, T05 flagged at the right step |
| S4 | Uncertainty proxy: hedging, overconfidence versus support; document as proxy | T08 visible but not hard alert |
| S5 | Policy and privacy scorer reading Subhiksha's rules file | T06 flagged at the leaking middle step |
| S6 | Signal record + combiner + first-unreliable-step logic (causal: step t sees steps <= t) | Predicted step matches labels on dev traces |
| S7 | Layer 2: small local model (NLI classifier first), structured output, temp 0, cached JSON, on/off switch | T11 behaves differently with Layer 2 on |
| S8 | Final-answer-only baseline + evaluate.py: four systems, metrics, overlap table, ablations, sweep, fixed seed, results.json | One command reproduces every number |
| S9 | Failure analysis: every miss, false alarm, layer disagreement with reasons | At least 3 honest failures written down |

## Test Traces Reference
- **T04**: two tools return conflicting values (cross-tool contradiction)
- **T05**: the agent states the opposite of what the tool returned (tool-result consistency failure)
- **T06**: Private data leaks in tool call; final answer looks safe → Blind spot
- **T07**: Citation to a step that does not support the claim → Evidence failure
- **T08** (held out): Correct but very hedged language → Uncertainty without error
- **T09** (held out): Fails at step 1; agent invents data from empty result → Earliest possible failure
- **T10** (held out): Only the final answer is wrong → Baseline should tie or win
- **T11**: Paraphrased contradiction (tool: pending, agent: shipped) → Where rules fail, LLM helps
- **T12** (held out): Unsupported claim with no numbers to match → Semantic evidence gap
- **T13**: Consistent paraphrase → Hard negative: must NOT be flagged

## Timeline
- Phase 0 (0-0:30): Contract — freeze schema + signal record
- Phase 1 (0:30-6h): Core — S1-S6 rules pipeline on dev traces
- Phase 2 (6-12h): Hybrid — S7 local LLM layer, S8 baseline + evaluate.py
- Phase 3 (12-18h): Evaluate — S8 final runs, S9 failure analysis
- Phase 4 (18-24h): Finish — lock results, fresh-clone test

## Limitations
- Uncertainty is a proxy.
- The risk score is weighted, not calibrated.
- Rules can miss paraphrased problems; the local LLM can miss failures or raise false alarms.
- Only simulated traces; no real-time prevention of agent actions.
