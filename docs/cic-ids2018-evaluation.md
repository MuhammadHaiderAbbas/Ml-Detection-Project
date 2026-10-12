# CSE-CIC-IDS2018: chronological evaluation

Status: **measured on 9 of the dataset's 10 capture days.**

- **Provenance:** `controlled_experiment`, on public data.
- **Cost:** none. The data came from the dataset's official public download, and every step ran on one 4-core
  machine.
- **Raw output:**
  - [`results/cic-ids2018-chronological.md`](results/cic-ids2018-chronological.md) and its `.json`;
  - without the port and protocol features: [`results/cic-ids2018-chronological-no-port.md`](results/cic-ids2018-chronological-no-port.md) and its `.json`.

> **The question:** does a model keep working as traffic and attacks change, and does Adaptive IDS's update
> rule help or hurt?
>
> **The answer on this dataset:**
> - Once the first capture day is over, a model trained on that day detects almost nothing.
> - Adapting helps only where an attack type comes back after its labels are available.
> - No strategy detected an attack type on the day it first appeared.
> - The governance gate blocked three updates that would have traded small detection gains for higher
>   false-positive rates.

## Why this test

A random train/test split of one file, as in the MSc notebook, mixes the same traffic into both sides. It gives
near-perfect numbers: a model trained on 14 Feb scores **99.99 % accuracy** on a random split of 14 Feb
(`configs/experiments/cic-ids2018-rf.json`). Here, models only ever predict days they have never seen, in
calendar order. Each CSE-CIC-IDS2018 day introduces new attack types, so this is a hard and realistic test.

## Set-up

| | |
|---|---|
| Data | "Processed Traffic Data for ML Algorithms" (CICFlowMeter): Wednesday 14 Feb to Friday 2 Mar 2018, except Tuesday 20 Feb (4 GB). SHA-256 of every file is in the JSON |
| Schema | [`cse-cic-ids2018@1.0.0`](../configs/schemas/cse-cic-ids2018.json): 78 flow features, checked against the real headers |
| Sampling | Per day, up to 60,000 benign rows and 20,000 rows per attack class (seed 0) |
| Model | Random Forest, 100 trees, binary attack vs benign. Training sets are capped at 400,000 rows |
| **Static** | Trained once on 14 Feb |
| **Retrain-always** | Before each test day, retrained on every earlier day |
| **Governed** | Adaptive IDS's rule: after a day's labels arrive, train a candidate on 70 % of that day plus all earlier days. Compare it with the active model on the other 30 % under the platform's [evaluation protocol](../configs/evaluation-protocol.json) (paired bootstrap; recall and F1 may drop at most 1 pp, the false-positive rate may rise at most 0.5 pp). Promote it only on `pass` |
| Test | Every sampled event of each later day, identical for all three strategies |

## Data quality: what the files actually contain

- **Truncated files.** 7 of the 9 files have exactly **1,048,575** data rows, Excel's row limit, and most
  days' records stop at about 12:59 (21 Feb at 10:43). The processed CSVs were very likely cut off when saved, so later parts of
  those days are missing.
- **Defective rows.**
  - Repeated header rows: 59 in total.
  - Rows with infinite values: 36,307.
  - Rows with corrupt timestamps (1970 dates): 14.

  The loader rejects all of these and counts them.
- **Duplicates.** 14 Feb has 225,625 exact duplicate rows (21 %); 16 Feb has 147,586.
- **Identical "different" attacks.** The 139,890 `DoS attacks-SlowHTTPTest` rows on 16 Feb contain only **55
  distinct flows**, all to port 21. 55 % of them are byte-for-byte identical to `FTP-BruteForce` rows from 14 Feb.
  The static model's 100 % recall on SlowHTTPTest is therefore an artefact of the data, not generalisation.
- **Benign traffic changes sharply.** Compared with 14 Feb, benign traffic on 16 and 21 Feb shows major drift
  on 64–65 of 78 features (PSI up to 11). For example, in a 1-in-40 slice of the two files, 99.7 % of benign flows on
  16 Feb have `Fwd Seg Size Min` = 32, against 0.3 % on 14 Feb.
- **Missing context.** These files have no IP addresses, so alerts carry no source or destination.

## Results

Attack recall and false-positive rate (FPR) on each test day (all ports and protocols kept):

| Day | New attack types that day | Static | Retrain-always | Governed |
|---|---|---|---|---|
| 15 Feb | GoldenEye, Slowloris | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % |
| 16 Feb | Hulk, SlowHTTPTest | 50.0 % / 0.0 % | 99.5 % / 0.2 % | 99.5 % / 0.0 % |
| 21 Feb | HOIC, LOIC-UDP | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % |
| 22 Feb | Web brute force, XSS, SQL injection | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % |
| 23 Feb | — (web attacks again) | 0.2 % / 0.0 % | 60.8 % / 0.0 % | 56.0 % / 0.0 % |
| 28 Feb | Infiltration | 0.0 % / 0.0 % | 0.1 % / 0.1 % | 0.1 % / 0.1 % |
| 1 Mar | — (infiltration again) | 0.1 % / 0.0 % | 10.5 % / 7.8 % | 0.1 % / 0.1 % |
| 2 Mar | Bot | 0.0 % / 0.0 % | 4.7 % / 1.6 % | 0.0 % / 0.0 % |

