"""
Pipeline Router — Exposes the 8-stage Batch File Validation, Anomaly Detection,
Time Estimation, GL Matching, and Publishing endpoints.
"""
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query

from app.models.pipeline_models import (
    BatchRecord,
    StructuralGateDetails,
    AnomalyItem,
    TimeEstimate,
    GLMatchSummary,
    PublishEvent,
    PipelineOverview,
    HumanResolveRequest,
    IngestionResponse
)
from app.services.pipeline_orchestrator import pipeline_orchestrator
from app.services.publish_service import publish_service
from app.services.ingestion_service import ingestion_service
from app.config import settings

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline Orchestrator"])


@router.get("/overview", response_model=PipelineOverview)
def get_pipeline_overview():
    """Returns high-level telemetry, active batches, SLA alerts, and processing metrics."""
    return pipeline_orchestrator.get_overview()


@router.get("/batches", response_model=List[BatchRecord])
def list_batches(
    stage: Optional[str] = Query(None, description="Filter by stage"),
    limit: int = Query(50, ge=1, le=200)
):
    """Lists all ingested batch records with current processing stage and ETA."""
    batches = list(pipeline_orchestrator.batches.values())
    if stage:
        batches = [b for b in batches if b.stage == stage]
    # Sort descending by created_at
    batches.sort(key=lambda b: b.created_at, reverse=True)
    return batches[:limit]


@router.get("/batches/{batch_id}", response_model=BatchRecord)
def get_batch(batch_id: str):
    """Returns full batch lifecycle details, metrics, and gate results."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    return pipeline_orchestrator.batches[batch_id]


@router.post("/ingest", response_model=IngestionResponse)
async def ingest_batch_file(
    file: UploadFile = File(...),
    source: str = Form("UPLOAD"),
    declared_record_count: Optional[int] = Form(None),
    declared_control_total: Optional[float] = Form(None)
):
    """
    Ingests a complete bank statement file without splitting.
    Executes the structural gate and row-level anomaly pipeline automatically.
    """
    try:
        content = await file.read()
        batch = pipeline_orchestrator.ingest_batch(
            file_bytes=content,
            filename=file.filename or "statement_batch.csv",
            source=source,
            declared_record_count=declared_record_count,
            declared_control_total=declared_control_total,
            auto_run_pipeline=True
        )

        return IngestionResponse(
            batch_id=batch.batch_id,
            filename=batch.filename,
            message=f"Batch {batch.batch_id} ingested successfully. Stage: {batch.stage}",
            stage=batch.stage,
            record_count=batch.total_records,
            gate_passed=bool(batch.gate_passed),
            quarantined=batch.stage == "GATE_QUARANTINED",
            time_estimate=batch.time_estimate
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.post("/simulate-sftp", response_model=IngestionResponse)
def simulate_sftp_ingestion(
    filename: Optional[str] = Query(None, description="Filename from sample batches to simulate SFTP arrival")
):
    """
    Simulates real-world automated SFTP drop arrival of a bank statement batch.
    """
    # Look in batches dir or sftp dir
    target_file = None
    if filename:
        candidate_1 = settings.batches_dir / filename
        candidate_2 = ingestion_service.sftp_dir / filename
        if candidate_1.exists():
            target_file = candidate_1
        elif candidate_2.exists():
            target_file = candidate_2
    else:
        # Pick first available batch file
        candidates = list(settings.batches_dir.glob("ingest_batch_*.csv"))
        if candidates:
            target_file = candidates[0]

    if not target_file or not target_file.exists():
        raise HTTPException(status_code=404, detail="No source file available for SFTP simulation.")

    batch = pipeline_orchestrator.ingest_batch(
        file_path=target_file,
        filename=f"sftp_{target_file.name}",
        source="SFTP",
        auto_run_pipeline=True
    )

    return IngestionResponse(
        batch_id=batch.batch_id,
        filename=batch.filename,
        message=f"Simulated SFTP arrival of {batch.filename} processed.",
        stage=batch.stage,
        record_count=batch.total_records,
        gate_passed=bool(batch.gate_passed),
        quarantined=batch.stage == "GATE_QUARANTINED",
        time_estimate=batch.time_estimate
    )


@router.get("/batches/{batch_id}/gate", response_model=StructuralGateDetails)
def get_batch_gate_details(batch_id: str):
    """Returns the file-level structural gate inspection report."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    gate = pipeline_orchestrator.batches[batch_id].gate_details
    if not gate:
        raise HTTPException(status_code=404, detail=f"No gate details for batch '{batch_id}'.")
    return gate


