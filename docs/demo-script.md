# Demonstration

**Recording:** [`demo/adaptive-ids-demo.mp4`](demo/adaptive-ids-demo.mp4) (1 min 40 s, 1280×720, no audio, with
on-screen captions). It was recorded on 2026-10-12 from the running application with the built-in SYNTHETIC demo
data. Every screen in it is real output; nothing was edited.

It is recorded by a script, so anyone can produce it again from a clean checkout:

```bash
adaptive-ids db-upgrade
adaptive-ids create-user admin --role admin        # password from ADAPTIVE_IDS_NEW_USER_PASSWORD or a prompt
adaptive-ids demo --admin admin
(cd apps/web && npm ci && npm run build)
ADAPTIVE_IDS_WEB_DIST=apps/web/dist adaptive-ids serve
# in another terminal
npm install --no-save playwright && npx playwright install chromium
DEMO_PASSWORD=<admin password> node tools/record-demo.mjs http://127.0.0.1:8000 demo-recording
ffmpeg -i demo-recording/adaptive-ids-demo.webm -c:v libx264 -pix_fmt yuv420p -crf 23 adaptive-ids-demo.mp4
```

The demo data is synthetic and easy to separate, so its scores are near-perfect. The video shows the workflow,
not detection performance. For real-data results, use the NSL-KDD examples in the [case study](case-study.md).

## Narration script (for a voiced version, about 3½ minutes)

Times are approximate positions in the silent recording. Speak over it, or record a longer screen capture
following the same order.

| # | Time | Screen | Say |
|---|---|---|---|
| 1 | 0:00 | Sign-in | "This is Adaptive IDS, a network intrusion detection platform I built from my MSc research. It runs entirely on one machine: no cloud services, no external AI APIs. Everything you'll see uses clearly labelled synthetic data." |
| 2 | 0:07 | Dashboard | "Every number on the dashboard comes from the database with its counting rule. Notice 'confirmed attacks: unavailable'. The system never treats a model prediction as a confirmed attack; only an analyst can decide that." |
| 3 | 0:16 | Alerts | "Suspicious predictions become alerts. Severity comes from documented, configurable rules, not from the raw model score, because the scores are uncalibrated." |
| 4 | 0:22 | Alert #807 | "The investigation view shows the prediction, the exact model and preprocessing versions that produced it, and the event's features." |
| 5 | 0:29 | Explanation | "This is why the model gave this score: exact SHAP contributions. Before showing it, the system re-scores the event with the same hash-verified model and checks that the result matches the stored prediction. It also checks that the contributions add up to the score. If either check fails, it refuses to show an explanation rather than show a wrong one." |
| 6 | 0:44 | Start investigating | "Analyst decisions, such as status changes, notes and assignment, are stored separately from model output and audited." |
| 7 | 0:51 | Drift Monitor | "Drift is monitored as four separate signals: feature, prediction, performance and suspected concept drift. They have different causes and different responses, so they're never merged into one score. And drift never retrains or promotes a model by itself." |
| 8 | 0:58 | Drift analysis | "Each analysis compares a reference window with a current window, with per-feature statistics, thresholds and events an analyst reviews and closes with a note." |
| 9 | 1:05 | Model Management | "New models are candidates. A candidate is evaluated against the active model on the same labelled events, under a versioned protocol." |
| 10 | 1:12 | Candidate evaluation | "Here the candidate catches one more attack but raises 12 false positives. The confidence interval for the false-positive rate goes beyond the 0.5-point non-inferiority margin, so the verdict is 'fail'." |
| 11 | 1:24 | Candidate model | "A failed candidate can only be approved with a written, audited override. Before any activation or rollback, the system proves the stored model still loads and reproduces 25 recorded predictions." |
| 12 | 1:32 | Audit log | "Sign-ins, imports, scoring, decisions, approvals and exports are all in the audit log." |
| 13 | 1:38 | Dashboard | "It's local-first, reproducible and explainable. On the public NSL-KDD benchmark, the case study shows what the evidence does and doesn't support, including how the explanations traced a class of false positives to a single learned feature. Thank you." |

## Live demo checklist

1. Fresh start: `adaptive-ids demo --admin admin` on an empty database.
2. Sign in as admin in one browser window and as a viewer in another, to show read-only access.
3. Keep the NSL-KDD false-positive screenshot (`screenshots/ui-18-nsl-kdd-false-positive-explanation.png`)
   ready for the real-data question.
4. If asked "how accurate is it?": point to the official-split NSL-KDD numbers (about 77 % accuracy, about
   62 % attack recall on attack types not seen in training), not the near-perfect synthetic or random-split
   figures. See `msc-notebook-review.md`.
