"""
Pydantic schemas for structural gate validation.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CheckDetail(BaseModel):
    passed: bool
    detail: str


class GateResultSchema(BaseModel):
    file: str = Field(..., description="Batch filename")
    passed: bool = Field(..., description="True if batch passed all structural checks")
    checks: Dict[str, CheckDetail] = Field(
        default_factory=dict,
        description="Individual check results: encoding, required_sections, record_count, control_total"
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="Human-readable failure reasons"
    )


class GateCheckRequest(BaseModel):
    batch_filename: str = Field(..., description="Filename in ingestion_batches directory (e.g. ingest_batch_0001.csv)")
    declared_record_count: Optional[int] = Field(
        None,
        description="Optional expected record count. If omitted, looked up from manifest.csv"
    )
    declared_control_total: Optional[float] = Field(
        None,
        description="Optional expected control total amount. If omitted, looked up from manifest.csv"
    )
    expected_encoding: str = Field("utf-8", description="Expected file encoding")


class GateAllRequest(BaseModel):
    batches_dir: Optional[str] = Field(None, description="Custom batches directory. Defaults to configured batches_dir.")
    manifest_path: Optional[str] = Field(None, description="Custom manifest CSV path.")
    quarantine_dir: Optional[str] = Field(None, description="Directory to copy failing batches to.")


class GateSummaryResponse(BaseModel):
    total_batches: int
    passed_count: int
    failed_count: int
    quarantined_count: int
    quarantine_dir: Optional[str]
    results: List[GateResultSchema]

