/**
 * TypeScript models and interfaces for Reconciliation & Feed Processing API
 */

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  uptime_seconds: number;
  timestamp: string;
}

export interface RootDiscoveryResponse {
  message: string;
  docs: string;
  health: string;
  endpoints: {
    feed: string;
    gate: string;
    recon: string;
    diagnostics: string;
  };
}

export interface ManifestRecord {
  sequence: number;
  file: string;
  row_count: number;
  declared_record_count: number;
  declared_control_total: number;
  min_booking_date?: string | null;
  max_booking_date?: string | null;
}

export interface SplitReconResponse {
  message: string;
  total_rows_loaded: number;
  cache_rows: number;
  ingest_rows: number;
  cache_path: string;
  batches_dir: string;
  manifest_path: string;
  batch_count: number;
  manifest: ManifestRecord[];
}

export interface ManifestResponse {
  manifest_path: string;
  total_batches: number;
  total_declared_records: number;
  total_declared_amount: number;
  records: ManifestRecord[];
}

export interface BatchesListResponse {
  batches_dir: string;
  count: number;
  files: string[];
}

export interface CheckDetail {
  passed: boolean;
  detail: string;
}

export interface GateResultSchema {
  file: string;
  passed: boolean;
  checks: { [key: string]: CheckDetail };
  reasons: string[];
}

export interface GateCheckRequest {
  batch_filename: string;
  declared_record_count?: number | null;
  declared_control_total?: number | null;
  expected_encoding?: string;
}

export interface GateAllRequest {
  batches_dir?: string | null;
  manifest_path?: string | null;
  quarantine_dir?: string | null;
}

export interface GateSummaryResponse {
  total_batches: number;
  passed_count: number;
  failed_count: number;
  quarantined_count: number;
  quarantine_dir?: string | null;
  results: GateResultSchema[];
}

export interface MatchConfigSchema {
  date_tolerance_days: number;
  amount_abs_tolerance: number;
  amount_pct_tolerance: number;
  direction_mode: 'ignore' | 'same' | 'opposite';
}

export interface ReconRunRequest {
  cache_path?: string | null;
  manifest_path?: string | null;
  batches_dir?: string | null;
  out_dir?: string | null;
  config: MatchConfigSchema;
  single_batch?: string | null;
}

export interface ReconRunResponse {
  message: string;
  total_matched: number;
  tier_breakdown: { [key: string]: number };
  cache_remaining_count: number;
  ingest_unmatched_count: number;
  ambiguous_count: number;
  out_dir: string;
  output_files: {
    matched: string;
    unmatched_cache: string;
    unmatched_ingest: string;
    ambiguous: string;
  };
}

export interface PaginatedQueryResponse<T = Record<string, any>> {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  items: T[];
}

export interface AmbiguityDiagnosisRequest {
  results_dir?: string | null;
}

export interface AmbiguityDiagnosisResponse {
  total_ambiguous: number;
  avg_candidates: number;
  max_candidates: number;
  ambiguity_by_tier: { [key: string]: number };
  resolved_by_reference?: number | null;
  resolved_by_reference_pct?: number | null;
  top_accounts: { [account: string]: number };
  top_amounts: { [amount: string]: number };
  top_amounts_concentration_pct: number;
  is_concentrated: boolean;
  diagnostic_assessment: string;
  output_detail_csv: string;
}

export interface CorruptBatchRequest {
  batch_filename: string;
  mode: 'truncate' | 'dropped_row' | 'duplicate_row' | 'tampered_amount' | 'missing_column' | 'bad_encoding';
}

export interface CorruptBatchResponse {
  message: string;
  file: string;
  mode: string;
  backup_path: string;
}

export interface RestoreBatchRequest {
  batch_filename: string;
}

export interface RestoreBatchResponse {
  message: string;
  file: string;
  restored: boolean;
}

