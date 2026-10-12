# Release checklist and public-release audit (1.0.0)

The repository is ready to be made public, but **making it public is the owner's decision and action**. Nothing
here has been published.

## Audit performed on 2026-10-12

The whole git history was checked (all 392 file versions in every commit, not just the latest files):

| Check | Result |
|---|---|
| Datasets, captures, databases, notebooks or model binaries (`.csv` data, `.pcap`, `.db`, `.ipynb`, `.pkl`, `.joblib`) ever committed | **None.** The MSc notebook and the planning document that were uploaded during development were never committed |
| Private keys, cloud or API tokens, or passwords in connection strings | **None.** Only documented placeholders (`.env.example`) and the CI-only test database password |
| Personal paths (for example a real `C:\Users\…` folder) | **None.** Only placeholders such as `D:\path\to\MSc_Research_IDS` |
| Largest files | Screenshots (up to 1.2 MB) and the demo video (3.1 MB) |
| The same checks on every future commit | `tests/test_repo_hygiene.py` (CI) |

### Decisions for the owner

These are not problems, but they become public with the repository:

1. **Commit author emails.** One commit is authored with the owner's personal email address; the others use
   a no-reply address. If you prefer, set GitHub's *Keep my email address private* option for future
   commits. Changing past commits would mean rewriting history.
2. **Dissertation grade.** `docs/milestone-1-status.md` mentions the "86 %" that appears in the planning
   transcripts, interpreted as the dissertation grade. Keep it or remove it.
3. **Licence.** All rights reserved (`LICENSE`). Viewing on GitHub and evaluation runs are permitted;
   everything else needs permission. A public repository under this licence is *source-available*, not open
   source.

## Steps to publish

- [ ] Merge the release branch into `main` (pull request
      https://github.com/MuhammadHaiderAbbas/Ml-Detection-Project/pull/1). CI must be green on the merge
      commit.
- [ ] Settings → General → **Change visibility → Public**.
- [ ] Settings → Code security → enable **Private vulnerability reporting** (`SECURITY.md` points to it),
      **Secret scanning** and **Dependabot alerts**.
- [ ] Repository details: description ("Local-first ML network intrusion detection with drift monitoring,
      explainable alerts and governed model updates"), topics (`intrusion-detection`, `machine-learning`,
      `concept-drift`, `explainable-ai`, `fastapi`, `react`), and a website link if you have one.
- [ ] Create release **v1.0.0** from `main`: tag `v1.0.0`, with the `CHANGELOG.md` 1.0.0 section as notes and
      `docs/demo/adaptive-ids-demo.mp4` attached.
- [ ] Pin the repository on your GitHub profile.
- [ ] Optional: record a narrated version of the demo using `docs/demo-script.md`, and link it from the
      README.

## Before every later release

- [ ] `python -m pytest` and `cd apps/web && npm test && npm run build` pass. CI is green on Ubuntu, Windows
      and PostgreSQL.
- [ ] `pip-audit -r requirements.lock.txt --no-deps --disable-pip`, `bandit -q -r src` and
      `npm audit --omit=dev --audit-level=high` are clean (the CI `security` job).
- [ ] Version bumped in `pyproject.toml`, `src/adaptive_ids/__init__.py` and `apps/web/package.json`.
      `CHANGELOG.md` updated.
- [ ] `python tools/third_party_notices.py` re-run if dependencies changed.
- [ ] New results are labelled by provenance and committed under `docs/results/` with the command that
      produced them.
