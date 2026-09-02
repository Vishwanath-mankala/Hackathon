"""
Router for Ambiguity Diagnostics and Test Corruption simulation.
"""
from asyncio import to_thread
from fastapi import APIRouter

from app.models.diagnostics import (
    AmbiguityDiagnosisRequest,
    AmbiguityDiagnosisResponse,
    CorruptBatchRequest,
    CorruptBatchResponse,
    RestoreBatchRequest,
    RestoreBatchResponse,
)
from app.services.diagnostics_service import diagnostics_service

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics & Simulation"])


@router.post(
    "/ambiguity",
    response_model=AmbiguityDiagnosisResponse,
    summary="Diagnose Match Ambiguity",
    description=(
        "Analyzes ambiguous matches from the latest reconciliation run. Identifies concentration "
        "of recurring amounts/accounts, assesses tie-breaker efficiency, and generates a diagnostic report."
    ),
)
async def diagnose_ambiguity(request: AmbiguityDiagnosisRequest):
    result = await to_thread(diagnostics_service.diagnose_ambiguity, request.results_dir)
    return result


@router.post(
    "/corrupt-batch",
    response_model=CorruptBatchResponse,
    summary="Simulate Batch Corruption (Chaos Testing)",
    description=(
        "Injects a realistic real-world failure into a batch file to test structural gate enforcement. "
        "Modes include: truncate, dropped_row, duplicate_row, tampered_amount, missing_column, bad_encoding. "
        "Automatically creates a .bak backup."
    ),
)
async def corrupt_batch(request: CorruptBatchRequest):
    result = await to_thread(
        diagnostics_service.corrupt_batch,
        batch_filename=request.batch_filename,
        mode=request.mode,
    )
    return result


@router.post(
    "/restore-batch",
    response_model=RestoreBatchResponse,
    summary="Restore Corrupted Batch",
    description="Restores a previously corrupted batch file back from its .bak backup copy.",
)
async def restore_batch(request: RestoreBatchRequest):
    result = await to_thread(
        diagnostics_service.restore_batch,
        batch_filename=request.batch_filename,
    )
    return result

