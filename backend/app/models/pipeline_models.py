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
    suggested_fix: Optional[Dict[str, Any]] = None
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
    actual_duration_seconds: Optional[float] = None


class GLMatchSummary(BaseModel):
    total_eligible_rows: int
    matched_count: int
    tier_1_exact: int
    tier_2_date: int
    tier_3_ref: int
    tier_4_amount: int
    unmatched_reconciling_items: int
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

