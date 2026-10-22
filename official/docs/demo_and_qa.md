# TRACE: 90-second demo and Q&A prep

Numbers in [brackets] come from `report/RESULTS.md` after the final run. Read them off that file;
never quote a number from memory.

## Demo script (90 seconds), dashboard open: `report/trace_dashboard.html`

**0:00 – The problem (15 s)** *(Play tab, run 1 = T06)*
"AI agents work in steps: think, call a tool, read the result, answer. Today we mostly check only
the final answer. But an agent can go wrong in the middle and still give an answer that looks fine."

**0:15 – Play it (30 s)**
"Here the agent summarises a support ticket. Which step would you stop trusting?" *(let the judge
pick, or tap step 4, then Lock in)* "Step 4 sends the customer's email and phone number to an
outside translation tool. The final answer is clean, so the final-answer check passes it. TRACE
flags step 4, names the rule, and suggests pausing for a person."

**0:45 – How it works (15 s)** *(Explore tab → ▶ Replay step by step)*
"Every step is scored on four questions: backed by proof, matches the tools, too sure of itself,
breaks a rule. Step 4 is judged only on steps 1 to 4, so this could run live. The replay stops at
the first step over the alarm line."

**1:00 – Honest results (30 s)** *(Scoreboard tab)*
"On 13 test runs TRACE found the exact bad step in [X of 9] problem runs; the final-answer check in
[Y of 9]. It also fails: [N] false alarms on [4] correct runs, and it misses [T03 and T09]. Every
failure is on screen with TRACE's own reason next to what really happened."

## The three questions (also on the "Judges' questions" tab)

**"What failed?"**
Read the "What failed" list in `report/RESULTS.md` with trace IDs. Then the patterns:
- a right step can come with the wrong reason (number parsing of "12,750" and dates);
- a handled tool error (T02) looks like an ignored one;
- omissions (T03) and data invented from an empty result (T09) have nothing to match;
- 13 hand-written runs can't support statistics, and the surprise test was written by our own team.

**"What baseline did you use?"**
"The same checks on the final answer only, so the only difference is every step versus the last
answer. Note: published work shows even strong LLM judges find the exact failing step in only 14%
of runs on Who&When; we couldn't add a paid LLM judge because the brief forbids paid calls."

**"What evidence would change your conclusion?"**
"We wrote these before the surprise test:
- the final-answer check localizing within one step on most problem runs;
- catching T06 needing an alarm line that flags most correct runs;
- one check explaining every catch, which the ablation table tests;
- traces from outside our team, or real agent logs, behaving differently."

## Likely follow-ups

| Question | Answer |
|---|---|
| Where's the AI in this? | "We prototyped a semantic layer but removed it: it wasn't a real model yet. We'd rather show a smaller honest system than a fake one. It's future work, for paraphrases like 'pending' vs 'on its way'." |
| Is this better than an LLM judge? | "Not at understanding meaning. It's cheap, deterministic, explainable, and can't be talked out of a rule by injected text. It's the always-on first layer; flagged steps go to a person or an expensive judge." |
| Isn't this already done? (AgentRx) | "AgentRx is closest: constraint checks plus an LLM judge, after the fact. We add a privacy-leak focus, a per-step score that only looks backwards so it could run live, and an explicit final-answer comparison. We don't claim to be first." |
| You wrote the tests and the checker. Circular? | "Partly. Labels were locked before any scorer ran, the trace writer didn't see the scorer code, and four runs were held out. Still semi-blind, and we say so." |
| The reason on T05 / T11 looks odd. | "Yes: it hit the right step but for a parsing reason, not the real contradiction. That's why we show the reason next to the truth instead of only counting hits." |
| What does the ablation show? | Read it from RESULTS.md. If removing a check changes nothing, say so: that check isn't doing work on this data. |
| Real agents don't output `cites` or confidence. | "True. Those checks would weaken on real logs; it's in our limitations." |
| What if the agent recovers? | "The flag stays on the first bad step and the alert notes the recovery." |
| Why only 13 traces? | "The brief asked for 5–10. We covered each failure type rather than volume; real logs are next." |

## Words to use
- **"step-level localization"**, not "level".
- **"weighted risk score"**, not "calibrated" or "probability".
- **"simulated replay"** and **"suggested action"**, never "firewall", "intercepted" or "blocked live".
- **"validated prototype on simulated traces"**, not "proven" or "production".
