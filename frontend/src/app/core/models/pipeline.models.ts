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
  suggested_fix?: Record<string, any> | null;
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
  actual_duration_seconds?: number | null;
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
  agent_id: string;
  agent_name: string;
  trigger: 'AUTOMATIC' | 'MANUAL';
  success: boolean;
  job_id?: number | null;
  agent_execution_id?: string | null;
  status: AgentExecutionStatus;
  message?: string | null;
  http_status?: string | null;
  target_file?: string | null;
  submitted_at?: string | null;
  completed_at?: string | null;
  output?: any;
}

/** One entry of the configured multi-agent roster, served by the API. */
export interface ConfiguredAgent {
  id: string;
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
  agent_executions: Record<string, AgentExecution>;
}

export interface AgentStatusResponse {
  batch_id: string;
  executions: Record<string, AgentExecution>;
  artifacts: {
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

/** Artefact kinds exposed by GET /batches/{id}/artifacts/{kind}. */
export type ArtifactKind =
  | 'statement'
  | 'anomaly_candidates'
  | 'matched'
  | 'unmatched_bank'
  | 'outstanding_gl'
  | 'recon_exceptions'
  | 'sla_metrics';
