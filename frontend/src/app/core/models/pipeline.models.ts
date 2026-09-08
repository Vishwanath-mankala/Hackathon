/**
 * TypeScript interfaces for the Batch Pipeline, Structural Gate,
 * Agentic Anomaly Detection, Time Estimation, and Publishing.
 *
 * Mirrors backend/app/models/pipeline_models.py — every field here is served
 * by the API; nothing is synthesised client-side.
 */

export interface CheckDetail {
  passed: boolean;
  detail: string;
}

export interface StructuralGateDetails {
  passed: boolean;
  file: string;
  declared_record_count?: number | null;
  actual_record_count: number;
  declared_control_total?: number | null;
  actual_control_total: number;
  checks: { [key: string]: CheckDetail };
  reasons: string[];
  quarantined: boolean;
  quarantine_path?: string | null;
}

export interface AnomalyItem {
  id: string;
  row_index: number;
  external_txn_id: string;
  account: string;
  amount?: number | null;
  raw_amount?: string | null;
  booking_date?: string | null;
  error_type: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  category: 'STRUCTURAL' | 'SEMANTIC' | 'TIMING' | 'REFERENTIAL' | string;
  description: string;
  auto_remediable: boolean;
  /**
   * Only present when a correction is derivable from the row itself and applying
   * it is lossless. Escalated rows carry null — there is nothing safe to propose.
   */
  suggested_fix?: Record<string, any> | null;
  /** Columns the analyst must fill in to resolve this by OVERRIDE. */
  override_fields: string[];
  status: 'DETECTED' | 'AUTO_REMEDIATED' | 'ESCALATED' | 'HUMAN_RESOLVED' | 'QUARANTINED';
  remediation_notes?: string | null;
  confidence_score: number;
}

export interface HumanResolveRequest {
  action: 'APPROVE' | 'OVERRIDE' | 'QUARANTINE';
  override_values?: Record<string, any> | null;
  analyst_notes?: string | null;
}

export interface TimeEstimate {
  batch_id: string;
  file_size_bytes: number;
  file_size_mb: number;
  total_records: number;
  anomaly_count: number;
  throughput_records_per_sec: number;
  estimated_parse_time_sec: number;
  estimated_gate_time_sec: number;
  estimated_rule_time_sec: number;
  estimated_anomaly_triage_sec: number;
  estimated_gl_match_sec: number;
  total_estimated_seconds: number;
  eta_timestamp: string;
  sla_target_seconds: number;
  sla_status: 'ON_TRACK' | 'AT_RISK' | 'BREACHED';
  completed_at?: string | null;
  /** Wall-clock, including analyst queue wait. */
  actual_duration_seconds?: number | null;
  /** Machine work vs human wait, kept separate. */
  estimated_machine_seconds: number;
  estimated_queue_wait_sec: number;
  machine_seconds?: number | null;
  queue_wait_seconds?: number | null;
  /** DEFAULT = declared formula constants; HISTORY = derived from the run history. */
  calibration_source: 'DEFAULT' | 'HISTORY' | string;
  calibration_sample_size: number;
  calibration_factor: number;
  baseline_throughput_used: number;
}

export type ForecastStatus = 'PENDING' | 'RECEIVED' | 'TIMED_OUT' | 'UNPARSEABLE' | 'SKIPPED' | 'FAILED';

/** The Stage 1 forecast agent's prediction, captured server-side and scored after the run. */
export interface BatchForecast {
  status: ForecastStatus | string;
  forecast_seconds?: number | null;
  p10_seconds?: number | null;
  p90_seconds?: number | null;
  confidence?: string | null;
  breach_probability_pct?: number | null;
  expected_escalation_rate_pct?: number | null;
  dominant_uncertainty?: string | null;
  comparable_batches: string[];
  reasoning?: string | null;
  dashboard_line?: string | null;
  agent_execution_id?: string | null;
  issued_at?: string | null;
  received_at?: string | null;
  message?: string | null;
  /** Signed, vs measured wall_seconds. Positive = over-estimated. */
  error_pct?: number | null;
}

