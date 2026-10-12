# Phase 7 — Security and testing

Status: **implemented and tested.** This phase completes permissions, audit logging, validation, error
handling and regression tests (spec §21), and fills the remaining §17 security and privacy controls.

## Threat model (local-first deployment)

| Asset | Threat | Main controls |
|---|---|---|
| Imported traffic data (IPs, flow features) | Read or exported by someone who shouldn't | Authentication on every route but `health` and `login`; per-permission checks; exports need `data.export`; backups flagged as sensitive |
| Model artifacts | Tampered or substituted model (pickle code execution) | SHA-256 from the registry checked before every load; restore check before activation; never loads unlisted files |
| Model lifecycle | Unreviewed or malicious promotion | `models.manage` (admin only), evaluation gates, audited approval and overrides (Phase 6) |
| Accounts | Password guessing, stolen sessions | scrypt hashing, password policy, sign-in throttling, idle and absolute session expiry, revocation on password or role change |
| Analyst decisions | Repudiation, silent changes | Append-only audit log for sensitive actions; status history and notes kept separately from automated output |
| The server | Oversized or malformed input, injection | Body-size limits, schema validation, parameterised SQL (SQLAlchemy), CSV-formula escaping, generic 500 errors, strict CSP |

Out of scope for this release: multi-tenant isolation, SSO/MFA, at-rest database encryption (use OS or
volume encryption), and network-level controls. Spec Phase 9 decides whether these are needed.

## Controls matrix (spec §17)

| Requirement | Implementation | Tests |
|---|---|---|
| Authentication | Opaque bearer tokens (32 random bytes); only a SHA-256 of each is stored | `test_permissions.py::test_unauthenticated_requests_are_rejected_everywhere` |
| Password hashing | scrypt (N=2^14, r=8, p=1, 16-byte salt), constant-time compare; unknown users cost the same time | `test_accounts.py::test_login_does_not_leak_whether_a_user_exists` |
| Password policy | 12–256 characters, not repetitive, not common, must not contain the username | `test_accounts.py::test_password_policy` |
| Server-side roles and permissions | `permissions.py`: 17 named permissions × 3 roles (admin, analyst, viewer). Every route declares exactly one | `test_permissions.py`: walks every route, cross-checked with the OpenAPI schema; 401/403 probes for each role |
| Secure sessions | 12-hour absolute and 60-minute idle expiry; revoked on logout, deactivation, role change, password change (other sessions) or reset | `test_accounts.py::test_idle_sessions_expire`, `::test_change_own_password`, `::test_admin_role_change_and_password_reset_sign_the_user_out` |
| Brute-force protection | 5 failures per username or 20 per address in 15 minutes → 429 with `Retry-After`; counted from audit records, so it survives restarts | `test_accounts.py::test_username_lockout_after_repeated_failures`, `::test_address_throttle_across_usernames` |
| Account safety | Admins can't deactivate or demote themselves; the last active admin is protected | `test_accounts.py::test_admins_cannot_lock_themselves_out`, `::test_last_admin_guard` |
| Input validation | Pydantic models on every request; feature schemas on every import; 422 responses never echo submitted values | `test_http_hardening.py::test_validation_errors_never_echo_submitted_values` |
| Parameterised database access | SQLAlchemy ORM/Core only; no string-built SQL | (code review; bandit B608 clean) |
| Unsafe uploads | `.csv` only, streamed with size and row limits, stored under a generated name; never served back | Phase 3 import tests; `test_http_hardening.py::test_oversized_upload_is_refused_before_parsing` |
| Size and row limits | Uploads ≤ `ADAPTIVE_IDS_MAX_UPLOAD_MB`, other bodies ≤ 1 MiB (checked before parsing, also for streamed bodies), rows ≤ `ADAPTIVE_IDS_MAX_IMPORT_ROWS` | `test_http_hardening.py::test_oversized_json_bodies_are_refused` |
| Safe errors | Domain errors become 4xx with a plain message; anything else is a generic 500 with a reference id (details only in the server log); no server paths in messages | `test_http_hardening.py::test_unexpected_errors_are_generic` |
| HTTP hardening | CSP (strict for the web app, `default-src 'none'` for the API), `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, permissions policy, COOP/CORP, `no-store` on API responses, optional HSTS | `test_http_hardening.py::test_security_headers_on_api_and_errors`, `::test_web_app_csp` |
| Export safety | CSV cells that a spreadsheet would run as formulas are prefixed with `'` | `test_http_hardening.py::test_csv_cells_neutralise_formulas`, `::test_alert_export_escapes_untrusted_values` |
| Secrets in the environment | `.env` (git-ignored) / environment variables; `.env.example` holds placeholders only | `test_repo_hygiene.py` |
| Audit logging | Sign-in, failed and throttled sign-ins, password and role changes, user changes, imports, scoring, alert/incident/drift decisions, model lifecycle, evaluations, restore checks, exports, retention purges | across the API test files |
| Configurable retention | `configs/retention.json` + `adaptive-ids retention [--apply]`; evidence is kept | `test_retention.py` |
| Restricted access to datasets and artifacts | Raw upload files and model artifacts are never served by the API; exports need `data.export`; viewers are read-only | `test_permissions.py::test_viewer_can_read` |
| Dependency and vulnerability checks | CI `security` job (blocking): `pip-audit` on the lock file, `bandit` on `src`; `npm audit --omit=dev --audit-level=high` in the `web` job | CI |
| Backup and recovery | `adaptive-ids data-backup` / `--verify` / `data-restore` with SHA-256 manifest and post-restore model checks | `test_backup.py` (SQLite and PostgreSQL) |
| Untrusted inputs (CSV, artifacts) | Schema validation and row rejection; trusted-artifact manifest with hashes | Phase 2–3 tests |

