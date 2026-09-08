"""
Pipeline Router — Exposes the 8-stage Batch File Validation, Anomaly Detection,
Time Estimation, GL Matching, and Publishing endpoints.
"""
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse

from app.models.pipeline_models import (
    AgentExecution,
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
from app.services.recon_service import recon_service
from app.models.recon import PaginatedQueryResponse
from app.config import settings

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline Orchestrator"])

# Stage artefacts downloadable through /batches/{id}/artifacts/{kind}
ARTIFACT_FIELDS = {
    "statement": ("batch_file_path", "text/csv"),
    "anomaly_candidates": ("anomaly_file_path", "text/csv"),
    "matched": ("matched_file_path", "text/csv"),
    "unmatched_bank": ("unmatched_file_path", "text/csv"),
    "outstanding_gl": ("outstanding_file_path", "text/csv"),
    "recon_exceptions": ("ambiguous_file_path", "text/csv"),
    "sla_metrics": ("sla_metrics_file_path", "text/csv"),
}

# Stage 6 result sets queryable through /batches/{id}/recon/{dataset}
RECON_DATASETS = {
    "matched": "_matched.csv",
    "unmatched_bank": "_unmatched_bank.csv",
    "outstanding_gl": "_outstanding_gl.csv",
    "ambiguous": "_ambiguous.csv",
}


def _exists(path: Optional[str]) -> bool:
    return bool(path and Path(path).exists())


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
    results = pipeline_orchestrator.batch_match_results.get(
        batch_id, {"matched": [], "unmatched_reconciling": [], "ambiguous": []}
    )

    return {
        "batch_id": batch_id,
        "summary": batch.gl_summary,
        "matched_sample": results.get("matched", [])[:100],
        "unmatched_sample": results.get("unmatched_reconciling", [])[:100],
        "ambiguous_sample": results.get("ambiguous", [])[:100],
        "artifacts": {
            "matched": batch.matched_file_path,
            "unmatched_bank": batch.unmatched_file_path,
            "outstanding_gl": batch.outstanding_file_path,
            "recon_exceptions": batch.ambiguous_file_path,
            "sla_metrics": batch.sla_metrics_file_path,
        },
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


@router.get("/batches/{batch_id}/file")
def download_batch_file(batch_id: str):
    """Downloads the original ingested batch statement CSV."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    batch = pipeline_orchestrator.batches[batch_id]

    file_path: Optional[Path] = None
    if batch.batch_file_path:
        p = Path(batch.batch_file_path)
        if p.exists():
            file_path = p

    if not file_path:
        p = settings.batches_dir / batch.filename
        if p.exists():
            file_path = p

    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Statement file for batch '{batch_id}' not found on server.")

    return FileResponse(
        path=str(file_path),
        filename=batch.filename,
        media_type="text/csv"
    )


@router.get("/batches/{batch_id}/anomalies/file")
def download_anomaly_candidates_file(batch_id: str):
    """Downloads the Stage 3 rule engine candidate anomalies CSV file."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    batch = pipeline_orchestrator.batches[batch_id]

    file_path: Optional[Path] = None
    if batch.anomaly_file_path:
        p = Path(batch.anomaly_file_path)
        if p.exists():
            file_path = p

    if not file_path:
        p = settings.anomalies_dir / f"{batch_id}_candidates.csv"
        if p.exists():
            file_path = p

    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail=f"No candidate anomalies file found for batch '{batch_id}'.")

    return FileResponse(
        path=str(file_path),
        filename=f"{batch_id}_anomaly_candidates.csv",
        media_type="text/csv"
    )


@router.post("/batches/{batch_id}/agent/classify", response_model=AgentExecution)
def trigger_agent_classification(
    batch_id: str,
    stage_key: str = Query("STAGE_4_ANOMALY", description="Pipeline stage whose agent should run"),
    agent_id: Optional[str] = Query(None, description="Override the agent ID configured for the stage")
):
    """
    Manually re-dispatches a stage's agent.

    The pipeline already submits Stage 4, Stage 6 and Stage 7 agents automatically
    as their input artefacts are produced — this endpoint exists to retry a
    submission that failed, or to run a stage against a different agent ID.
    """
    try:
        return pipeline_orchestrator.trigger_agent_classification(
            batch_id=batch_id,
            stage_key=stage_key,
            agent_id=agent_id
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent trigger failed: {str(e)}")


@router.get("/batches/{batch_id}/agent/status")
def get_batch_agent_status(batch_id: str):
    """Returns every automatic agent dispatch recorded against this batch."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    batch = pipeline_orchestrator.batches[batch_id]
    return {
        "batch_id": batch_id,
        "executions": batch.agent_executions,
        "artifacts": {
            "anomaly_candidates": _exists(batch.anomaly_file_path),
            "recon_exceptions": _exists(batch.ambiguous_file_path),
            "sla_metrics": _exists(batch.sla_metrics_file_path),
            "raw_statement": _exists(batch.batch_file_path),
        },
    }


@router.get("/batches/{batch_id}/agent/output", response_model=Dict[str, AgentExecution])
def refresh_batch_agent_outputs(batch_id: str):
    """
    Polls the agent platform for every in-flight execution on this batch and
    returns the refreshed per-stage dispatch log.
    """
    try:
        return pipeline_orchestrator.refresh_agent_outputs(batch_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch agent output: {str(e)}")


@router.get("/agent/execution/{execution_id}")
def get_agent_execution_by_id(execution_id: str):
    """
    Fetches the execution output from Aava AI by arbitrary execution ID.
    """
    from app.services.agentic_anomaly_service import agentic_anomaly_service
    res = agentic_anomaly_service.agent_bridge.get_agent_execution_output(execution_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to retrieve execution"))
    return res



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


@router.get("/agent/available-agents")
def get_available_agents():
    """
    Returns the configured multi-agent team and their role assignments:
    - Stage 4 Anomaly Classification (CREWAI_AGENT_ANOMALY_ID)
    - Stage 7 SLA & Urgency (CREWAI_AGENT_SLA_ID)
    - Stage 6 Exception Verification (CREWAI_AGENT_RECON_ID)
    - Stage 2 Ingestion & Extraction (CREWAI_AGENT_EXTRACTION_ID)
    - Workbench Collab (CREWAI_AGENT_COLLAB_ID)
    """
    from app.services.agentic_anomaly_service import agentic_anomaly_service
    return agentic_anomaly_service.agent_bridge.get_configured_agents()





@router.get("/batches/{batch_id}/artifacts/{kind}")
def download_batch_artifact(batch_id: str, kind: str):
    """
    Downloads any stage artefact produced for this batch:
    statement, anomaly_candidates, matched, unmatched_bank, outstanding_gl,
    recon_exceptions, sla_metrics.
    """
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    if kind not in ARTIFACT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown artefact '{kind}'. Expected one of: {sorted(ARTIFACT_FIELDS)}"
        )

    batch = pipeline_orchestrator.batches[batch_id]
    field, media_type = ARTIFACT_FIELDS[kind]
    path_str = getattr(batch, field, None)

    if not _exists(path_str):
        raise HTTPException(
            status_code=404,
            detail=f"Artefact '{kind}' has not been produced for batch '{batch_id}'."
        )

    path = Path(path_str)
    return FileResponse(path=str(path), filename=path.name, media_type=media_type)


@router.get("/batches/{batch_id}/recon/{dataset}", response_model=PaginatedQueryResponse)
def query_batch_recon_dataset(
    batch_id: str,
    dataset: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    account: Optional[str] = Query(None, description="Filter by account number/substring"),
    tier: Optional[str] = Query(None, description="Filter matched rows by tier, e.g. TIER_1_EXACT"),
):
    """
    Pages through this batch's Stage 6 reconciliation output:
    matched, unmatched_bank, outstanding_gl or ambiguous.

    These are the results of the live pipeline run for the batch — the same
    4-tier waterfall the reconciliation console displays.
    """
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    if dataset not in RECON_DATASETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown dataset '{dataset}'. Expected one of: {sorted(RECON_DATASETS)}"
        )

    target = settings.batch_results_dir / f"{batch_id}{RECON_DATASETS[dataset]}"
    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Stage 6 has not produced '{dataset}' for batch '{batch_id}' yet. "
                "Reconciliation runs once every escalated anomaly is signed off."
            )
        )

    return recon_service.query_csv_results(target, page, page_size, account, tier)
