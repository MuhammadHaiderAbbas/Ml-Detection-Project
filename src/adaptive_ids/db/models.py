"""Relational schema (SQLAlchemy 2.0). PostgreSQL is the target; SQLite works for local prototyping.

Conventions:
* All timestamps are timezone-aware UTC (see :class:`UTCDateTime`).
* Automated outputs (predictions) and analyst decisions (alert status changes,
  notes, incident dispositions) live in separate tables, so they can never be
  confused.
* Ground-truth labels that came with an imported dataset are stored as
  ``events.dataset_label``; they are not analyst decisions either.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores UTC; always returns timezone-aware UTC datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use UTC-aware datetimes")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime(), dict[str, Any]: JSON, list[Any]: JSON}


# --------------------------------------------------------------------------- users


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))  # admin | analyst | viewer (see permissions.py)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None]


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]  # idle timeout; updated at most once a minute
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user: Mapped[User] = relationship()


# --------------------------------------------------------------------------- data


class DatasetImport(Base):
    __tablename__ = "dataset_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_uid: Mapped[str] = mapped_column(String(36), unique=True)
    dataset_name: Mapped[str] = mapped_column(String(200))
    dataset_version: Mapped[str] = mapped_column(String(100))
    provenance: Mapped[str] = mapped_column(String(40))
    data_source: Mapped[str | None] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_bytes: Mapped[int | None] = mapped_column(Integer)
    schema_id: Mapped[str] = mapped_column(String(200))
    schema_hash: Mapped[str] = mapped_column(String(64))
    column_mapping: Mapped[dict[str, Any]] = mapped_column(default=dict)
    column_mapping_hash: Mapped[str] = mapped_column(String(64))
    duplicate_policy: Mapped[str] = mapped_column(String(10), default="keep")
    status: Mapped[str] = mapped_column(String(32), index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_dropped: Mapped[int] = mapped_column(Integer, default=0)
    rejection_reason_counts: Mapped[dict[str, Any]] = mapped_column(default=dict)
    label_distribution: Mapped[dict[str, Any]] = mapped_column(default=dict)
    errors: Mapped[list[Any]] = mapped_column(default=list)
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]


class RejectedRow(Base):
    __tablename__ = "rejected_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("dataset_imports.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[str] = mapped_column(Text)


class Event(Base):
    """One accepted network-flow record from an import."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("dataset_imports.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    event_key: Mapped[str | None] = mapped_column(String(200))
    occurred_at: Mapped[datetime | None] = mapped_column(index=True)
    source: Mapped[str | None] = mapped_column(String(200), index=True)
    destination: Mapped[str | None] = mapped_column(String(200), index=True)
    dataset_label: Mapped[str | None] = mapped_column(String(200))
    features: Mapped[dict[str, Any]]
    context: Mapped[dict[str, Any]] = mapped_column(default=dict)
    __table_args__ = (UniqueConstraint("import_id", "row_number"),)


# --------------------------------------------------------------------------- models


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    model_type: Mapped[str] = mapped_column(String(200))
    artifact_path: Mapped[str] = mapped_column(String(500))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_format: Mapped[str] = mapped_column(String(16), default="joblib")
    provenance: Mapped[str] = mapped_column(String(40))
    feature_schema: Mapped[dict[str, Any]]
    feature_schema_id: Mapped[str] = mapped_column(String(200))
    preprocessor: Mapped[dict[str, Any]]
    preprocessing_version: Mapped[str] = mapped_column(String(100))
    positive_class: Mapped[str | None] = mapped_column(String(200))
    threshold: Mapped[float | None] = mapped_column(Float)
    benign_label: Mapped[str | None] = mapped_column(String(200))
    training_dataset: Mapped[str | None] = mapped_column(String(300))
    training_config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    software_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    evaluation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source_run: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    registered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None]
    activated_at: Mapped[datetime | None]
    # Phase 6 governance: the evaluation an approval relied on, a small recorded
    # input sample with the outputs the model gave at approval (used to prove the
    # artifact can be restored), and the latest restorability check.
    approval_evaluation_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_evaluations.id", use_alter=True, ondelete="SET NULL"))
    approval_override: Mapped[bool] = mapped_column(Boolean, default=False)
    reference_sample: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    restore_check: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    @property
    def has_reference_sample(self) -> bool:
        return bool(self.reference_sample)


class ModelStatusChange(Base):
    __tablename__ = "model_status_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    reason: Mapped[str | None] = mapped_column(Text)


class ModelEvaluation(Base):
    """A candidate scored side by side with the baseline on one labelled import, under a versioned protocol."""

    __tablename__ = "model_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), index=True)
    baseline_model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    import_id: Mapped[int] = mapped_column(ForeignKey("dataset_imports.id"), index=True)
    protocol: Mapped[dict[str, Any]]
    protocol_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), index=True)
    verdict: Mapped[str | None] = mapped_column(String(30))
    gates: Mapped[list[Any] | None] = mapped_column(JSON)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reference_sample: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    duration_ms: Mapped[float | None] = mapped_column(Float)


