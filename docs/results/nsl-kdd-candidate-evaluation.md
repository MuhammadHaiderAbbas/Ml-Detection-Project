# Candidate evaluation #2: nsl-kdd-et-official-train-model@698cd7f8ad6d

- **Verdict:** fail
- **Protocol:** v1.0.0 (`configs/evaluation-protocol.json`)
- **Candidate:** nsl-kdd-et-official-train-model@698cd7f8ad6d (controlled_experiment, status candidate)
- **Baseline:** nsl-kdd-rf-official-train-model@ac1b1ad64575 (controlled_experiment)
- **Data:** import #2 nsl-kdd-test@KDDTest+ (controlled_experiment), SHA-256 `c30eda7ab18bf7eebd0491e7bf481e8289e3c50fa24028c6f1edd18844300d6d`
- **Truth:** dataset label != 'normal' counts as attack (labels from the imported file). dataset-provided labels from the imported file; not analyst-confirmed outcomes
- **Run:** 2026-10-11T20:12:28.132339+00:00, 2.6 s

## Metrics (attack vs benign)

| Metric | Candidate | Baseline | Difference | 95 % CI of difference |
|---|---|---|---|---|
| Attack recall (detection rate) | 61.36 % | 58.05 % | +3.30 pp | [+2.97 pp, +3.67 pp] |
| False-positive rate | 4.12 % | 2.46 % | +1.66 pp | [+1.40 pp, +1.93 pp] |
| Precision | 95.17 % | 96.89 % | -1.73 pp | [-2.03 pp, -1.42 pp] |
| F1 | 74.61 % | 72.61 % | +2.01 pp | [+1.71 pp, +2.31 pp] |
| Accuracy | 76.23 % | 75.06 % | +1.17 pp | [+0.93 pp, +1.39 pp] |

Compared events: 22,544 (12,833 attack, 9,711 benign) of 22,544 labelled. Differences are candidate - baseline in percentage points (pp).

## Gates

| Gate | Kind | Result | Value | Threshold |
|---|---|---|---|---|
| labelled events scored by every compared model | validity | pass | 22,544 | 200 |
| events labelled as attacks | validity | pass | 12,833 | 30 |
| events labelled benign | validity | pass | 9,711 | 30 |
| share of labelled events the candidate could not score | validity | pass | 0.00 % | 1.00 % |
| share of labelled events the baseline could not score | validity | pass | 0.00 % | 1.00 % |
| attack recall drops by at most 1.0 pp (lower 95% bound of candidate - baseline) | performance | pass | +2.97 pp | -1.00 pp |
| F1 drops by at most 1.0 pp (lower 95% bound of candidate - baseline) | performance | pass | +1.71 pp | -1.00 pp |
| false-positive rate rises by at most 0.5 pp (upper 95% bound of candidate - baseline) | performance | fail | +1.93 pp | +0.50 pp |

## McNemar test (context only, not a gate)

Candidate right where the baseline was wrong: 504; the reverse: 241. chi-square, continuity corrected, p = 8.077e-22 (significant at 0.05).

## Limitations

- Labels come from the imported file. They are not analyst-confirmed outcomes.
- Metrics treat every non-benign label as an attack; per-class behaviour is not gated.
- The evaluation file is checked against each model's training file by hash only; overlapping rows inside a different file are not detected.
- Scores are uncalibrated; the comparison uses each model's own decision rule.