@router.get("/batches/{batch_id}/anomalies", response_model=List[AnomalyItem])
def get_batch_anomalies(
    batch_id: str,
    status: Optional[str] = Query(None, description="Filter by status (AUTO_REMEDIATED, ESCALATED, etc.)"),
    severity: Optional[str] = Query(None, description="Filter by severity")
):
    """Returns detected row anomalies, auto-remediations, and human escalation queue."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    anomalies = pipeline_orchestrator.batch_anomalies.get(batch_id, [])
    if status:
        anomalies = [a for a in anomalies if a.status == status]
    if severity:
        anomalies = [a for a in anomalies if a.severity == severity]
    return anomalies


@router.post("/batches/{batch_id}/anomalies/{anomaly_id}/resolve", response_model=BatchRecord)
def resolve_human_escalation(
    batch_id: str,
    anomaly_id: str,
    req: HumanResolveRequest
):
    """
    Analyst review action:
    - APPROVE: accepts suggested fix (re-enters rule engine for re-validation)
    - OVERRIDE: applies manual values
    - QUARANTINE: isolates row from matching
    """
    try:
        updated_batch = pipeline_orchestrator.resolve_escalation(
            batch_id=batch_id,
            anomaly_id=anomaly_id,
            action=req.action,
            override_values=req.override_values,
            analyst_notes=req.analyst_notes
        )
        return updated_batch
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resolution error: {str(e)}")


@router.get("/batches/{batch_id}/recon")
def get_batch_reconciliation(batch_id: str):
    """Returns GL tiered matching breakdown, matched pairs, and unmatched reconciling items."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    batch = pipeline_orchestrator.batches[batch_id]
    summary = batch.gl_summary
    results = pipeline_orchestrator.batch_match_results.get(batch_id, {"matched": [], "unmatched_reconciling": []})

    return {
        "batch_id": batch_id,
        "summary": summary,
        "matched_sample": results["matched"][:100],
        "unmatched_sample": results["unmatched_reconciling"][:100]
    }


@router.get("/batches/{batch_id}/estimator", response_model=TimeEstimate)
def get_time_estimate(batch_id: str):
    """Returns granular processing time breakdown, throughput benchmarks, and SLA compliance status."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    est = pipeline_orchestrator.batches[batch_id].time_estimate
    if not est:
        raise HTTPException(status_code=404, detail=f"No estimate available for '{batch_id}'.")
    return est


@router.post("/batches/{batch_id}/publish", response_model=PublishEvent)
def publish_batch_results(batch_id: str):
    """Broadcasts batch completion and reconciliation summary to downstream message bus."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    batch = pipeline_orchestrator.batches[batch_id]
    event = publish_service.publish_batch(batch)
    return event


@router.get("/publish/events", response_model=List[PublishEvent])
def get_published_events(limit: int = Query(50, ge=1, le=200)):
    """Returns event history published to downstream consumers."""
    return publish_service.get_events(limit)


# =============================================================================
# Agent Platform Integration Endpoints (CrewAI / Multi-Agent Platform)
# =============================================================================
@router.get("/agent/status")
def get_agent_status():
    """
    Returns the configuration and connectivity status of the external CrewAI
    or Multi-Agent platform API.
    """
    from app.services.agentic_anomaly_service import agentic_anomaly_service
    return agentic_anomaly_service.agent_bridge.test_connection()


@router.post("/agent/test-connection")
def test_agent_connection():
    """
    Tests live connectivity to the configured CrewAI agent platform.
    """
    from app.services.agentic_anomaly_service import agentic_anomaly_service
    return agentic_anomaly_service.agent_bridge.test_connection()


