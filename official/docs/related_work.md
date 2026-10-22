# Related work (verified 22 Oct 2026)

We do not claim to be first. Step-level failure localization in agent runs is an active area.
Everything below was checked against the paper page or the authors' own blog post. We read
abstracts and summaries, not full papers.

| Work | What it does | How TRACE differs |
|---|---|---|
| **Who&When** (Zhang et al., ICML 2025, arXiv 2505.00212) | Benchmark of 184 annotated failures from 127 LLM multi-agent systems, each labelled with the responsible agent, the decisive error step and a reason. Tests LLM judges (all-at-once, step-by-step, binary search). Best method: 53.5% agent-level but only **14.2% step-level accuracy**. | Shows exact-step localization is hard even for strong LLM judges. TRACE is a cheap rule-first monitor that scores steps as they happen, rather than a post-mortem judge. |
| **AgentRx** (Microsoft Research, blog 12 Mar 2026; ICML 2026) | Finds the "critical failure step" in a trajectory. Generates executable constraints from tool schemas and domain policies, checks them step by step into an auditable violation log, then an LLM judge uses that log and a 9-category taxonomy to pick the step and root cause. 115 annotated failed trajectories (τ-bench, Flash, Magentic-One). | **Closest to us.** Same idea of auditable step-level checks. TRACE adds a privacy-leak focus (PII sent to external tools), a causal per-step score (step t sees only steps ≤ t), and an explicit comparison against a final-answer-only check. Our core needs no LLM. |
| **FALAT** (arXiv 2606.00765, Jun 2026) | Post-mortem failure attribution as a dependency-guided search: builds an expectation from the task, flags candidate steps, separates original from propagated errors, and verifies counterfactually. LLM calls at every stage. | Post-mortem and LLM-heavy. TRACE is online-capable and deterministic at its core. |
| **Traverse** ("Locating Hidden Failures Makes Long-Horizon Agents More Reliable", arXiv 2609.17930) | 2,518 real agent trajectories with human-labelled first mistakes (two annotators, κ = 0.73). Agents rarely notice or recover after a first mistake. The best of six frontier judges finds the first mistake in fewer than a third of runs; a trained 4B verifier does better. | Real, large-scale, human-labelled data. TRACE uses 13 small simulated traces, so we claim a validated prototype, not benchmark-level evidence. |
| **Observability tools** (LangSmith, Langfuse, etc.) | Record and visualise traces. | They record; TRACE scores trust per step and recommends an intervention. (General knowledge, not checked.) |

## Not verified, so not cited
TrajDebug (arXiv 2608.06346) and CodeTracer (arXiv 2604.11641) exist as paper titles, but we did
not read them. Do not describe them in the presentation unless someone reads the abstract first.

## The motivation in one line
Even strong LLM judges find the exact failing step in only 14% of runs (Who&When) to under a third
(Traverse). Step-level localization is hard and expensive, which is why TRACE puts cheap,
deterministic, explainable checks first and escalates only flagged steps.

## Sources
- Who&When: https://arxiv.org/abs/2505.00212
- AgentRx: https://microsoft.com/en-us/research/blog/systematic-debugging-for-ai-agents-introducing-the-agentrx-framework
- FALAT: https://arxiv.org/abs/2606.00765
- Traverse: https://arxiv.org/abs/2609.17930
