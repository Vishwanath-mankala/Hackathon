"""
Pydantic schemas for reconciliation feed splitting and manifest inspection.
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class ManifestRecord(BaseModel):
    sequence: int = Field(..., description="Batch execution sequence order")
    file: str = Field(..., description="Batch CSV filename")
    row_count: int = Field(..., description="Actual row count in batch")
    declared_record_count: int = Field(..., description="Declared record count for structural validation")
    declared_control_total: float = Field(..., description="Declared control total amount")
    min_booking_date: Optional[str] = Field(None, description="Earliest booking date in batch")
    max_booking_date: Optional[str] = Field(None, description="Latest booking date in batch")


class SplitReconRequest(BaseModel):
    input_path: Optional[str] = Field(
        None,
        description="Optional local filesystem path to source recon CSV (e.g. recon_60k.csv). If omitted, uploaded file is used."
    )
    split_by: Literal["size", "date"] = Field(
        "size",
        description="'size' = fixed-row batches, 'date' = one file per calendar booking date"
    )
    batch_size: int = Field(
        500,
        ge=1,
        description="Rows per batch file when split_by='size'"
    )
    out_dir: Optional[str] = Field(
        None,
        description="Custom output directory. Defaults to configured output_dir."
    )


class SplitReconResponse(BaseModel):
    message: str
    total_rows_loaded: int
    cache_rows: int
    ingest_rows: int
    cache_path: str
    batches_dir: str
    manifest_path: str
    batch_count: int
    manifest: List[ManifestRecord]


class ManifestResponse(BaseModel):
    manifest_path: str
    total_batches: int
    total_declared_records: int
    total_declared_amount: float
    records: List[ManifestRecord]


class BatchesListResponse(BaseModel):
    batches_dir: str
    count: int
    files: List[str]

