"""
Reconciliation service adapter.
Wraps 'Rule Engine/rule_engine.py' without altering original functionality.
"""
import io
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from fastapi import HTTPException

from app.config import settings
from app.models.recon import (
    MatchConfigSchema,
    PaginatedQueryResponse,
    ReconRunRequest,
    ReconRunResponse,
)

RULE_ENGINE_DIR = str(settings.project_root / "Rule Engine")
if RULE_ENGINE_DIR not in sys.path:
    sys.path.insert(0, RULE_ENGINE_DIR)

import rule_engine  # type: ignore


class ReconService:
    @staticmethod
    def run_reconciliation(request: ReconRunRequest) -> ReconRunResponse:
        cache_path = Path(request.cache_path) if request.cache_path else settings.cache_path
        manifest_path = Path(request.manifest_path) if request.manifest_path else settings.manifest_path
        batches_dir = Path(request.batches_dir) if request.batches_dir else settings.batches_dir
        out_dir = Path(request.out_dir) if request.out_dir else settings.results_dir

        if not cache_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Cache file not found at: {cache_path}. Run feed split first."
            )
        if not manifest_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Manifest file not found at: {manifest_path}. Run feed split first."
            )
        if not batches_dir.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Batches directory not found at: {batches_dir}."
            )

        out_dir.mkdir(parents=True, exist_ok=True)

        cfg = rule_engine.MatchConfig(
            date_tolerance_days=request.config.date_tolerance_days,
            amount_abs_tolerance=request.config.amount_abs_tolerance,
            amount_pct_tolerance=request.config.amount_pct_tolerance,
            direction_mode=request.config.direction_mode,
        )

        try:
            rule_engine.run(
                str(cache_path),
                str(manifest_path),
                str(batches_dir),
                str(out_dir),
                cfg,
                single_batch=request.single_batch,
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Rule engine execution error: {str(e)}"
            )

        # Parse generated outputs for summary
        matched_path = out_dir / "matched_transactions.csv"
        unmatched_cache_path = out_dir / "unmatched_cache_remaining.csv"
        unmatched_ingest_path = out_dir / "unmatched_ingestion_exceptions.csv"
        ambiguous_path = out_dir / "ambiguous_matches_for_review.csv"

        matched_count = 0
        tier_breakdown: Dict[str, int] = {}
        if matched_path.exists():
            m_df = pd.read_csv(matched_path, dtype=str, keep_default_na=False)
            matched_count = len(m_df)
            if "matchRule" in m_df.columns:
                tier_breakdown = {str(k): int(v) for k, v in m_df["matchRule"].value_counts().items()}

        cache_remaining = 0
        if unmatched_cache_path.exists():
            uc_df = pd.read_csv(unmatched_cache_path, dtype=str, keep_default_na=False)
            cache_remaining = len(uc_df)

        ingest_unmatched = 0
        if unmatched_ingest_path.exists():
            ui_df = pd.read_csv(unmatched_ingest_path, dtype=str, keep_default_na=False)
            ingest_unmatched = len(ui_df)

        ambiguous_count = 0
        if ambiguous_path.exists():
            amb_df = pd.read_csv(ambiguous_path, dtype=str, keep_default_na=False)
            ambiguous_count = len(amb_df)

        return ReconRunResponse(
            message="Reconciliation run completed successfully.",
            total_matched=matched_count,
            tier_breakdown=tier_breakdown,
            cache_remaining_count=cache_remaining,
            ingest_unmatched_count=ingest_unmatched,
            ambiguous_count=ambiguous_count,
            out_dir=str(out_dir),
            output_files={
                "matched": str(matched_path),
                "unmatched_cache": str(unmatched_cache_path),
                "unmatched_ingest": str(unmatched_ingest_path),
                "ambiguous": str(ambiguous_path),
            },
        )

    @staticmethod
    def query_csv_results(
        file_path: Path,
        page: int = 1,
        page_size: int = 50,
        account: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> PaginatedQueryResponse:
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Result file does not exist: {file_path}. Run reconciliation first."
            )

        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError:
            # A stage that produced no rows writes a zero-byte CSV. That is a
            # valid empty result set, not a failure.
            return PaginatedQueryResponse(
                total=0, page=page, page_size=page_size, total_pages=1, items=[]
            )

        if account and "account" in df.columns:
            df = df[df["account"].str.contains(account, case=False, na=False)]
        if tier and "matchRule" in df.columns:
            df = df[df["matchRule"] == tier]

        total_items = len(df)
        total_pages = max(1, math.ceil(total_items / page_size))
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        sliced = df.iloc[start_idx:end_idx]
        items = sliced.to_dict(orient="records")

        return PaginatedQueryResponse(
            total=total_items,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            items=items,
        )


recon_service = ReconService()

