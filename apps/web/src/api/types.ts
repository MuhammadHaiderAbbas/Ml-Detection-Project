// Mirrors the FastAPI response models in src/adaptive_ids/api/schemas.py.

export type Role = "admin" | "analyst";
export interface User { id: number; username: string; role: Role; is_active: boolean; created_at: string; last_login_at: string | null }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export type AlertStatus = "new" | "investigating" | "resolved" | "false_positive";
export type Severity = "low" | "medium" | "high" | "critical";

export interface ImportRecord {
  id: number; import_uid: string; dataset_name: string; dataset_version: string; provenance: string;
  data_source: string | null; original_filename: string; file_sha256: string | null; file_bytes: number | null;
  schema_id: string; schema_hash: string; column_mapping: Record<string, string>; duplicate_policy: string;
  status: string; total_rows: number; accepted_rows: number; rejected_rows: number; duplicate_rows: number;
  duplicates_dropped: number; rejection_reason_counts: Record<string, number>; label_distribution: Record<string, number>;
  errors: string[]; warnings: string[]; created_at: string; started_at: string | null; completed_at: string | null;
}
export interface RejectedRow { row_number: number; reasons: string }
export interface SchemaInfo { schema_id: string; name: string; version: string; status: string; n_features: number; label_column: string | null; context_columns: string[]; notes: string }
export interface Preview { columns: string[]; rows: Record<string, string>[]; compatibility: { missing: string[]; extra: string[]; duplicated: string[] } }

export interface EventRecord {
  id: number; import_id: number; row_number: number; event_key: string | null; occurred_at: string | null;
  source: string | null; destination: string | null; dataset_label: string | null;
  features: Record<string, number | null>; context: Record<string, string | null>;
}
export interface Prediction {
  id: number; scoring_run_id: number; event_id: number; model_version_id: number; predicted_class: string | null;
  score: number | null; score_kind: string | null; threshold: number | null; decision_rule: string;
  preprocessing_version: string; inferred_at: string; status: string; error: string | null; is_suspicious: boolean;
}
export interface TrafficRow { event: EventRecord; prediction: Prediction | null }

export interface ModelVersion {
  id: number; version_id: string; name: string; model_type: string; artifact_sha256: string; artifact_format: string;
  provenance: string; feature_schema_id: string; preprocessing_version: string; positive_class: string | null;
  threshold: number | null; benign_label: string | null; training_dataset: string | null; status: string;
  source_run: string | null; created_at: string; approved_at: string | null; activated_at: string | null;
}
export interface Metrics {
  n_scored: number; accuracy: number; labels: string[];
  averages: Record<"macro" | "weighted", { precision: number; recall: number; f1: number }>;
  per_class: Record<string, { precision: number; recall: number; f1: number; support: number }>;
  confusion_matrix: { labels: string[]; rows_true_cols_pred: number[][] };
  binary_attack_vs_benign?: { benign_label: string; precision: number | null; recall_detection_rate: number | null; f1: number | null; false_positive_rate: number | null; false_negative_rate: number | null; tp: number; fp: number; tn: number; fn: number };
  basis?: string;
}
export interface ModelDetail extends ModelVersion {
  training_config: Record<string, unknown>; software_versions: Record<string, string | null>;
  evaluation: { experiment_id?: string; provenance?: string; result_sha256?: string; split_method?: string;
    dataset?: Record<string, unknown>; test?: Metrics | null; limitations?: string[] };
  approval_evaluation_id: number | null; approval_override: boolean; restore_check: RestoreCheck | null;
  has_reference_sample: boolean;
}
export interface RestoreCheck {
  ok: boolean; partial: boolean; checked_at: string; mismatches: number | null; sample_size: number;
  checks: { id: string; passed: boolean | null; detail: string }[];
}

