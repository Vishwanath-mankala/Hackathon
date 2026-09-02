"""
Pydantic schemas for reconciliation engine execution and queries.
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class MatchConfigSchema(BaseModel):
    date_tolerance_days: int = Field(3, ge=0, description="Tier 2 date window fallback in days")
    amount_abs_tolerance: float = Field(1.00, ge=0.0, description="Tier 4 absolute currency slack")
    amount_pct_tolerance: float = Field(0.0, ge=0.0, le=1.0, description="Tier 4 percentage slack on top of absolute")
    direction_mode: Literal["ignore", "same", "opposite"] = Field(
        "ignore",
        description="'ignore' = sign convention unknown, 'same' = DR matches DR, 'opposite' = DR matches CR"
    )


class ReconRunRequest(BaseModel):
    cache_path: Optional[str] = Field(None, description="Path to cache_gl_cashbook.csv. Defaults to config.")
    manifest_path: Optional[str] = Field(None, description="Path to manifest.csv. Defaults to config.")
    batches_dir: Optional[str] = Field(None, description="Directory containing batch CSVs. Defaults to config.")
    out_dir: Optional[str] = Field(None, description="Output directory for recon results. Defaults to config.")
    config: MatchConfigSchema = Field(default_factory=MatchConfigSchema, description="Tolerance and direction knobs")
    single_batch: Optional[str] = Field(
        None,
        description="Filename (e.g. ingest_batch_0001.csv) to test just one batch instead of full run."
    )


class ReconRunResponse(BaseModel):
    message: str
    total_matched: int
    tier_breakdown: Dict[str, int]
    cache_remaining_count: int
    ingest_unmatched_count: int
    ambiguous_count: int
    out_dir: str
    output_files: Dict[str, str]


class MatchRecord(BaseModel):
    matchId: str
    matchDate: str
    matchRule: str
    matchedBy: str
    wasPreviouslyMismatched: int
    internal_txn_id: Optional[str] = None
    external_txn_id: Optional[str] = None
    account: Optional[str] = None
    currency: Optional[str] = None
    cache_amount: Optional[str] = None
    ingest_amount: Optional[str] = None
    cache_date: Optional[str] = None
    ingest_date: Optional[str] = None
    cache_reference: Optional[str] = None
    ingest_reference: Optional[str] = None
    batch_file: Optional[str] = None


class PaginatedQueryResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[Dict[str, Any]]

