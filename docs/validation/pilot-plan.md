# Pilot plan: one small, authorised deployment

**Goal:** find out whether Adaptive IDS helps a real team triage network alerts on their own traffic,
whether it runs reliably on their hardware, and what is missing. All of this happens under written
authorisation, without any data leaving the organisation.

## 1. Scope

| | |
|---|---|
| Organisations | One. A second only after the first one's review |
| Duration | 4–6 weeks: 1 week of setup and baseline, then 3–5 weeks of use |
| Data | Read-only flow exports (CSV, CIC-style or NetFlow converted to a supported schema) from one agreed network segment. No packet payloads and no live capture (not built in 1.0) |
| Where it runs | The organisation's own machine, inside their network, operated by their staff. The developer has no remote access unless it is separately authorised in writing |
| Users | 1–3 analysts (the analyst role) and one admin from the organisation |
| Out of scope | Blocking or changing traffic, automated response, production alerting duties (the pilot runs **alongside** their existing tools, never instead of them) |

## 2. Before any data is touched

1. **Authorisation.** The [authorisation template](pilot-authorisation-template.md) has been reviewed by the
   organisation's legal and data-protection staff, completed and signed by someone with authority over the
   network and the data.
2. **Data-protection check.** The organisation decides whether a DPIA (or local equivalent) is needed,
   because flow records contain IP addresses, which are usually personal data.
3. **Install and harden.**
   - Install on their machine following the README.
   - Use PostgreSQL with a dedicated database user.
   - Use their own TLS reverse proxy if they need access from another machine.
   - Set a retention policy in `configs/retention.json` that matches the authorisation.
   - Schedule `data-backup` to storage they control.
4. **Smoke test** with the SYNTHETIC demo, then delete the demo data (or use a separate database for it).
5. **Agree the model.** Either a model trained on a public dataset (labelled as such), or one trained on
   their own labelled history, if they have it and allow it.
   - Run a candidate evaluation on their labelled data **before** activation.
   - If there are no labels, say plainly that detection quality is unknown and is to be estimated from
     analyst decisions during the pilot.

## 3. Weekly routine

- The organisation exports flows → **Data Sources** → import → score.
- Analysts triage alerts, use the explanations, record decisions and notes, and link incidents.
- Weekly drift analysis: the reference window is week 1, the current window is the latest week.
  Drift events are reviewed and closed with notes.
- A 30-minute weekly call. Collect issues. No data, screenshots of real records or IP addresses leave
  the organisation.

## 4. What to measure

| Measure | How | Source |
|---|---|---|
| Alerts per week, and the share reviewed | Counts | Dashboard, Alerts |
| Analyst-confirmed precision | resolved as true ÷ (resolved + false positive) | Alert decisions |
| Time to a decision | Median time from "new" to the final status | Alert status history |
| Usefulness of explanations | Rate 1–5 on a sample of 20 alerts: "did the explanation help you decide?" | Analyst survey |
| Drift | Events raised, and how many the analysts judged real | Drift events and notes |
| Reliability | Failed imports or scoring runs, restore check after a backup | Audit log, `data-restore` test |
| Operating cost | Admin hours per week; hardware utilisation | Admin log |
| Missing features | A ranked list | Weekly calls |

Analyst-confirmed precision is not a detection rate: missed attacks are unknown unless the organisation has
another source of truth. Report it as precision among reviewed alerts, nothing more.

## 5. Success criteria (agreed before the start)

Fill in the numbers with the organisation in week 1. Suggested starting points:

- [ ] Ran for the full period without data loss. A restore test from backup succeeded.
- [ ] At least 80 % of alerts were reviewed within the agreed time, so the volume is manageable.
- [ ] Analyst-confirmed precision ≥ ___ % (agree a level that would make the tool worth an analyst's time).
- [ ] Median explanation usefulness ≥ 3.5 / 5.
- [ ] At least one finding that the organisation considers new or faster than with their existing tools.
- [ ] Admin effort ≤ ___ hours per week.

## 6. Stop or exit conditions

Stop immediately, and follow the authorisation's deletion clause, if:

- the authorisation is withdrawn, or its scope would be exceeded;
- any data would need to leave the organisation to continue;
- the tool degrades the organisation's systems or analysts' primary duties;
- a security issue is found in the tool (handle it under `SECURITY.md`).

## 7. Close-out (within 2 weeks of the end)

1. **Results.** Write the pilot report from the measures above, aggregated and with no raw records. The
   organisation reviews and approves it before anyone else sees it.
2. **Deletion.** Delete or hand over all data, as the authorisation says.
   - Drop the pilot database. The retention command can't do this, because it always keeps evidence and at
     least 90 days of audit records.
   - Delete backups and uploads.
   - The organisation confirms the deletion in writing.
3. **Decision.** Apply the decision gate in `phase-9-commercial-validation.md` §4.

## Deployment checks to run during the pilot

These fill the gaps in the benchmark (which used one reference machine):

- [ ] Throughput and memory on the organisation's hardware:
      `tools/benchmark_deployment.py --synthetic 100000 --database-url …`
- [ ] Two to three analysts working at the same time for a week, with no errors or lockouts.
- [ ] One week of daily imports and scoring with no manual fixes.
- [ ] A backup and restore to a spare machine, followed by `data-restore` model checks.
- [ ] Their reverse proxy, TLS and `--forwarded-allow-ips` set-up, verified with the sign-in throttling test.
