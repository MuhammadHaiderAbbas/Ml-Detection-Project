"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- auth / users -------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORM):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_hours: int
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "analyst"]


class UserActive(BaseModel):
    is_active: bool


# --- imports ------------------------------------------------------------------


class SchemaOut(BaseModel):
    schema_id: str
    name: str
    version: str
    status: str
    n_features: int
    label_column: str | None
    context_columns: list[str]
    notes: str


class ImportOut(ORM):
    id: int
    import_uid: str
    dataset_name: str
    dataset_version: str
    provenance: str
    data_source: str | None
    original_filename: str
    file_sha256: str | None
    file_bytes: int | None
    schema_id: str
    schema_hash: str
    column_mapping: dict[str, Any]
    column_mapping_hash: str
    duplicate_policy: str
    status: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    duplicates_dropped: int
    rejection_reason_counts: dict[str, Any]
    label_distribution: dict[str, Any]
    errors: list[Any]
    warnings: list[Any]
    created_by_id: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RejectedRowOut(ORM):
    row_number: int
    reasons: str


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    compatibility: dict[str, list[str]]


# --- events / predictions -----------------------------------------------------


class PredictionOut(ORM):
    id: int
    scoring_run_id: int
    event_id: int
    model_version_id: int
    predicted_class: str | None
    score: float | None
    score_kind: str | None
    threshold: float | None
    decision_rule: str
    preprocessing_version: str
    inferred_at: datetime
    status: str
    error: str | None
    is_suspicious: bool


class EventOut(ORM):
    id: int
    import_id: int
    row_number: int
    event_key: str | None
    occurred_at: datetime | None
    source: str | None
    destination: str | None
    dataset_label: str | None = Field(
        description="Label supplied in the imported file (ground truth for evaluation only); not an analyst decision."
    )
    features: dict[str, Any]
    context: dict[str, Any]


class TrafficRow(BaseModel):
    event: EventOut
    prediction: PredictionOut | None


class EventWithPredictions(BaseModel):
    event: EventOut
    predictions: list[PredictionOut]


# --- models -------------------------------------------------------------------


class ModelOut(ORM):
    id: int
    version_id: str
    name: str
    model_type: str
    artifact_sha256: str
    artifact_format: str
    provenance: str
    feature_schema_id: str
    preprocessing_version: str
    positive_class: str | None
    threshold: float | None
    benign_label: str | None
    training_dataset: str | None
    status: str
    source_run: str | None
    created_at: datetime
    approved_at: datetime | None
    activated_at: datetime | None


class ModelDetail(ModelOut):
    training_config: dict[str, Any]
    software_versions: dict[str, Any]
    evaluation: dict[str, Any]


class ModelStatusChangeOut(ORM):
    from_status: str | None
    to_status: str
    changed_by_id: int | None
    changed_at: datetime
    reason: str | None


class RegisterRun(BaseModel):
    run_name: str = Field(min_length=1, max_length=200)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class RunOut(BaseModel):
    run_name: str
    experiment_id: str | None
    provenance: str | None
    model_version: str | None
    test_accuracy: float | None
    registered: bool


# --- scoring ------------------------------------------------------------------


class ScoreRequest(BaseModel):
    model_version_id: int | None = Field(None, description="Defaults to the active model.")


class ScoringRunOut(ORM):
    id: int
    import_id: int
    model_version_id: int
    status: str
    severity_rules_version: str | None
    started_at: datetime
    completed_at: datetime | None
    events_total: int
    events_scored: int
    events_rejected: int
    suspicious: int
    alerts_created: int
    duration_ms: float | None
    label_metrics: dict[str, Any] | None
    error: str | None


# --- alerts -------------------------------------------------------------------


class AlertOut(ORM):
    id: int
    prediction_id: int
    event_id: int
    model_version_id: int
    import_id: int
    predicted_class: str
    score: float | None
    severity: str
    severity_rule: str
    group_key: str
    status: str
    assignee_id: int | None
    incident_id: int | None
    created_at: datetime
    updated_at: datetime


class AlertNoteOut(BaseModel):
    id: int
    author: str | None
    body: str
    created_at: datetime


class AlertHistoryOut(BaseModel):
    from_status: str | None
    to_status: str
    changed_by: str | None
    changed_at: datetime
    note: str | None


class AlertDetail(BaseModel):
    alert: AlertOut
    assignee: str | None
    event: EventOut
    prediction: PredictionOut
    model: ModelOut
    incident_id: int | None
    notes: list[AlertNoteOut]
    history: list[AlertHistoryOut]
    related_alerts: list[AlertOut]
    interpretation: str = (
        "This alert records a model suspicion. The score is an uncalibrated model output and the severity is a "
        "triage priority from configured rules; neither confirms an attack."
    )


class AlertGroupOut(BaseModel):
    group_key: str
    predicted_class: str
    source: str
    destination: str
    alerts: int
    max_score: float | None
    first_seen: datetime
    last_seen: datetime


class StatusChange(BaseModel):
    status: Literal["new", "investigating", "resolved", "false_positive"]
    note: str | None = Field(None, max_length=10_000)


class AssignBody(BaseModel):
    assignee_id: int | None


class NoteBody(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


# --- incidents ----------------------------------------------------------------


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = Field(None, max_length=20_000)
    alert_ids: list[int] = Field(default_factory=list, max_length=10_000)
    owner_id: int | None = None


class IncidentUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    summary: str | None = Field(None, max_length=20_000)
    owner_id: int | None = None
    status: Literal["open", "investigating", "closed"] | None = None
    disposition: Literal["undetermined", "confirmed_attack", "benign", "false_positive", "inconclusive"] | None = None
    decision_note: str | None = Field(None, max_length=10_000)


class LinkAlerts(BaseModel):
    alert_ids: list[int] = Field(min_length=1, max_length=10_000)


class IncidentNoteBody(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    kind: Literal["note", "evidence"] = "note"


class IncidentOut(ORM):
    id: int
    title: str
    status: str
    disposition: str
    owner_id: int | None
    summary: str | None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class IncidentNoteOut(BaseModel):
    id: int
    author: str | None
    kind: str
    body: str
    created_at: datetime


class TimelineItem(BaseModel):
    at: datetime
    kind: str
    actor: str | None
    text: str


class IncidentDetail(BaseModel):
    incident: IncidentOut
    owner: str | None
    alerts: list[AlertOut]
    notes: list[IncidentNoteOut]
    timeline: list[TimelineItem]
    sources: list[str]
    destinations: list[str]


# --- audit --------------------------------------------------------------------


class AuditOut(ORM):
    id: int
    at: datetime
    actor_id: int | None
    actor_name: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]
    client_ip: str | None
