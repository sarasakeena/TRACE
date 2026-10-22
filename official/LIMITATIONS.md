# Limitations and failures

We report what failed, not just what worked.

## 1. Real failures from our run
Every miss, false alarm and wrong-step flag, with TRACE's own reason next to what really happened,
is listed in **[report/RESULTS.md](report/RESULTS.md)** under "What failed". That file is generated
from the evaluation output (`python report/summarize_results.py`), so it always matches the latest run.

Patterns to read it with:
- **A right step can come with the wrong reason.** The number checks compare every number in a
  claim against every number in the cited step. Thousands separators ("12,750") and dates
  ("2026-10-25") can be read as several numbers, so a flag can land on the right step because of a
  parsing artefact rather than the real contradiction. Check each hit's reason against the truth.
- **Handled errors look like ignored errors.** In T02 the agent retries a failed tool and succeeds;
  a check that only sees "a tool failed and the agent continued" raises a false alarm.
- **Several numbers in one result.** In T08 the tool returns temperature and humidity; matching a
  claim number against the wrong field raises a false alarm.
- **Omissions are hard to see.** In T03 the agent skips a verification step. There is no wrong text
  to match, so word- and number-based checks can miss it.
- **Inventing data from an empty result** (T09) needs a check that a claim's facts appear in some
  earlier tool result.
- **T10 (only the final number is wrong)** is a case the final-answer check should be able to
  catch; if it does not, the baseline is weaker than intended.

## 2. Data
- **Small.** 13 hand-written simulated traces cannot support statistical or real-world claims. One trace moves a rate by 7–11 percentage points.
- **Semi-blind surprise test.** T08–T10 and T12 were written by the same team that designed the signals.
- **One failure per trace.** Real runs can have several compounding failures.
- **Simulated, not real.** Published work uses thousands of real trajectories with human-labelled first mistakes (Traverse: 2,518 runs).

## 3. Method
- **No meaning-level check.** The semantic layer was removed, so TRACE sees words and numbers, not meaning. A contradiction phrased without matching keywords or numbers can slip through.
- **Self-reported fields.** `cites` and `stated_confidence` are fields we invented; real agents do not emit them, so the evidence and uncertainty checks would weaken on real logs.
- **Uncertainty is a proxy** (hedging words, confidence versus support), not the model's true uncertainty.
- **`probe_score` is simulated.** The internal-state probes in our abstract need model access and are not implemented.
- **Weighted, not calibrated.** The risk score is a weighted sum with a hand-set alarm line. Because it is a weighted sum, a single serious policy hit can sit close to the alarm line.
- **Policy rules only catch what we listed.** An encoded or partial leak (base64 email, last 4 digits, PII in a URL) would be missed.
- **Format conversion.** The official traces are converted to the monitor's input format by `tools/convert_traces.py` (format only; no story, number or label changes). A tool result's "cites" only records which call produced it, so it is not passed to the monitor as a claim.

## 4. Evaluation
- **No LLM-judge baseline.** The brief forbids paid model calls. Published results suggest strong LLM judges are themselves weak at exact-step localization (14.2% step-level accuracy on Who&When).
- **Replay only.** TRACE scores recorded runs. "Pause the agent" is a suggested action, not a live intervention.

## 5. Scope versus abstract
| Abstract promise | Prototype |
|---|---|
| Multi-channel leak detection | Pattern scan across simulated reasoning, tool calls and answers |
| Uncertainty on intermediate reasoning | Documented proxy only |
| Internal-state probes | Not implemented (simulated optional field) |
| Semantic consistency checks | Prototyped, removed; future work |
| Calibrated combiner | Weighted risk score with a hand-set alarm line |
| Pauses the agent before a risky action | Replay with a causal score; no live prevention |
| K-Bench / LongFact evaluation, adversarial prompts | Out of scope |
