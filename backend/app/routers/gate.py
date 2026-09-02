"""
Router for Structural Integrity Gate.
"""
from asyncio import to_thread
from fastapi import APIRouter

from app.models.gate import (
    GateAllRequest,
    GateCheckRequest,
    GateResultSchema,
    GateSummaryResponse,
)
from app.services.gate_service import gate_service

router = APIRouter(prefix="/gate", tags=["Structural Gate Validation"])


@router.post(
    "/check-batch",
    response_model=GateResultSchema,
    summary="Validate Single Batch File",
    description=(
        "Applies 4 deterministic checks to a batch file: encoding, required header columns, "
        "record count vs declared count, and control total sum vs declared total."
    ),
)
async def check_batch(request: GateCheckRequest):
    result = await to_thread(
        gate_service.check_batch,
        batch_filename=request.batch_filename,
        declared_record_count=request.declared_record_count,
        declared_control_total=request.declared_control_total,
        expected_encoding=request.expected_encoding,
    )
    return result


@router.post(
    "/check-all",
    response_model=GateSummaryResponse,
    summary="Validate All Manifest Batches",
    description=(
        "Executes structural gate checks on all batches registered in the manifest. "
        "Corrupt or inconsistent batches are automatically quarantined before reaching the rule engine."
    ),
)
async def check_all_batches(request: GateAllRequest):
    result = await to_thread(
        gate_service.check_all,
        batches_dir=request.batches_dir,
        manifest_path=request.manifest_path,
        quarantine_dir=request.quarantine_dir,
    )
    return result