## Roles

| Permission | admin | analyst | viewer |
|---|:-:|:-:|:-:|
| Read dashboards, alerts, incidents, models, drift, data, config | ✓ | ✓ | ✓ |
| Import data, run scoring | ✓ | ✓ | |
| Change alerts, incidents and drift events | ✓ | ✓ | |
| Export data (CSV / Markdown) | ✓ | ✓ | |
| Model governance (register, evaluate, approve, activate, verify) | ✓ | | |
| Manage users | ✓ | | |
| Read the audit log | ✓ | | |

Only the user who started an import (or an admin) can cancel it. The web UI hides controls a role
can't use, based on the permissions `/api/auth/me` returns. The server enforces every one of them
regardless.

## Acceptance checks (spec §20)

| # | Check | Evidence |
|---|---|---|
| 1 | Baseline reproduced or discrepancy documented | `docs/msc-notebook-review.md`: 15/15 reported metrics reproduced; discrepancies documented |
| 2 | Schemas and preprocessing tested | `test_schema.py`, `test_preprocessing.py` |
| 3 | Invalid data rejected with explanations | `test_ingestion.py`, `test_api.py` (rejected-row reasons) |
| 4 | Correct model and preprocessing versions | `test_detection.py`, prediction records carry both versions |
| 5 | Alerts persist and can be investigated | `test_api.py` alert lifecycle tests |
| 6 | Drift events recorded and displayed accurately | `test_drift_engine.py`, `test_drift_api.py` |
| 7 | Metrics on the correct data | `test_evaluation.py`, `test_governance.py` (paired comparison on the same events) |
| 8 | Promotion requires evaluation and approval | `test_governance.py` |
| 9 | Rollback restores a previous approved version | `test_api.py`, `test_governance.py::test_activation_and_rollback_require_a_restorable_artifact` |
| 10 | Authentication and permissions tested | `test_permissions.py`, `test_accounts.py` |
| 11 | Sensitive information excluded from logs and commits | `test_repo_hygiene.py`, `test_http_hardening.py::test_logs_never_contain_passwords_or_tokens` |
| 12 | Fresh local setup follows the documentation | CI `fresh-setup` job: clean checkout → README commands → demo → serve → sign in → backup → retention |
| 13 | Demonstration uses labelled, reproducible data | `synthetic_demo` provenance everywhere; seeded generators |
| 14 | Failures don't produce misleading predictions | `test_detection.py` (errors raise), scoring runs fail as a whole |

