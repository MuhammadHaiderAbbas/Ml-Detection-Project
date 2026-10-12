"""Application settings from environment variables (see .env.example).

Secrets and machine-specific paths live in the environment, never in source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; existing environment wins."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./var/adaptive_ids.db"
    storage_dir: Path = Path("var/storage")
    schemas_dir: Path = Path("configs/schemas")
    runs_dir: Path = Path("experiments/runs")
    severity_rules_path: Path = Path("configs/severity-rules.json")
    evaluation_protocol_path: Path = Path("configs/evaluation-protocol.json")
    retention_policy_path: Path = Path("configs/retention.json")
    max_upload_mb: int = 200
    max_import_rows: int = 1_000_000
    max_rejected_rows_stored: int = 10_000
    session_hours: int = 12
    session_idle_minutes: int = 60
    login_max_failures: int = 5  # per username, within login_window_minutes
    login_ip_max_failures: int = 20  # per client address, within login_window_minutes
    login_window_minutes: int = 15
    web_dist_dir: Path | None = None
    hsts: bool = False  # send Strict-Transport-Security; only when served over HTTPS
    cors_origins: tuple[str, ...] = field(default_factory=lambda: ("http://localhost:5173",))

    @classmethod
    def from_env(cls, *, dotenv: Path | None = Path(".env")) -> "Settings":
        if dotenv is not None:
            _load_dotenv(dotenv)
        env = os.environ.get
        origins = env("ADAPTIVE_IDS_CORS_ORIGINS")
        return cls(
            database_url=env("ADAPTIVE_IDS_DATABASE_URL") or cls.database_url,
            storage_dir=Path(env("ADAPTIVE_IDS_STORAGE_DIR") or cls.storage_dir),
            schemas_dir=Path(env("ADAPTIVE_IDS_SCHEMAS_DIR") or cls.schemas_dir),
            runs_dir=Path(env("ADAPTIVE_IDS_RUNS_DIR") or cls.runs_dir),
            severity_rules_path=Path(env("ADAPTIVE_IDS_SEVERITY_RULES") or cls.severity_rules_path),
            evaluation_protocol_path=Path(env("ADAPTIVE_IDS_EVALUATION_PROTOCOL") or cls.evaluation_protocol_path),
            retention_policy_path=Path(env("ADAPTIVE_IDS_RETENTION_POLICY") or cls.retention_policy_path),
            max_upload_mb=_int("ADAPTIVE_IDS_MAX_UPLOAD_MB", cls.max_upload_mb),
            max_import_rows=_int("ADAPTIVE_IDS_MAX_IMPORT_ROWS", cls.max_import_rows),
            max_rejected_rows_stored=_int("ADAPTIVE_IDS_MAX_REJECTED_ROWS_STORED", cls.max_rejected_rows_stored),
            session_hours=_int("ADAPTIVE_IDS_SESSION_HOURS", cls.session_hours),
            session_idle_minutes=_int("ADAPTIVE_IDS_SESSION_IDLE_MINUTES", cls.session_idle_minutes),
            login_max_failures=_int("ADAPTIVE_IDS_LOGIN_MAX_FAILURES", cls.login_max_failures),
            login_ip_max_failures=_int("ADAPTIVE_IDS_LOGIN_IP_MAX_FAILURES", cls.login_ip_max_failures),
            login_window_minutes=_int("ADAPTIVE_IDS_LOGIN_WINDOW_MINUTES", cls.login_window_minutes),
            web_dist_dir=Path(env("ADAPTIVE_IDS_WEB_DIST")) if env("ADAPTIVE_IDS_WEB_DIST") else None,
            hsts=env("ADAPTIVE_IDS_HSTS", "").lower() in ("1", "true", "yes"),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins else ("http://localhost:5173",),
        )