export type Verdict = "pass" | "fail" | "insufficient_evidence";
export interface Gate { id: string; kind: "validity" | "performance"; passed: boolean | null; value: number | null; threshold: number | null; detail: string }
export type GovMetric = "attack_recall" | "false_positive_rate" | "precision" | "f1" | "accuracy";
export type GovMetrics = Record<GovMetric, number | null> & { confusion: { tp: number; fp: number; tn: number; fn: number } };
export interface Evaluation {
  id: number; model_version_id: number; baseline_model_version_id: number | null; import_id: number;
  protocol_version: string; status: string; verdict: Verdict | null; error: string | null;
  data: { import_id: number; dataset: string; provenance: string; file_sha256: string | null; schema_id: string; labelled_events: number;
    candidate: { version_id: string; provenance: string }; baseline: { version_id: string; provenance: string } | null; truth: string };
  created_by_id: number | null; created_at: string; started_at: string | null; completed_at: string | null; duration_ms: number | null;
}
export interface EvaluationDetail extends Evaluation {
  protocol: Record<string, number | string | null>;
  gates: Gate[] | null;
  results: {
    verdict: Verdict; baseline_present: boolean; basis: string;
    metrics: { candidate: GovMetrics; baseline?: GovMetrics };
    differences: Partial<Record<GovMetric, { difference: number | null; ci_low: number | null; ci_high: number | null; better_when: "higher" | "lower" }>>;
    mcnemar: { candidate_only_correct: number; baseline_only_correct: number; method: string; p_value: number; significant: boolean; alpha: number } | null;
    counts: { labelled_events: number; compared_events: number; attack_events: number; benign_events: number; failed_prediction_rate: Record<string, number> };
  } | null;
}
export interface ModelHistory { from_status: string | null; to_status: string; changed_by_id: number | null; changed_at: string; reason: string | null }
export interface ExperimentRun { run_name: string; experiment_id: string | null; provenance: string | null; model_version: string | null; test_accuracy: number | null; registered: boolean }

export interface ScoringRun {
  id: number; import_id: number; model_version_id: number; status: string; severity_rules_version: string | null;
  started_at: string; completed_at: string | null; events_total: number; events_scored: number; events_rejected: number;
  suspicious: number; alerts_created: number; duration_ms: number | null; label_metrics: Metrics | null; error: string | null;
}

export interface Alert {
  id: number; prediction_id: number; event_id: number; model_version_id: number; import_id: number;
  predicted_class: string; score: number | null; severity: Severity; severity_rule: string; group_key: string;
  status: AlertStatus; assignee_id: number | null; incident_id: number | null; created_at: string; updated_at: string;
}
export interface AlertDetail {
  alert: Alert; assignee: string | null; event: EventRecord; prediction: Prediction; model: ModelVersion;
  incident_id: number | null; notes: { id: number; author: string | null; body: string; created_at: string }[];
  history: { from_status: string | null; to_status: string; changed_by: string | null; changed_at: string; note: string | null }[];
  related_alerts: Alert[]; interpretation: string;
}
export interface AlertGroup { group_key: string; predicted_class: string; source: string; destination: string; alerts: number; max_score: number | null; first_seen: string; last_seen: string }

export type Disposition = "undetermined" | "confirmed_attack" | "benign" | "false_positive" | "inconclusive";
export interface Incident { id: number; title: string; status: "open" | "investigating" | "closed"; disposition: Disposition; owner_id: number | null; summary: string | null; created_by_id: number | null; created_at: string; updated_at: string; closed_at: string | null }
export interface IncidentDetail {
  incident: Incident; owner: string | null; alerts: Alert[];
  notes: { id: number; author: string | null; kind: string; body: string; created_at: string }[];
  timeline: { at: string; kind: string; actor: string | null; text: string }[]; sources: string[]; destinations: string[];
}

export interface AuditEntry { id: number; at: string; actor_id: number | null; actor_name: string | null; action: string; entity_type: string | null; entity_id: string | null; details: Record<string, unknown>; client_ip: string | null }

