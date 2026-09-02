"""
Feed processing service adapter.
Wraps 'File-Gen Scripts/split_recon_feed.py' without altering original functionality.
"""
import os
import sys
from pathlib import Path
from typing import List, Optional
import pandas as pd
from fastapi import HTTPException

from app.config import settings
from app.models.feed import (
    BatchesListResponse,
    ManifestRecord,
    ManifestResponse,
    SplitReconResponse,
)

# Ensure File-Gen Scripts directory is in sys.path
FILE_GEN_DIR = str(settings.project_root / "File-Gen Scripts")
if FILE_GEN_DIR not in sys.path:
    sys.path.insert(0, FILE_GEN_DIR)

import split_recon_feed  # type: ignore


class FeedService:
    @staticmethod
    def split_feed(
        input_path: Optional[str] = None,
        split_by: str = "size",
        batch_size: int = 500,
        out_dir: Optional[str] = None,
    ) -> SplitReconResponse:
        resolved_out_dir = Path(out_dir) if out_dir else settings.output_dir
        resolved_input = Path(input_path) if input_path else (settings.project_root / "File-Gen Scripts" / "BenchRec_cash_v1.0_eval.csv")

        if not resolved_input.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Source input file not found: {resolved_input}"
            )

        resolved_out_dir.mkdir(parents=True, exist_ok=True)
        batches_dir = resolved_out_dir / "ingestion_batches"
        batches_dir.mkdir(parents=True, exist_ok=True)

        try:
            df = split_recon_feed.load_source(str(resolved_input))
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to parse source file: {str(e)}"
            )

        cache_df = split_recon_feed.build_cache(df)
        cache_path = resolved_out_dir / "cache_gl_cashbook.csv"
        cache_df.to_csv(cache_path, index=False)

        ingest_df = split_recon_feed.build_ingest(df)

        if split_by == "size":
            manifest = split_recon_feed.write_batches_by_size(ingest_df, str(batches_dir), batch_size)
        else:
            manifest = split_recon_feed.write_batches_by_date(ingest_df, str(batches_dir))

        manifest_df = pd.DataFrame(manifest)
        manifest_path = batches_dir / "manifest.csv"
        manifest_df.to_csv(manifest_path, index=False)

        manifest_records = [
            ManifestRecord(
                sequence=int(m["sequence"]),
                file=str(m["file"]),
                row_count=int(m["row_count"]),
                declared_record_count=int(m["declared_record_count"]),
                declared_control_total=float(m["declared_control_total"]),
                min_booking_date=str(m.get("min_booking_date")) if pd.notna(m.get("min_booking_date")) else None,
                max_booking_date=str(m.get("max_booking_date")) if pd.notna(m.get("max_booking_date")) else None,
            )
            for m in manifest
        ]

        return SplitReconResponse(
            message=f"Successfully split {len(df)} rows into cache and {len(manifest)} ingestion batches.",
            total_rows_loaded=len(df),
            cache_rows=len(cache_df),
            ingest_rows=len(ingest_df),
            cache_path=str(cache_path),
            batches_dir=str(batches_dir),
            manifest_path=str(manifest_path),
            batch_count=len(manifest),
            manifest=manifest_records,
        )

    @staticmethod
    def get_manifest(manifest_path: Optional[str] = None) -> ManifestResponse:
        path = Path(manifest_path) if manifest_path else settings.manifest_path
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Manifest file not found at: {path}. Run feed split first."
            )

        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error reading manifest: {str(e)}"
            )

        records: List[ManifestRecord] = []
        total_records = 0
        total_amount = 0.0

        for _, row in df.iterrows():
            rc = int(row.get("declared_record_count", row.get("row_count", 0)) or 0)
            ct = float(row.get("declared_control_total", 0.0) or 0.0)
            total_records += rc
            total_amount += ct
            records.append(
                ManifestRecord(
                    sequence=int(row.get("sequence", 0)),
                    file=str(row.get("file", "")),
                    row_count=int(row.get("row_count", 0)),
                    declared_record_count=rc,
                    declared_control_total=ct,
                    min_booking_date=str(row.get("min_booking_date")) if row.get("min_booking_date") else None,
                    max_booking_date=str(row.get("max_booking_date")) if row.get("max_booking_date") else None,
                )
            )

        return ManifestResponse(
            manifest_path=str(path),
            total_batches=len(records),
            total_declared_records=total_records,
            total_declared_amount=round(total_amount, 2),
            records=records,
        )

    @staticmethod
    def list_batches(batches_dir: Optional[str] = None) -> BatchesListResponse:
        path = Path(batches_dir) if batches_dir else settings.batches_dir
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Batches directory not found at: {path}"
            )

        csv_files = sorted([f.name for f in path.glob("*.csv") if f.name != "manifest.csv"])
        return BatchesListResponse(
            batches_dir=str(path),
            count=len(csv_files),
            files=csv_files,
        )


feed_service = FeedService()