export interface RunHistoryRow {
  batch_id: string;
  completed_at: string;
  source: string;
  filename: string;
  outcome: string;
  provenance: 'LIVE' | 'BACKFILL_SLA_METRICS' | string;
  gate_passed: boolean;
  record_count: number;
  file_size_mb: number;
  anomaly_count: number;
  escalated_count: number;
  matched_count: number;
  estimate_at_ingest_sec?: number | null;
  estimate_final_sec?: number | null;
  machine_seconds?: number | null;
  queue_wait_seconds?: number | null;
  wall_seconds?: number | null;
  throughput_actual_rec_per_sec?: number | null;
  local_error_pct?: number | null;
  eligible_for_calibration: boolean;
  forecast_seconds?: number | null;
  forecast_error_pct?: number | null;
  forecast_status?: string | null;
}

export interface CalibrationSummary {
  source: 'DEFAULT' | 'HISTORY' | string;
  sample_size: number;
  min_runs_required: number;
  baseline_throughput: number;
  default_throughput: number;
  queue_wait_per_escalation_sec: number;
  default_queue_wait_sec: number;
  residual_factor: number;
  total_runs_recorded: number;
  forecasts_received: number;
  forecast_median_abs_error_pct?: number | null;
  local_median_abs_error_pct?: number | null;
}

export interface MeasuredActual {
  machine_seconds?: number | null;
  queue_wait_seconds?: number | null;
  wall_seconds?: number | null;
  still_parked: boolean;
}

/** GET /batches/{id}/forecast */
export interface ForecastComparison {
  batch_id: string;
  stage: string;
  local_estimate: TimeEstimate;
  agent_forecast?: BatchForecast | null;
  execution?: AgentExecution | null;
  actual?: MeasuredActual | null;
  calibration: CalibrationSummary;
}

/** GET /run-history */
export interface RunHistoryResponse {
  rows: RunHistoryRow[];
  calibration: CalibrationSummary;
  file?: string | null;
}

export interface GLMatchSummary {
  total_eligible_rows: number;
  matched_count: number;
  tier_1_exact: number;
  tier_2_date: number;
  tier_3_ref: number;
  tier_4_amount: number;
  unmatched_reconciling_items: number;
  outstanding_gl_items: number;
  ambiguous_count: number;
  match_rate_pct: number;
}

export interface PublishEvent {
  event_id: string;
  batch_id: string;
  published_at: string;
  channel: string;
  status: string;
  summary: Record<string, any>;
  delivered: boolean;
}

/** Pipeline stage that owns an automatic agent dispatch. */
export type AgentStageKey =
  | 'STAGE_1_FORECAST'
  | 'STAGE_1_EXTRACTION'
  | 'STAGE_4_ANOMALY'
  | 'STAGE_6_RECON'
  | 'STAGE_7_SLA'
  | 'NON_PIPELINE';

export type AgentExecutionStatus =
  | 'PENDING'
  | 'SUBMITTING'
  | 'SUBMITTED'
  | 'IN_PROGRESS'
  | 'SUCCESS'
  | 'COMPLETED'
  | 'FAILED'
  | 'ERROR'
  | 'CANCELLED'
  | 'SKIPPED';

export interface AgentExecution {
  stage: AgentStageKey | string;
  /** Null when the stage has no CREWAI_AGENT_*_ID configured. */
  agent_id: string | null;
  agent_name: string;
  trigger: 'AUTOMATIC' | 'MANUAL';
  success: boolean;
  job_id?: number | null;
  agent_execution_id?: string | null;
  status: AgentExecutionStatus;
  message?: string | null;
  http_status?: string | null;
  /** Primary artefact; names the zip. */
  target_file?: string | null;
  /** Every member of the zip the agent was handed. */
  bundled_files?: string[];
  submitted_at?: string | null;
  completed_at?: string | null;
  output?: any;
  forecast_captured?: boolean;
}

