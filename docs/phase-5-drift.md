# Phase 5 — Drift monitoring

Status: **implemented and tested.** Engine in `src/adaptive_ids/drift/`, persistence and API in
`services/drift.py` and `api/routes/drift.py`, UI under **Drift Monitor**, migration `0002`.

> A drift signal is a prompt for an analyst to review. It is **not evidence of an attack**, does not by
> itself show that the model has failed, and **never retrains, approves or activates a model**. Those steps
> go through Model Management's explicit, audited approvals. A test enforces this.

## Four signals, kept separate (spec §10)

| Signal | Question it answers | Method | Needs |
|---|---|---|---|
| **Feature drift** | Have input feature distributions changed? | Per-feature PSI (reference-quantile bins) as the effect size, gated by a two-sample KS test with Bonferroni correction across features | Features |
| **Prediction drift** | Has the model's output changed? | Class-mix PSI + chi-square; Jensen–Shannon distance; ADWIN on the 0/1 suspicious indicator in event-time order | Predictions from the chosen model |
| **Performance degradation** | Has the error rate risen? | Error rate, current vs reference, against labels supplied with the data; ADWIN on the 0/1 error indicator | Labels in both samples |
| **Suspected concept drift** | Has the input→label relationship changed? | Reported only when performance degrades **without** feature drift. It's an interpretation, not proof | Labels |

When a signal can't be assessed (no model scored the data, no labels, too few events), the analysis says
**Not assessable** or **Insufficient data** instead of returning a number.

### Rules (configurable, versioned — `DriftConfig`, defaults v1.0.0)

- **Severity:** `major` when PSI ≥ 0.25 and adjusted p < 0.01. `moderate` when PSI ≥ 0.10 and adjusted p < 0.01. Otherwise `none`.
- **Effect size gates detection.** The p-value is never used alone, because with large samples it flags trivial shifts.
- **Minimum sample:** 200 events per sample or window, and 100 labels for performance. Smaller windows are reported as `insufficient_data`, not judged.
- **Performance:** an error-rate rise of ≥ 0.02 is `moderate` and ≥ 0.05 is `major` (absolute).
- **ADWIN** (River 0.21, `delta = 0.002`) runs only on bounded 0/1 signals. Other inputs are rejected, which validates the method's assumption. A falling error rate is not raised as degradation.

All thresholds can be overridden per analysis (`config` in the request) and are stored with the analysis.

## Using it

**Run an analysis.** UI: Drift Monitor → *New analysis*. API: `POST /api/drift/analyses`. You choose:
- a reference import (and optionally a time range within it), usually data the model was validated on;
- a current import and time range;
- the model (defaults to the active one);
- windows: a fixed number of events, or hour/day/week;
- optionally, which features to include.

**Read the analysis page:**
- the four verdicts;
- PSI per window against the thresholds, on a log scale with a table view;
- error rate per window, when labels exist;
- a per-feature table with PSI, KS D, adjusted p, medians, severity and the window where drift began;
- reference-vs-current distributions per feature;
- the events raised.

**Review drift events.** Statuses: `new → acknowledged → investigating → closed`, and they can be re-opened. Closing requires a note recording the outcome, and notes and status changes form the event history. Status changes are audited.

**Export.** A Markdown report (verdicts, feature table, thresholds, events, limitations) and per-window CSV. Exports are audited.

**Dashboard.** The Drift-monitoring tile shows open drift events by type and links to the monitor.

## Controlled drift experiments (spec §15, Phase 5)

```powershell
adaptive-ids drift-experiment --repeats 5          # modes: none, sudden, gradual, concept
```

Each trial trains a model on clean SYNTHETIC data and generates a current stream with a known drift point.
It then measures, per detector, the detection rate, the delay in events after the true drift start, false
alarms before it, and the analysis overhead. Output goes to `experiments/runs/drift-experiment-*/`
(`result.json`, `report.md`).

Results from 2026-10-11 (5 repeats per mode, 500-event windows, default thresholds, CPU).
**SYNTHETIC data, so these describe the generator, not real traffic:**

| Mode | Feature windows | ADWIN on error rate | Prediction signals | False alarms (any detector) |
|---|---|---|---|---|
| No drift | — | — | — | **0** |
| Sudden feature drift | detected 5/5, delay 500 events | not triggered | not triggered | 0 |
| Gradual feature drift | detected 5/5, delay 500 events | not triggered | not triggered | 0 |
| Concept drift (labels flip, inputs unchanged) | not triggered | detected 5/5, mean delay 109 events | not triggered | 0 |

Overhead was about 65–75 µs per event for the full analysis (all windows, all 12 features and ADWIN).

**How to read these:**
- **Window delay.** Window detectors can only fire when a window completes. The drift starts on a window boundary, so the 500-event delay is exactly one window.
- **Gradual vs sudden.** Gradual drift matched sudden drift because even the first step of the synthetic ramp exceeds the PSI threshold. The generator does not yet produce slow enough ramps to separate the two.
- **Prediction drift.** It stayed quiet because the synthetic attack classes remain easy to separate after the shift. This is a property of the generator, not evidence about real models.
- **Concept drift.** It was invisible to every input- and output-based detector and was found only through labels, as expected.

## Testing

- **Engine** (`tests/test_drift_engine.py`):
  - **Statistics:** PSI and KS properties, binning of discrete features, Bonferroni correction.
  - **Detection:** nothing flagged when there's no drift; a shift is detected, along with its onset window.
  - **Separation:** concept drift is suspected only without feature drift; missing labels or predictions give "not assessable"; small windows give "insufficient data".
  - **Inputs and config:** time windows; ADWIN's bounded-input check and rate-change detection; config validation.
  - **Experiment:** an end-to-end run of the controlled experiment.
- **API** (`tests/test_drift_api.py`, also run against PostgreSQL in CI):
  - **Detection:** the drift appears in the right windows; no drift between identical data.
  - **Event lifecycle:** required closing note, notes, invalid transitions.
  - **Outputs:** reports, and the dashboard status.
  - **Validation:** bad features, bad config, bad windows, bad time ranges, missing imports.
  - **Without a model:** the analysis still runs; prediction drift and performance are reported as not assessable.
  - **Safety:** model lifecycle states are unchanged after drift is detected.
- **Web:** unit tests for drift badges and the honest "Not assessable" rendering. The UI was also checked in a real browser in light, dark and 390px widths, and an end-to-end run covered create analysis → detected → distribution → acknowledge → blocked close without a note → close.

## Limitations

- Reference and current samples are loaded into memory (limit 1,000,000 events per analysis).
- Analyses run as in-process background tasks. Continuous scheduled monitoring, such as automatically analysing each new import, is a later step.
- PSI bins come from reference quantiles. Heavily discrete features get fewer bins, and features absent from the reference cannot be binned meaningfully.
- Event-count windows follow event time. Events without timestamps are placed last.
- Performance and concept signals use labels supplied with the imported data, not analyst-confirmed outcomes.
