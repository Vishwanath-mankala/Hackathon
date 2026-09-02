"""
Router for Reconciliation Rule Engine execution and result queries.
"""
from asyncio import to_thread
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import settings
from app.models.recon import (
    PaginatedQueryResponse,
    ReconRunRequest,
    ReconRunResponse,
)
from app.services.recon_service import recon_service

router = APIRouter(prefix="/recon", tags=["Reconciliation Engine"])


@router.post(
    "/run",
    response_model=ReconRunResponse,
    summary="Run Reconciliation Engine",
    description=(
        "Runs the tiered waterfall rule engine against the cache and sequential ingestion batches. "
        "Validates structural integrity, applies tiers (Exact, Date Tolerance, Reference Match, Amount Tolerance), "
        "and produces matched, remaining cache, unmatched exceptions, and ambiguous reviews."
    ),
)
async def run_reconciliation(request: ReconRunRequest):
    result = await to_thread(recon_service.run_reconciliation, request)
    return result


@router.get(
    "/matches",
    response_model=PaginatedQueryResponse,
    summary="Query Matched Transactions",
    description="Returns paginated matched transactions with optional account and tier filtering.",
)
async def get_matches(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Items per page"),
    account: Optional[str] = Query(None, description="Filter by account number/substring"),
    tier: Optional[str] = Query(None, description="Filter by match tier (e.g. TIER_1_EXACT)"),
):
    target = settings.results_dir / "matched_transactions.csv"
    result = await to_thread(
        recon_service.query_csv_results,
        target,
        page,
        page_size,
        account,
        tier,
    )
    return result


@router.get(
    "/unmatched-cache",
    response_model=PaginatedQueryResponse,
    summary="Query Remaining Unmatched Cache",
    description="Returns paginated internal cashbook/GL rows that were never matched by ingestion files.",
)
async def get_unmatched_cache(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    account: Optional[str] = Query(None),
):
    target = settings.results_dir / "unmatched_cache_remaining.csv"
    result = await to_thread(
        recon_service.query_csv_results,
        target,
        page,
        page_size,
        account,
    )
    return result


@router.get(
    "/unmatched-ingest",
    response_model=PaginatedQueryResponse,
    summary="Query Unmatched Ingestion Exceptions",
    description="Returns paginated bank statement transactions that could not find a match in the internal cache.",
)
async def get_unmatched_ingest(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    account: Optional[str] = Query(None),
):
    target = settings.results_dir / "unmatched_ingestion_exceptions.csv"
    result = await to_thread(
        recon_service.query_csv_results,
        target,
        page,
        page_size,
        account,
    )
    return result


@router.get(
    "/ambiguous",
    response_model=PaginatedQueryResponse,
    summary="Query Ambiguous Multi-Candidate Matches",
    description="Returns paginated records where multiple candidates competed, detailing tie-breaker scores and decisions.",
)
async def get_ambiguous_matches(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    target = settings.results_dir / "ambiguous_matches_for_review.csv"
    result = await to_thread(
        recon_service.query_csv_results,
        target,
        page,
        page_size,
    )
    return result


@router.get(
    "/download/{filename}",
    summary="Download Result CSV",
    description="Download any reconciliation output or manifest CSV file directly.",
)
async def download_csv(filename: str):
    # Check recon_results
    recon_candidate = settings.results_dir / filename
    if recon_candidate.exists():
        return FileResponse(
            path=str(recon_candidate),
            media_type="text/csv",
            filename=filename,
        )

    # Check output_dir
    output_candidate = settings.output_dir / filename
    if output_candidate.exists():
        return FileResponse(
            path=str(output_candidate),
            media_type="text/csv",
            filename=filename,
        )

    # Check ingestion_batches
    batch_candidate = settings.batches_dir / filename
    if batch_candidate.exists():
        return FileResponse(
            path=str(batch_candidate),
            media_type="text/csv",
            filename=filename,
        )

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")

