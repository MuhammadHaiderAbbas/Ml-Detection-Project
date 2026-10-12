# Model explanations (SHAP)

Status: **implemented and tested.** Engine in `src/adaptive_ids/explainability/`, service in
`services/explanations.py`, API `GET /api/alerts/{id}/explanation`, UI on every alert page, CLI
`adaptive-ids explain-summary`, migration `0005`. This completes item 6 of the spec's definition of done
("inspect model explanations") and the §11 investigation view.

> An explanation shows how the model arrived at its score. It is not evidence that an event is an
> attack, and the page says so next to every chart.

## What is computed

| | |
|---|---|
| Method | SHAP `TreeExplainer`: the exact polynomial-time algorithm with tree-path-dependent feature perturbation. It is exact, so there is no background sample and no sampling error. |
| Supported models | scikit-learn `RandomForestClassifier`, `ExtraTreesClassifier`, `DecisionTreeClassifier`, `HistGradientBoostingClassifier`. These cover every model the platform trains except `LogisticRegression` and `GaussianNB`. |
| Unsupported models | The page says which model type it is and that no explanation is available. No approximate method (KernelSHAP, permutation) is substituted. |
| Explained class | The class whose score is shown: the predicted class (the score is its maximum class probability), or the positive class when the model uses a threshold rule |
| Units | Random forest, extra trees, decision tree: the model's (uncalibrated) class score, 0–1. Gradient boosting: log-odds (binary) or the raw per-class score (multi-class). The page names the unit. |
| Features | Attributions are on the model input after preprocessing. The platform's preprocessing works feature by feature (imputation, optional scaling), so every model input is exactly one schema feature. The table shows both the imported value and the model input. |

## Why the numbers can be trusted

Before anything is shown, `services/explanations.py` checks the following, and refuses (HTTP 409 with
the reason) if any check fails:

1. **Same artifact.** The model is loaded through the hash-verified cache, and the stored explanation
   records the artifact's SHA-256.
2. **Same preprocessing.** The stored preprocessing state must rebuild to the version the prediction
   recorded.
3. **Same prediction.** The event is scored again, and must reproduce the stored class exactly and the
   stored score within 1e-9. If someone changed the record or the artifact, the explanation would
   describe a different prediction, so none is given.
4. **Additivity.** The base value plus the sum of the contributions must equal the model's own output
   (`predict_proba`, or `decision_function` for gradient boosting) within 1e-6. In practice the error is
   around 1e-14.

The first successful explanation is stored (`prediction_explanations`), so later reviews of the alert see
the same attribution. Viewers can read explanations; they're part of `alerts.read`.

Tests (`tests/test_explanations.py`, 17 tests):

- **Additivity:** every supported model, binary and multi-class, adds up to the model's own output.
- **Brute-force check:** for a decision tree, every value is compared with Shapley values computed by
  enumerating all feature subsets with the same path-dependent value function. They agree to 1e-12, an
  independent check of the library.
- **Bad output is refused:** a deliberately skewed explainer output is refused.
- **Unsupported models** (logistic regression, naive Bayes) get a reason, not a number.
- **Through the API:**
  - the explained output equals the alert's score;
  - the explanation is stored and reused;
  - viewers can read it;
  - a prediction record that no longer matches its model gets a 409, and nothing is stored;
  - the summary is reproducible.

## Worked example on real data (NSL-KDD, public)

The Random Forest from Phase 6 (trained only on KDDTrain+) scored all 22,544 events of KDDTest+ and raised
7,689 alerts. Of those, 7,450 carry an attack label in the file and 239 carry `normal`. Labels come with
the public dataset; they are not analyst decisions.

**One false positive, explained** ([screenshot](screenshots/ui-18-nsl-kdd-false-positive-explanation.png)):

- **The alert:** #425, row 1200 of KDDTest+, a UDP record labelled `normal`, predicted `teardrop`
  with a score of 0.9245.
- **Main reason:** `wrong_fragment = 3` adds +0.469 to the teardrop score. No other feature adds more
  than +0.074, starting from a base value of 0.044.
- **Why the model learned this:** in KDDTrain+, `wrong_fragment > 0` occurs in 1.9 % of attack records
  and in **none** of the 67,343 normal records; it appears only in `teardrop` (892) and `pod` (198).
- **What follows on the test set:** KDDTest+ has 52 normal records with fragment errors. The model
  flags **all 52** (37 as teardrop, 15 as pod). That is 22 % of the 239 false positives.

So the explanation points to a specific, checkable weakness: the training data taught the model that
malformed fragments only ever mean an attack. An analyst seeing this chart knows what to look at in the
traffic, and a modeller knows what to fix (training data with benign fragmentation, or a rule for it).

**What drives each group** (`adaptive-ids explain-summary --import-id 2 --model-id 1 --sample 300`):

- **Sample:** a seeded sample of up to 300 events per group.
- **Measure:** mean absolute contribution to the explained class.
- **Explained class:** the predicted class. For missed attacks that is `normal`.
- **Full output:** [`results/nsl-kdd-explanations.json`](results/nsl-kdd-explanations.json).
- **Additivity:** the largest error over all 839 explained events was 4.7e-14.

| Rank | Alerts on attack-labelled events (7,450) | Alerts on normal-labelled events (239, all explained) | Attack-labelled events the model called normal (5,383) |
|---|---|---|---|
| 1 | `src_bytes` 0.082 | `wrong_fragment` 0.123 | `src_bytes` 0.081 |
| 2 | `count` 0.070 | `src_bytes` 0.114 | `dst_host_srv_count` 0.075 |
| 3 | `dst_host_same_src_port_rate` 0.063 | `count` 0.060 | `dst_bytes` 0.066 |
| 4 | `diff_srv_rate` 0.050 | `dst_host_count` 0.044 | `dst_host_same_src_port_rate` 0.063 |
| 5 | `rerror_rate` 0.047 | `dst_bytes` 0.043 | `dst_host_same_srv_rate` 0.045 |

The first view of an alert's explanation took a median of 0.40 s for this 200-tree, 23-class forest
(20 alerts; [`results/benchmark-nsl-kdd.json`](results/benchmark-nsl-kdd.json)). Later views read the stored
explanation, in about 15 ms. In batch, the 839-event summary took 98 s on one CPU core.

## Use it

- **Web:** open any alert. The "Why the model gave this score" card shows the ten largest contributions
  and sums the rest into one row, so the bars still add up from the base value to the output. A table
  view lists every feature with exact values, and the method, verification and limitations are listed
  under the chart.
- **API:** `GET /api/alerts/{id}/explanation` (permission `alerts.read`).
- **CLI:** `adaptive-ids explain-summary --import-id N --model-id M [--sample 200] [--seed 0] [--out file.json]`.

## Limitations

- **Supported models:** only tree models are supported. Adding a model type means adding an exact
  explainer and its tests; no approximation is used meanwhile.
- **Correlated features:** with the tree-path-dependent method, related features (for example `count`
  and `srv_count`) can share or swap credit. A small contribution doesn't prove a feature is
  irrelevant.
- **Units:** contributions are in score units, not probabilities of an attack, and the scores are
  uncalibrated.
- **Summary groups:** they use dataset labels from the file, not analyst-confirmed outcomes.
