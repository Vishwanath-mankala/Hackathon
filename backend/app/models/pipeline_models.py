"""
Pydantic models for the End-to-End Batch Pipeline, Agentic Anomaly Detection,
Auto-Remediation, GL Matching, Processing Time Estimation, and Publishing.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class CheckDetail(BaseModel):
    passed: bool
    detail: str


class StructuralGateDetails(BaseModel):
    passed: bool
    file: str
    declared_record_count: Optional[int] = None
    actual_record_count: int
    declared_control_total: Optional[float] = None
    actual_control_total: float
    checks: Dict[str, CheckDetail] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    quarantined: bool = False
    quarantine_path: Optional[str] = None


class AnomalyItem(BaseModel):
    id: str
    row_index: int
    external_txn_id: str
    account: str
    amount: Optional[float] = None
    raw_amount: Optional[str] = None
    booking_date: Optional[str] = None
    error_type: str
    severity: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW
    category: str = "STRUCTURAL"  # STRUCTURAL, SEMANTIC, TIMING, REFERENTIAL (ARCHITECTURE.md Stage 4)
    description: str
    auto_remediable: bool = False
    # Only set when a correction is derivable from the row itself and applying it
    # is lossless. Escalated rows carry None: there is nothing safe to propose,
    # and offering a guess an analyst could approve would corrupt the ledger.
    suggested_fix: Optional[Dict[str, Any]] = None
    # Columns the analyst has to fill in to resolve this by OVERRIDE.
    override_fields: List[str] = Field(default_factory=list)
    status: str = "DETECTED"  # DETECTED, AUTO_REMEDIATED, ESCALATED, HUMAN_RESOLVED, QUARANTINED
    remediation_notes: Optional[str] = None
    confidence_score: float = 0.85


class HumanResolveRequest(BaseModel):
    action: str = "APPROVE"  # APPROVE, OVERRIDE, QUARANTINE
    override_values: Optional[Dict[str, Any]] = None
    analyst_notes: Optional[str] = None


class TimeEstimate(BaseModel):
    batch_id: str
    file_size_bytes: int
    file_size_mb: float
    total_records: int
    anomaly_count: int
    throughput_records_per_sec: float
    estimated_parse_time_sec: float
    estimated_gate_time_sec: float
    estimated_rule_time_sec: float
    estimated_anomaly_triage_sec: float
    estimated_gl_match_sec: float
    total_estimated_seconds: float
    eta_timestamp: str
    sla_target_seconds: float = 900.0  # e.g., 15 minute SLA
    sla_status: str = "ON_TRACK"  # ON_TRACK, AT_RISK, BREACHED
    completed_at: Optional[str] = None
    actual_duration_seconds: Optional[float] = None   # wall-clock, including analyst queue wait

    # Machine work vs human wait, kept separate: one number mixing 0.4s of compute
    # with 40 minutes of analyst wait is useless for calibration.
    estimated_machine_seconds: float = 0.0
    estimated_queue_wait_sec: float = 0.0
    machine_seconds: Optional[float] = None
    queue_wait_seconds: Optional[float] = None

    # Where the constants behind this estimate came from. DEFAULT means the
    # declared formula; HISTORY means throughput / queue-wait were derived from
    # the run history on this machine.
    calibration_source: str = "DEFAULT"
    calibration_sample_size: int = 0
    calibration_factor: float = 1.0          # residual machine/actual ratio, display only
    baseline_throughput_used: float = 1450.0


class BatchForecast(BaseModel):
    """
    The forecast agent's prediction for one batch, captured server-side.

    Issued before the batch is processed from ingest-time features plus the run
    history, then scored against the measured wall-clock once the run completes.
    """
    status: str = "PENDING"   # PENDING | RECEIVED | TIMED_OUT | UNPARSEABLE | SKIPPED | FAILED
    forecast_seconds: Optional[float] = None
    p10_seconds: Optional[float] = None
    p90_seconds: Optional[float] = None
    confidence: Optional[str] = None
    breach_probability_pct: Optional[float] = None
    expected_escalation_rate_pct: Optional[float] = None
    dominant_uncertainty: Optional[str] = None
    comparable_batches: List[str] = Field(default_factory=list)
    reasoning: Optional[str] = None
    dashboard_line: Optional[str] = None
    agent_execution_id: Optional[str] = None
    issued_at: Optional[str] = None
    received_at: Optional[str] = None
    message: Optional[str] = None
    error_pct: Optional[float] = None       # signed, vs measured wall_seconds


class RunHistoryRow(BaseModel):
    """One completed run in the knowledge base (see run_history_service.CSV_COLUMNS)."""
    batch_id: str
    completed_at: str
    source: str
    filename: str
    outcome: str
    provenance: str
    gate_passed: bool
    record_count: int
    file_size_mb: float
    anomaly_count: int
    escalated_count: int
    matched_count: int
    estimate_at_ingest_sec: Optional[float] = None
    estimate_final_sec: Optional[float] = None
    machine_seconds: Optional[float] = None
    queue_wait_seconds: Optional[float] = None
    wall_seconds: Optional[float] = None
    throughput_actual_rec_per_sec: Optional[float] = None
    local_error_pct: Optional[float] = None
    eligible_for_calibration: bool = False
    forecast_seconds: Optional[float] = None
    forecast_error_pct: Optional[float] = None
    forecast_status: Optional[str] = None


class CalibrationSummary(BaseModel):
    source: str                               # DEFAULT | HISTORY
    sample_size: int
    min_runs_required: int
    baseline_throughput: float
    default_throughput: float
    queue_wait_per_escalation_sec: float
    default_queue_wait_sec: float
    residual_factor: float                    # median machine / machine_estimate, display only
    total_runs_recorded: int
    forecasts_received: int
    forecast_median_abs_error_pct: Optional[float] = None
    local_median_abs_error_pct: Optional[float] = None


class ForecastComparison(BaseModel):
    """Local estimate vs agent forecast vs measured actual, for one batch."""
    batch_id: str
    stage: str
    local_estimate: TimeEstimate
    agent_forecast: Optional[BatchForecast] = None
    execution: Optional["AgentExecution"] = None
    actual: Optional[Dict[str, Any]] = None   # machine_seconds, queue_wait_seconds, wall_seconds
    calibration: CalibrationSummary


class AgentExecution(BaseModel):
    """One dispatch of a batch artefact to an external (Aava/CrewAI) agent."""
    stage: str                      # STAGE_1_FORECAST, STAGE_4_ANOMALY, STAGE_6_RECON, STAGE_7_SLA
    agent_id: Optional[str] = None  # None when the stage has no CREWAI_AGENT_*_ID set
    agent_name: str
    trigger: str = "AUTOMATIC"      # AUTOMATIC | MANUAL
    success: bool = False
    job_id: Optional[int] = None
    agent_execution_id: Optional[str] = None
    status: str = "PENDING"         # PENDING, SUBMITTED, IN_PROGRESS, SUCCESS, FAILED, SKIPPED
    message: Optional[str] = None
    http_status: Optional[str] = None
    target_file: Optional[str] = None            # primary artefact (names the zip)
    bundled_files: List[str] = Field(default_factory=list)  # every member of the zip
    submitted_at: Optional[str] = None
    completed_at: Optional[str] = None
    output: Optional[Any] = None
    forecast_captured: bool = False  # STAGE_1_FORECAST: output already parsed into BatchForecast


ForecastComparison.model_rebuild()


class AuditSignoff(BaseModel):
    """
    One analyst decision on one reconciliation line, append-only.

    A correction is recorded as a new sign-off carrying `supersedes`; the record
    it replaces is never edited or removed, so the trail reads as the sequence of
    calls actually made.
    """
    signoff_id: str
    batch_id: str
    dataset: str                                  # matched | unmatched_bank | outstanding_gl | ambiguous
    row_key: str                                  # the transaction id the decision applies to
    action: str                                   # see audit_service.valid_actions(dataset)
    chosen_internal_txn_id: Optional[str] = None  # set when re-pointing an ambiguous tie
    analyst: str
    analyst_notes: Optional[str] = None
    signed_at: str
    supersedes: Optional[str] = None              # signoff_id this one replaces


class SignoffRequest(BaseModel):
    row_key: str
    action: str
    chosen_internal_txn_id: Optional[str] = None
    analyst: Optional[str] = None                 # defaults to the console operator
    analyst_notes: Optional[str] = None


class GLMatchSummary(BaseModel):
    total_eligible_rows: int
    matched_count: int
    tier_1_exact: int
    tier_2_date: int
    tier_3_ref: int
    tier_4_amount: int
    unmatched_reconciling_items: int
    outstanding_gl_items: int = 0
    ambiguous_count: int
    match_rate_pct: float


class PublishEvent(BaseModel):
    event_id: str
    batch_id: str
    published_at: str
    channel: str = "downstream-reconciliation-bus"
    status: str
    summary: Dict[str, Any]
    delivered: bool = True


class BatchRecord(BaseModel):
    batch_id: str
    filename: str
    file_size_bytes: int
    source: str = "SFTP"  # SFTP, UPLOAD, MANUAL_TRIGGER
    stage: str = "RECEIVED"  # RECEIVED, INGESTED, GATE_CHECK, GATE_QUARANTINED, RULE_ENGINE, ANOMALY_EVAL, REMEDIATION, RECONCILING, COMPLETED, PUBLISHED
    gate_passed: Optional[bool] = None
    total_records: int = 0
    valid_records_count: int = 0
    anomaly_count: int = 0
    auto_remediated_count: int = 0
    escalated_count: int = 0
    quarantined_rows_count: int = 0
    matched_count: int = 0
    unmatched_count: int = 0
    created_at: str
    updated_at: str
    time_estimate: Optional[TimeEstimate] = None
    gate_details: Optional[StructuralGateDetails] = None
    gl_summary: Optional[GLMatchSummary] = None
    published: bool = False
    publish_event: Optional[PublishEvent] = None
    batch_file_path: Optional[str] = None
    anomaly_file_path: Optional[str] = None

    # Stage 6 / Stage 7 artefacts written to disk (agent inputs + audit exports)
    matched_file_path: Optional[str] = None
    unmatched_file_path: Optional[str] = None
    outstanding_file_path: Optional[str] = None
    ambiguous_file_path: Optional[str] = None
    sla_metrics_file_path: Optional[str] = None

    # Stage 1 forecast bundle: this batch's ingest-time features and the history
    # snapshot the forecast agent was handed (kept so the forecast is auditable).
    forecast_input_file_path: Optional[str] = None
    run_history_file_path: Optional[str] = None

    # Measured timing. machine = compute across the stages; queue_wait = time
    # parked at the analyst queue; wall = both, what the SLA is judged against.
    machine_seconds: Optional[float] = None
    queue_wait_seconds: Optional[float] = None
    wall_seconds: Optional[float] = None
    # The Stage 1 estimate, kept because time_estimate is replaced once the
    # rule engine has told us the batch's quality.
    estimate_at_ingest_sec: Optional[float] = None
    agent_forecast: Optional[BatchForecast] = None

    # Automatic multi-agent dispatch log, keyed by pipeline stage
    agent_executions: Dict[str, AgentExecution] = Field(default_factory=dict)
    # Most recent dispatch (kept for backwards compatibility with older clients)
    agent_execution: Optional[Dict[str, Any]] = None


class AgentExecutionResponse(BaseModel):
    batch_id: str
    job_id: Optional[int] = None
    agent_execution_id: Optional[str] = None
    message: str
    http_status: str = "OK"
    success: bool = True
    submitted_at: str
    target_file: Optional[str] = None


class IngestionResponse(BaseModel):
    batch_id: str
    filename: str
    message: str
    stage: str
    record_count: int
    gate_passed: bool
    quarantined: bool
    time_estimate: Optional[TimeEstimate] = None


class PipelineOverview(BaseModel):
    total_batches: int
    active_batches: int
    completed_batches: int
    quarantined_batches: int
    total_records_processed: int
    sla_breaches: int
    at_risk_count: int
    batches: List[BatchRecord]

