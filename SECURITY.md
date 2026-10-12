# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue:

- Use GitHub's **"Report a vulnerability"** button on this repository's *Security* tab (private
  vulnerability reporting), or
- contact the maintainer through their GitHub profile and ask for a private channel.

Include the version or commit, what you did, what happened, and what you expected. Please don't
include real network captures or personal data in a report; a synthetic reproduction is enough.

You should get an acknowledgement within 7 days. Fixes are released as a new version with a
`CHANGELOG.md` entry that credits the reporter, unless they prefer otherwise.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| < 1.0 | No (development snapshots) |

## Scope and design

Adaptive IDS is designed to run **locally**, on a single trusted machine or behind a TLS reverse
proxy. Its threat model, controls and known limitations are documented in
[`docs/phase-7-security.md`](docs/phase-7-security.md). In particular:

- Model files (pickle/joblib) are loaded only after a SHA-256 allowlist check. Never add a model you
  didn't produce yourself to `models/trusted_artifacts.json`.
- Only process network data you are authorised to use, and keep backups encrypted: they contain the
  same data as the live system.
- An ML prediction is a suspicion, not a confirmed attack.