export interface DashboardSummary {
  demo_data_present: boolean; provenances_present: string[];
  events_processed: number; events_scored: number; events_rejected_at_inference: number; suspicious_predictions: number;
  alerts_by_status: Record<AlertStatus, number>; alerts_by_severity: Record<string, number>; high_priority_open_alerts: number;
  incidents_by_disposition: Record<string, number>; confirmed_attacks: number | null; confirmed_attacks_note: string | null;
  active_model: { id: number; version_id: string; provenance: string; activated_at: string } | null;
  last_approved_evaluation: { model_id: number; version_id: string; approved_at: string; experiment_id: string | null } | null;
  processing_latency: { scoring_run_id: number; ms_per_event: number; events: number; duration_ms: number } | null;
  ingestion: { recent: { id: number; dataset: string; status: string; provenance: string; created_at: string }[]; failed_in_range: number };
  drift_monitoring: { status: string; note?: string; open_events: Record<string, number>; latest_analysis?: { id: number; name: string; completed_at: string } };
  top_sources: { value: string; alerts: number }[]; top_destinations: { value: string; alerts: number }[];
  recent_alert_ids: number[]; definitions: Record<string, string>;
}
export interface TimelinePoint { bucket_start: string; events: number; suspicious: number; not_flagged: number; unscored: number }
export interface Timeline { bucket: string; basis: string; points: TimelinePoint[]; events_without_timestamp: number; definitions: Record<string, string> }
export interface SeverityRules { version: string; description: string; rules: { rule_id: string; classes: string[]; min_score?: number; severity: Severity }[]; default: { rule_id: string; severity: Severity } }
export interface Health { status: string; version: string; database: string }

// --- drift ---------------------------------------------------------------------
export type DriftSeverity = "none" | "moderate" | "major" | "insufficient_data";
export interface DriftVerdict { status: "detected" | "not_detected" | "insufficient_data" | "not_assessable"; severity?: DriftSeverity; events?: number; reason?: string }
export interface DriftFeatureStat {
  n_ref: number; n_cur: number; psi: number | null; ks_d: number | null; ks_p: number | null; ks_p_adj: number | null;
  ref_mean?: number; cur_mean?: number; ref_median?: number; cur_median?: number; severity: DriftSeverity;
  bins?: { edges: number[]; ref: number[]; cur: number[] };
}
export interface DriftSpecOut { import_id: number; since: string | null; until: string | null; dataset: string; provenance: string; schema_id: string }
export interface DriftAnalysis {
  id: number; name: string; model_version_id: number | null; reference_spec: DriftSpecOut; current_spec: DriftSpecOut;
  window_spec: { mode: string; size?: number; bucket?: string }; features: string[]; config: Record<string, number | string>;
  status: string; n_reference: number | null; n_current: number | null; error: string | null;
  summary: null | { feature: DriftVerdict; prediction: DriftVerdict; performance: DriftVerdict; concept: DriftVerdict;
    n_reference: number; n_current: number; n_windows: number; features_tested: number; features_drifted: string[]; interpretation: string };
  timings: Record<string, number> | null; created_at: string; completed_at: string | null;
}
export interface DriftAnalysisDetail extends DriftAnalysis {
  overall: null | {
    features: Record<string, DriftFeatureStat>;
    prediction: null | { psi: number | null; chi2_p: number | null; js_distance: number | null; severity: DriftSeverity; categories: string[]; ref_props?: number[]; cur_props?: number[]; suspicious_rate_ref?: number | null; suspicious_rate_cur?: number | null };
    performance: { reference: { n_labelled: number; error_rate: number | null }; current: { n_labelled: number; error_rate: number | null }; severity: DriftSeverity; error_rate_change: number | null };
    streaming: Record<string, { position: number; mean_before: number | null; mean_after: number | null; direction: string | null }[]>;
  };
}
export interface DriftWindow {
  window_index: number; start: string | null; end: string | null; n_events: number; max_feature_psi: number | null; drifted_features: string[];
  features: Record<string, { psi: number | null; ks_d: number | null; ks_p_adj: number | null; severity: DriftSeverity; n_cur: number }>;
  prediction: null | { psi: number | null; severity: DriftSeverity; suspicious_rate_cur: number | null; n_cur: number };
  performance: null | { n_labelled: number; error_rate: number | null; severity: DriftSeverity };
}
export interface DriftEvent {
  id: number; analysis_id: number; drift_type: "feature" | "prediction" | "performance" | "concept"; signal: string; severity: DriftSeverity;
  rule: string; window_index: number | null; detected_at: string | null; details: Record<string, unknown>;
  status: "new" | "acknowledged" | "investigating" | "closed"; created_at: string; updated_at: string;
}
export interface DriftEventDetail { event: DriftEvent; notes: { id: number; author: string | null; kind: string; body: string; created_at: string }[]; interpretation: string }
