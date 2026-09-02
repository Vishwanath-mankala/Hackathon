"""
Router for Feed Processing and Batch Manifest management.
"""
import shutil
from asyncio import to_thread
from pathlib import Path
from typing import Literal, Optional
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.config import settings
from app.models.feed import BatchesListResponse, ManifestResponse, SplitReconResponse
from app.services.feed_service import feed_service

router = APIRouter(prefix="/feed", tags=["Feed Ingestion & Batching"])


@router.post(
    "/split",
    response_model=SplitReconResponse,
    summary="Split Recon Source File",
    description=(
        "Splits a raw recon export into internal cache (cache_gl_cashbook.csv) and sequential "
        "ingestion batches with a declared manifest. Accepts either a file upload or a server-local file path."
    ),
)
async def split_feed(
    file: Optional[UploadFile] = File(None, description="Recon CSV file upload"),
    input_path: Optional[str] = Form(
        None,
        description="Path to local file on server. Used if no file is uploaded. Defaults to project sample dataset if both omitted."
    ),
    split_by: Literal["size", "date"] = Form("size", description="'size' or 'date'"),
    batch_size: int = Form(500, ge=1, description="Rows per batch if split_by='size'"),
    out_dir: Optional[str] = Form(None, description="Custom output directory"),
):
    target_input = input_path

    # If file uploaded, save to scratch/temp location
    if file is not None:
        upload_dir = settings.output_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp_dest = upload_dir / file.filename
        with open(temp_dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        target_input = str(temp_dest)

    result = await to_thread(
        feed_service.split_feed,
        input_path=target_input,
        split_by=split_by,
        batch_size=batch_size,
        out_dir=out_dir,
    )
    return result


@router.get(
    "/manifest",
    response_model=ManifestResponse,
    summary="Get Ingestion Manifest",
    description="Reads and parses manifest.csv detailing sequence, row counts, and control totals for all batches.",
)
async def get_manifest(
    manifest_path: Optional[str] = Query(None, description="Optional custom manifest path")
):
    result = await to_thread(feed_service.get_manifest, manifest_path)
    return result


@router.get(
    "/batches",
    response_model=BatchesListResponse,
    summary="List Ingestion Batches",
    description="Lists all batch CSV files currently generated and ready for ingestion processing.",
)
async def list_batches(
    batches_dir: Optional[str] = Query(None, description="Optional custom batches directory")
):
    result = await to_thread(feed_service.list_batches, batches_dir)
    return result

