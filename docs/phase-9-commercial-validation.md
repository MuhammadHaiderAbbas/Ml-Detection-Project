# Phase 9 — Commercial validation

Spec §21: *"Interview potential users, test deployment requirements and evaluate a small authorised pilot
before building multi-tenant SaaS features."*

Status: **prepared, not yet run.** Interviews and a pilot need real people and an organisation's written
authorisation. Software can't do them, and no results are claimed here. This phase supplies:

| Part | State | Where |
|---|---|---|
| Deployment requirements | **Measured** on a reference machine, reproducible with one command | [below](#1-deployment-requirements-measured) and `docs/results/benchmark-*.json` |
| User interviews | Guide, screener and synthesis template ready | [`validation/interview-guide.md`](validation/interview-guide.md) |
| Authorised pilot | Plan, success criteria, exit criteria and authorisation template ready | [`validation/pilot-plan.md`](validation/pilot-plan.md), [`validation/pilot-authorisation-template.md`](validation/pilot-authorisation-template.md) |
| Decision gate before multi-tenant SaaS | Defined | [below](#4-decision-gate-before-building-multi-tenant-saas) |

## 1. Deployment requirements (measured)

`python tools/benchmark_deployment.py` runs the real application through an operator's workflow (import →
evaluate → approve with restore check → activate → score → open explanations → drift analysis → backup) on a
fresh database. It records time, throughput, peak memory and storage.

**Machine:** 4 logical CPUs (Intel Xeon @ 2.10 GHz), 15.7 GB RAM, Linux, Python 3.10, application 1.0.0,
measured 2026-10-12. The SYNTHETIC runs use the demo Random Forest (100 trees, 3 classes, 12 features). The
NSL-KDD run uses the Phase 6 Random Forest (200 trees, 23 classes, 38 features) on the public test set.

| Step | SYNTHETIC 100k, SQLite | SYNTHETIC 100k, PostgreSQL 16 | NSL-KDD, SQLite |
|---|---|---|---|
| CSV import (validate + store) | 9,599 events/s | 7,428 events/s | 7,130 events/s (KDDTest+); 5,744 events/s (KDDTrain+, 126k rows) |
| Batch scoring (predict + store + alerts) | 3,825 events/s | 2,379 events/s | 2,995 events/s |
| Candidate evaluation (paired, 1,000 bootstrap resamples) | 0.73 s for 20k events | 0.77 s for 20k events | 2.5 s for 22.5k events |
| Approve (incl. restore check) / activate | 0.11 s / 0.13 s | 0.10 s / 0.10 s | 0.33 s / 0.35 s |
| Alert explanation, first view (median of 20) | 101 ms | 104 ms | 397 ms |
| Alert explanation, stored | 9 ms | 12 ms | 16 ms |
| Drift analysis | 15,731 events/s | 15,478 events/s | 6,526 events/s |
| Dashboard summary | 0.15 s | 0.14 s | 0.05 s |
| Backup | 0.7 s | 1.6 s | 2.9 s |
| Peak process memory | 638 MB | 646 MB | 1,351 MB |
| Database size | 95 MB for 120k events | 115 MB for 120k events | 173 MB for 149k events |

Raw output: [`benchmark-synthetic-sqlite.json`](results/benchmark-synthetic-sqlite.json),
[`benchmark-synthetic-postgresql.json`](results/benchmark-synthetic-postgresql.json),
[`benchmark-nsl-kdd.json`](results/benchmark-nsl-kdd.json).

What this means for a pilot:

- **Hardware.** Memory depends on the size of the largest file imported in one go.
  - **Files of 20,000–150,000 events:** peak memory was 0.6–1.4 GB.
  - **A real 1-million-row CSE-CIC-IDS2018 day file:** peak memory was **9.3 GB** (below).
  - **Recommendation:** 16 GB RAM and 4 cores, with files split into parts of about 250,000 rows on smaller
    machines. No GPU is needed.
- **Volume.** Batch scoring ran at 2,400–3,800 events per second on one machine, so a day of flow records
  for a small site (for example 1–5 million flows) scores in roughly 5–35 minutes. This is **batch scoring
  of imported files**, the only mode built. Live streaming capture is not implemented, and a pilot must not
  assume it.
- **Storage.** Storage per stored event, including its prediction and any alert, depends on the feature
  count:
  - 12–38 features: about 0.8–1.2 KB;
  - the 78 CSE-CIC-IDS2018 features: about 2.5 KB.

  So plan for 1–3 GB per million events. Keep upload files under the retention policy, which by default deletes them
  after 30 days. Backups were 26 MB (PostgreSQL, compressed) to 111 MB (SQLite) for 120k events.
- **Database.** SQLite was faster on one machine, while PostgreSQL gives concurrent users, online backups
  with `pg_dump`, and access control. Use PostgreSQL for any pilot with more than one analyst.
- **Explanations.** The cost depends on model size. For a large forest, expect up to about half a second
  when an alert is first opened, and near-instant afterwards.

### A real, full day file (CSE-CIC-IDS2018, 15 Feb 2018)

The unmodified 376 MB file (1,048,575 rows) went through the same workflow with a model trained on the
previous day ([`benchmark-cic-ids2018-real-day.json`](results/benchmark-cic-ids2018-real-day.json)):

| Step | Measured |
|---|---|
| Import (validate, reject defective rows, store) | 293 s, 3,552 events/s, 1,040,548 events accepted |
| Batch scoring | 325 s, 3,206 events/s, 21 alerts |
| Candidate evaluation (on a 90,990-event sample of the day) | 12.6 s |
| Alert explanation, first view / stored | 136 ms median / 11 ms |
| Drift analysis on the whole day | **Refused:** "window has 1040548 events; the limit per analysis is 1000000" |
| Evaluation on the whole day | **Refused:** "the limit per evaluation is 1000000" |
| Backup | 13.7 s, 3.5 GB |
| Peak process memory | 9.3 GB |
| Database size | 3.0 GB |

What this shows:

- **Large files are slower.** Throughput was lower than with small files, and import was the slowest step.
- **Limits are enforced.** The million-event limits on evaluations and drift analyses refuse with a clear
  message rather than running out of memory. To analyse a whole large day, use a time window
  (`since`/`until`) or split the file.
- **The row limit needs raising.** Importing a file over a million rows needs `ADAPTIVE_IDS_MAX_IMPORT_ROWS`
  raised.
- **Few alerts is correct here, not a fault.** Only 21 alerts on a day with about 52,000 attack flows matches
  the chronological study: the previous day's model has never seen this day's attacks.
- **The first approval has no performance floor.** The candidate evaluation passed, because with no earlier
  model to compare against only the validity gates apply. A deployment should set `min_attack_recall` (and
  `max_false_positive_rate`) in `configs/evaluation-protocol.json`.

What it doesn't measure: concurrent users, network capture, multi-day continuous operation, or hardware
other than the reference machine. The pilot plan adds these (see "Deployment checks" there).

Reproduce:

```bash
python tools/benchmark_deployment.py --synthetic 100000 --out my-benchmark.json
python tools/benchmark_deployment.py --synthetic 100000 --database-url postgresql+psycopg://user:pass@host/emptydb
python tools/benchmark_deployment.py --run <nsl-kdd run> --runs-dir experiments/runs \
  --data data/processed/nsl-kdd/KDDTest+.csv --reference-csv data/processed/nsl-kdd/KDDTrain+.csv --schema nsl-kdd@1.0.0
```

### Supported deployment shape (1.0)

| Item | Requirement |
|---|---|
| Operating system | Windows 10/11 or Linux (CI tests Ubuntu and Windows) |
| Runtime | Python 3.10, Node.js 20.19+ or 22.12+ (only to build the web app) |
| Database | SQLite (single user, evaluation) or PostgreSQL 16 (pilot) |
| Network | Listens on 127.0.0.1 by default; behind a TLS reverse proxy for anything else (see `phase-7-security.md`) |
| Input | CSV flow exports that match a versioned feature schema (CIC-style flows, NSL-KDD; others by adding a schema) |
| Outbound connections | None. No telemetry, no cloud services, no external AI APIs |
| Accounts | Local accounts (admin, analyst, viewer); no SSO or MFA in 1.0 |

## 2. User interviews

The goal is to learn whether the problems this product addresses are real and painful for the people who
would use or buy it. Interviews aren't for demonstrating features.

- **Who:** SOC analysts and leads, network or IT admins at small and medium organisations, managed security
  providers, and security researchers or lecturers.
- **How many:** 12–15 interviews, at least 4 per primary segment, before any pricing or SaaS decision.
- **The hypotheses to test** are listed in the guide. Each is either supported or refuted by what people
  describe they *already do*, not by what they say they would do.

See [`validation/interview-guide.md`](validation/interview-guide.md).

## 3. A small authorised pilot

One organisation, one network segment, 4–6 weeks, read-only flow exports, on the organisation's own
hardware, with written authorisation signed **before** any data is touched. Success and exit criteria are
fixed in advance. See [`validation/pilot-plan.md`](validation/pilot-plan.md) and
[`validation/pilot-authorisation-template.md`](validation/pilot-authorisation-template.md). The template is
not legal advice: the organisation's own legal and data-protection staff must review it.

## 4. Decision gate before building multi-tenant SaaS

Multi-tenant features (tenant isolation, billing, hosted data, SSO) are built **only if all** of these hold:

1. At least 8 of the interviews describe the same top-two problems unprompted, and at least 3 people with
   budget authority say they'd pay to solve them.
2. The pilot meets its success criteria (pilot plan §5), including the analysts' own usefulness rating.
3. At least one pilot organisation, or one interviewee's organisation, is willing to have its data hosted
   off-site. Otherwise the product stays an on-premises install.
4. The security work that hosting needs is planned and costed: tenant isolation, encryption at rest, SSO/MFA,
   an external penetration test, and data-processing agreements.

If 1 or 2 fails, change the problem or the segment, not the architecture.