## Operations runbook

### Retention

```bash
adaptive-ids retention            # dry run: lists what the policy would remove and what is kept as evidence
adaptive-ids retention --apply    # deletes, then writes one audited retention.purge record
```

The shipped policy deletes stored upload files after 30 days and expired sessions after 30 days. It
keeps imports and the audit log forever. Change `configs/retention.json` (or point
`ADAPTIVE_IDS_RETENTION_POLICY` to your own file). The audit log can't be set below 90 days. Run it
from a scheduler (cron or Windows Task Scheduler) if you set limits.

### Backup and restore

```bash
adaptive-ids data-backup D:\AdaptiveIDS\backups           # database + uploads + runs/models + configs + manifest
adaptive-ids data-backup --verify D:\AdaptiveIDS\backups\adaptive-ids-backup-<time>
adaptive-ids data-restore D:\AdaptiveIDS\backups\adaptive-ids-backup-<time>            # into an empty setup
adaptive-ids data-restore <folder> --force                 # replace existing data (asks nothing more)
adaptive-ids db-upgrade                                     # if the backup is from an older version
```

- **SQLite** is copied with the online-backup API, so the app can keep running. **PostgreSQL** uses
  `pg_dump --format=custom` and `pg_restore --clean --single-transaction`. The client tools must be
  installed, and the password is passed through the environment, never on the command line.
- Restore verifies every hash before touching anything. After restoring, it re-checks each approved,
  active or archived model, and exits non-zero if an artifact can't be verified.
- Restore into the same configured folders (`ADAPTIVE_IDS_STORAGE_DIR`, `ADAPTIVE_IDS_RUNS_DIR`),
  because records refer to those paths.
- **A backup holds the same sensitive data as the live system.** Keep it on encrypted,
  access-controlled storage, and test a restore regularly.

### Running beyond localhost (HTTPS)

The server listens on `127.0.0.1` by default. To expose it on a network:

1. Put it behind a TLS-terminating reverse proxy (Caddy, nginx or IIS). Don't expose uvicorn
   directly.
2. Set `ADAPTIVE_IDS_HSTS=1` once HTTPS works. Set `ADAPTIVE_IDS_CORS_ORIGINS` to the exact
   origin, or leave it empty when the API serves the web app itself.
3. Make the proxy pass the client address (`X-Forwarded-For`) and start the server with
   `adaptive-ids serve --forwarded-allow-ips <proxy ip>`. The header is only trusted from that
   address (by default only from this machine). Otherwise sign-in throttling and audit records see
   the proxy's address, or a client could spoof its own.
4. Use PostgreSQL with a dedicated, least-privilege database user and a strong password in `.env`.
5. Schedule `data-backup` and `retention`, and keep the OS and `requirements.lock.txt` patched. CI's
   `security` job fails when a pinned dependency has a known vulnerability.

## Screenshots

| | |
|---|---|
| [Read-only viewer (alert without actions)](screenshots/ui-13-viewer-read-only.png) | [Change password, roles and password reset](screenshots/ui-14-account-security.png) |
| [Sign-in throttling](screenshots/ui-15-login-throttled.png) | |

A browser check signed in as admin and as viewer, and opened all 18 pages. It found no console
errors, no Content-Security-Policy violations and no horizontal overflow.

## Known limitations

- No multi-factor authentication or SSO. Use a VPN or SSO-aware proxy in front of the app if needed.
- Bearer tokens are kept in the browser's session storage. The strict CSP and the absence of inline
  scripts limit, but don't remove, the impact of a cross-site-scripting bug.
- Sign-in throttling can be used to lock a known username out temporarily (by design, for 15 minutes).
  Admins can still reset that user's password.
- The audit log is append-only by convention, not cryptographically chained.
- Retention protects evidence by reference (evaluations, incident links). Other ad-hoc references,
  for example a drift analysis that read an import, keep their aggregate results but not the raw events.