Each cell is recall / FPR. Paired 95 % confidence intervals, per-attack-type recall and drift for every day
are in the [full report](results/cic-ids2018-chronological.md).

What it shows:

1. **A static model fails on later days.**
   - **Where it scores:** its only detections come from SlowHTTPTest flows that duplicate its own training
     data.
   - **Why it misses:** the attacks on later days are different attacks, and supervised models learn the
     attacks they were shown.
2. **No strategy catches a new attack type on its first day.** On 15, 21, 22 and 28 Feb and 2 Mar, every
   strategy was at or near 0 % recall, because each brought attack types nobody had labelled yet. Adaptation
   is not a substitute for detecting novel attacks. That needs different methods (anomaly detection) or
   different features, and it is the main open problem.
3. **Adaptation helps when an attack type returns.**
   - **Web attacks** reappeared on 23 Feb: recall went from 0.2 % (static) to 60.8 % (retrain-always) and
     56.0 % (governed), at 0 % FPR. The paired gain was +55.8 pp [+51.5, +59.7] for the governed model.
   - **Hulk DoS** reached 99 % once 15 Feb's labels were in.
4. **The governance gate prevented false-positive regressions.** After 28 Feb, 1 Mar and 2 Mar, the candidates
   failed the false-positive gate, so the governed model stayed as it was.
   - **What retraining would have done on 1 Mar:** retrain-always reached 10.5 % infiltration recall but
     raised the FPR by +7.7 pp [+7.5, +7.9]. On a network with 10 million benign flows a day, that would be
     770,000 extra false alerts.
   - **What the gate cost:** the governed model kept a 0.1 % FPR and gave up that 10 % recall.

   This is the trade-off the gate is designed to surface, not hide. Published analyses of CSE-CIC-IDS2018
   report that its infiltration flows are hard to tell apart from benign traffic, which fits what happened.
5. **The gate can't foresee the next day.**
   - **Without port and protocol features:** the gate passed a candidate on 15 Feb's held-out data. That
     model's FPR on 16 Feb's very different benign traffic was then 3.8 %, against 0.4 % for retrain-always.
   - **Why:** the gate judges a candidate on the latest labelled day, so drift arriving after approval is a
     job for drift monitoring and later re-evaluation, not for the gate.

### Without the port and protocol features

In a lab dataset, a destination port can identify an attack scenario, a shortcut that may not transfer to
real networks. With `Dst Port` and `Protocol` removed:

- **Overall:** results were broadly the same.
- **One clear difference:** on 2 Mar, the governed model, which had never seen Bot traffic, detected 30.6 % of
  it at 0.0 % FPR. Retrain-always detected 37.3 % at 1.7 % FPR.
- **Interpretation:** dropping the port shortcut helped the model generalise to this new attack, which supports
  dropping those features for deployments.

[Full report without the port and protocol features](results/cic-ids2018-chronological-no-port.md).

### Drift detection

- **Benign feature drift** flagged the large changes on 16 and 21 Feb (major drift on 64–65 of 78 features)
  and smaller drift on 28 Feb to 2 Mar (2–3 features major).
- **ADWIN on the static model's error stream** first fired 113 events into 16 Feb, and only 32,703 events into
  15 Feb.
- **Later days:** the static model's errors stayed at a constant high level, so ADWIN saw no further change.
  A constant failure is not a change, which is why the error rate must be watched as a level as well as for
  changes.

## Running cost

| Item | Measured |
|---|---|
| Full study (load 9 files, 18 forest fits, predictions, drift) | 803 s wall clock |
| Peak memory | 4.8 GB |
| Loading one day file (0.3–1 million rows) | 14–67 s |
| Largest forest fit (400,000 rows) | 34 s |

The "real day through the product" run below adds import, scoring, explanation and drift timings.

## Reproduce (free)

```bash
# Data: the dataset's official public bucket, no account needed
#   https://cse-cic-ids2018.s3.ca-central-1.amazonaws.com/  (folder "Processed Traffic Data for ML Algorithms/")
#   save the day files as data/raw/cic-ids2018/<Weekday>-dd-mm-yyyy.csv (git-ignored)
adaptive-ids cic-ids2018-study data/raw/cic-ids2018
adaptive-ids cic-ids2018-study data/raw/cic-ids2018 --drop-feature "Dst Port" --drop-feature Protocol
```

On a 16 GB laptop, the defaults fit with room to spare. With 8 GB, use `--benign-cap 30000 --attack-cap 10000`.

## Limitations

- **Labels:** these are the dataset's own labels, not analyst-confirmed, and the dataset has known labelling
  problems (see the SlowHTTPTest finding above).
- **Coverage:** one dataset, one model family, one seed, sampled rows. The confidence intervals cover sampling
  of test events, not variation between training runs. Tuesday 20 Feb is not included.
- **Truncated days:** these are the files as published. Results describe the first part of each day only.
- **Usage terms:** check the dataset's terms of use (cite Sharafaldin et al., 2018) before using it in a
  commercial setting. UNSW-NB15 explicitly needs the authors' agreement for commercial use, and was not used.