/** One entry of the configured multi-agent roster, served by the API. */
export interface ConfiguredAgent {
  /** Null until the CREWAI_AGENT_*_ID env var is set — there is no default. */
  id: string | null;
  configured: boolean;
  key: string;
  stage_key: AgentStageKey | string;
  name: string;
  role: string;
  stage: string;
  description: string;
  input_artifact: string;
  auto_dispatch: boolean;
  human_intervention: boolean;
  is_default: boolean;
}

export interface BatchRecord {
  batch_id: string;
  filename: string;
  file_size_bytes: number;
  source: string;
  stage: string;
  gate_passed?: boolean | null;
  total_records: number;
  valid_records_count: number;
  anomaly_count: number;
  auto_remediated_count: number;
  escalated_count: number;
  quarantined_rows_count: number;
  matched_count: number;
  unmatched_count: number;
  created_at: string;
  updated_at: string;
  time_estimate?: TimeEstimate | null;
  gate_details?: StructuralGateDetails | null;
  gl_summary?: GLMatchSummary | null;
  published: boolean;
  publish_event?: PublishEvent | null;
  batch_file_path?: string | null;
  anomaly_file_path?: string | null;
  matched_file_path?: string | null;
  unmatched_file_path?: string | null;
  outstanding_file_path?: string | null;
  ambiguous_file_path?: string | null;
  sla_metrics_file_path?: string | null;
  forecast_input_file_path?: string | null;
  run_history_file_path?: string | null;
  machine_seconds?: number | null;
  queue_wait_seconds?: number | null;
  wall_seconds?: number | null;
  estimate_at_ingest_sec?: number | null;
  agent_forecast?: BatchForecast | null;
  agent_executions: Record<string, AgentExecution>;
}

export interface AgentStatusResponse {
  batch_id: string;
  executions: Record<string, AgentExecution>;
  artifacts: {
    forecast_input: boolean;
    run_history: boolean;
    anomaly_candidates: boolean;
    recon_exceptions: boolean;
    sla_metrics: boolean;
    raw_statement: boolean;
  };
}

export interface BatchReconResponse {
  batch_id: string;
  summary?: GLMatchSummary | null;
  matched_sample: any[];
  unmatched_sample: any[];
  ambiguous_sample: any[];
  artifacts: Record<string, string | null>;
}

export interface IngestionResponse {
  batch_id: string;
  filename: string;
  message: string;
  stage: string;
  record_count: number;
  gate_passed: boolean;
  quarantined: boolean;
  time_estimate?: TimeEstimate | null;
}

export interface PipelineOverview {
  total_batches: number;
  active_batches: number;
  completed_batches: number;
  quarantined_batches: number;
  total_records_processed: number;
  sla_breaches: number;
  at_risk_count: number;
  batches: BatchRecord[];
}

/** Actions valid for an ambiguous multi-candidate tie. */
export type AmbiguousSignoffAction =
  | 'CONFIRM_PROVISIONAL'
  | 'SELECT_ALTERNATIVE'
  | 'LEAVE_UNSETTLED';

/** Actions valid for any other reconciliation line. */
export type AttestationAction = 'ATTEST_REVIEWED' | 'FLAG_FOR_INVESTIGATION';

export type SignoffAction = AmbiguousSignoffAction | AttestationAction;

/** One analyst decision on one reconciliation line. Append-only. */
export interface AuditSignoff {
  signoff_id: string;
  batch_id: string;
  dataset: string;
  row_key: string;
  action: SignoffAction | string;
  chosen_internal_txn_id?: string | null;
  analyst: string;
  analyst_notes?: string | null;
  signed_at: string;
  /** signoff_id this decision replaces; null for a first sign-off. */
  supersedes?: string | null;
}

export interface SignoffRequest {
  row_key: string;
  action: SignoffAction | string;
  chosen_internal_txn_id?: string | null;
  analyst?: string | null;
  analyst_notes?: string | null;
}

/** Artefact kinds exposed by GET /batches/{id}/artifacts/{kind}. */
export type ArtifactKind =
  | 'statement'
  | 'forecast_input'
  | 'run_history'
  | 'anomaly_candidates'
  | 'matched'
  | 'unmatched_bank'
  | 'outstanding_gl'
  | 'recon_exceptions'
  | 'sla_metrics';
