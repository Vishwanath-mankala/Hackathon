"""
Pydantic schemas for ambiguity diagnostics and batch corruption testing.
"""
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field


class AmbiguityDiagnosisRequest(BaseModel):
    results_dir: Optional[str] = Field(
        None,
        description="Path to recon_results directory containing ambiguous_matches_for_review.csv. Defaults to config."
    )


class AmbiguityDiagnosisResponse(BaseModel):
    total_ambiguous: int
    avg_candidates: float
    max_candidates: int
    ambiguity_by_tier: Dict[str, int]
    resolved_by_reference: Optional[int] = None
    resolved_by_reference_pct: Optional[float] = None
    top_accounts: Dict[str, int]
    top_amounts: Dict[str, int]
    top_amounts_concentration_pct: float
    is_concentrated: bool
    diagnostic_assessment: str
    output_detail_csv: str


class CorruptBatchRequest(BaseModel):
    batch_filename: str = Field(
        ...,
        description="Batch CSV filename in ingestion_batches (e.g. ingest_batch_0001.csv)"
    )
    mode: Literal[
        "truncate",
        "dropped_row",
        "duplicate_row",
        "tampered_amount",
        "missing_column",
        "bad_encoding",
    ] = Field(
        ...,
        description="Type of corruption to simulate"
    )


class CorruptBatchResponse(BaseModel):
    message: str
    file: str
    mode: str
    backup_path: str


class RestoreBatchRequest(BaseModel):
    batch_filename: str = Field(
        ...,
        description="Batch CSV filename to restore from .bak"
    )


class RestoreBatchResponse(BaseModel):
    message: str
    file: str
    restored: bool