# --------------------------------------------------------------------------- scoring


class ScoringRun(Base):
    __tablename__ = "scoring_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("dataset_imports.id", ondelete="CASCADE"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    severity_rules_version: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None]
    events_total: Mapped[int] = mapped_column(Integer, default=0)
    events_scored: Mapped[int] = mapped_column(Integer, default=0)
    events_rejected: Mapped[int] = mapped_column(Integer, default=0)
    suspicious: Mapped[int] = mapped_column(Integer, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    label_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    scoring_run_id: Mapped[int] = mapped_column(ForeignKey("scoring_runs.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    predicted_class: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[float | None] = mapped_column(Float)
    score_kind: Mapped[str | None] = mapped_column(String(60))
    threshold: Mapped[float | None] = mapped_column(Float)
    decision_rule: Mapped[str] = mapped_column(String(200))
    preprocessing_version: Mapped[str] = mapped_column(String(100))
    inferred_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    __table_args__ = (UniqueConstraint("event_id", "model_version_id"),)


class PredictionExplanation(Base):
    """A SHAP explanation of one stored prediction, computed from the exact artifact that made it.

    Kept so an analyst's later review sees the same attribution they based a decision on. It records
    the artifact hash and library version, and the additivity error that was checked when it was made.
    """

    __tablename__ = "prediction_explanations"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id", ondelete="CASCADE"), unique=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    preprocessing_version: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(String(100))
    library: Mapped[str] = mapped_column(String(60))
    output_space: Mapped[str] = mapped_column(String(20))
    target_class: Mapped[str] = mapped_column(String(200))
    base_value: Mapped[float] = mapped_column(Float)
    model_output: Mapped[float] = mapped_column(Float)
    additivity_error: Mapped[float] = mapped_column(Float)
    contributions: Mapped[list[Any]]
    limitations: Mapped[list[Any]]
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)


# --------------------------------------------------------------------------- alerts / incidents


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), index=True)  # open | investigating | closed
    disposition: Mapped[str] = mapped_column(String(30), default="undetermined")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    closed_at: Mapped[datetime | None]


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id", ondelete="CASCADE"), unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("dataset_imports.id", ondelete="CASCADE"), index=True)
    predicted_class: Mapped[str] = mapped_column(String(200))
    score: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    severity_rule: Mapped[str] = mapped_column(String(100))
    group_key: Mapped[str] = mapped_column(String(600), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class AlertStatusChange(Base):
    __tablename__ = "alert_status_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class AlertNote(Base):
    __tablename__ = "alert_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class IncidentNote(Base):
    __tablename__ = "incident_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20), default="note")  # note | evidence | decision
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# --------------------------------------------------------------------------- audit


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    client_ip: Mapped[str | None] = mapped_column(String(64))


Index("ix_alerts_status_severity", Alert.status, Alert.severity)
Index("ix_audit_logs_action_at", AuditLog.action, AuditLog.at)  # login throttling and retention scans


# --------------------------------------------------------------------------- drift


class DriftAnalysis(Base):
    """One comparison of a current data window against a reference window."""

    __tablename__ = "drift_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), index=True)
    reference_spec: Mapped[dict[str, Any]]
    current_spec: Mapped[dict[str, Any]]
    window_spec: Mapped[dict[str, Any]]
    features: Mapped[list[Any]]
    config: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(String(20), index=True)
    n_reference: Mapped[int | None] = mapped_column(Integer)
    n_current: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    overall: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    timings: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]


class DriftWindow(Base):
    __tablename__ = "drift_windows"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("drift_analyses.id", ondelete="CASCADE"), index=True)
    window_index: Mapped[int] = mapped_column(Integer)
    start: Mapped[datetime | None]
    end: Mapped[datetime | None]
    n_events: Mapped[int] = mapped_column(Integer)
    max_feature_psi: Mapped[float | None] = mapped_column(Float)
    drifted_features: Mapped[list[Any]] = mapped_column(default=list)
    features: Mapped[dict[str, Any]]
    prediction: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    performance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("analysis_id", "window_index"),)


class DriftEvent(Base):
    """A detected drift signal. Never triggers retraining or promotion by itself."""

    __tablename__ = "drift_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("drift_analyses.id", ondelete="CASCADE"), index=True)
    drift_type: Mapped[str] = mapped_column(String(20), index=True)  # feature | prediction | performance | concept
    signal: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(20))
    rule: Mapped[str] = mapped_column(Text)
    window_index: Mapped[int | None] = mapped_column(Integer)
    detected_at: Mapped[datetime | None]
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), index=True)  # new | acknowledged | investigating | closed
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class DriftEventNote(Base):
    __tablename__ = "drift_event_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("drift_events.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20), default="note")  # note | status
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
