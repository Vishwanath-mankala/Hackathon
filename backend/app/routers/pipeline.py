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
    AuditSignoff,
    SignoffRequest,
    BatchRecord,
    StructuralGateDetails,
    AnomalyItem,
    TimeEstimate,
    ForecastComparison,
    RunHistoryRow,
    CalibrationSummary,
    FeedQueueStatus,
    FeedResetResult,
    GLMatchSummary,
    PublishEvent,
    PipelineOverview,
    HumanResolveRequest,
    IngestionResponse
)
from app.services.pipeline_orchestrator import pipeline_orchestrator, QueueConflict
from app.services.publish_service import publish_service
from app.services.ingestion_service import ingestion_service
from app.services.recon_service import recon_service
from app.services.audit_service import audit_service
from app.services.run_history_service import run_history_service
from app.services.time_estimator_service import time_estimator_service
from app.models.recon import PaginatedQueryResponse
from app.config import settings

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline Orchestrator"])

# Stage artefacts downloadable through /batches/{id}/artifacts/{kind}
ARTIFACT_FIELDS = {
    "statement": ("batch_file_path", "text/csv"),
    "forecast_input": ("forecast_input_file_path", "text/csv"),
    "run_history": ("run_history_file_path", "text/csv"),
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
def pull_next_sftp_drop(
    filename: Optional[str] = Query(None, description="Specific queued sample file to ingest (retries a FAILED one)")
):
    """
    Ingests the next statement from the sample-feed queue.

    The queue is `manifest.csv` loaded into the database, so its position
    survives a restart and repeated pulls walk the feed in order. The batch is
    tagged `SAMPLE_FEED` and the manifest's declared record count and control
    total go through the structural gate. Real SFTP arrivals in
    `incoming_sftp/` are picked up by the startup poll.
    """
    try:
        batch, _origin, remaining = pipeline_orchestrator.pull_next_sftp_drop(filename=filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except QueueConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

    queue = pipeline_orchestrator.queue_status()
    position = next(
        (r["sequence"] for r in queue["recent"] if r.get("batch_id") == batch.batch_id), None
    )
    where = f"Feed batch {position} of {queue['total']}" if position else "Feed batch"
    message = f"{where} ({batch.filename}) ingested, tagged SAMPLE_FEED. Stage: {batch.stage}. {remaining} remaining."

    return IngestionResponse(
        batch_id=batch.batch_id,
        filename=batch.filename,
        message=message,
        stage=batch.stage,
        record_count=batch.total_records,
        gate_passed=bool(batch.gate_passed),
        quarantined=batch.stage == "GATE_QUARANTINED",
        time_estimate=batch.time_estimate,
        queue_remaining=remaining,
    )


@router.get("/feed/queue", response_model=FeedQueueStatus)
def get_feed_queue():
    """The sample-feed queue: how many files are pending, ingested, failed or missing, and which is next."""
    return pipeline_orchestrator.queue_status()


@router.post("/feed/reset", response_model=FeedResetResult)
def reset_feed():
    """
    Demo reset. Forgets every batch (registry, anomalies, match results, parked
    clocks, working frames), restores the GL cache to its full size and puts
    the sample feed back to the start. Keeps the run history, the sign-off
    trails and every artefact on disk.
    """
    try:
        return pipeline_orchestrator.reset_state(requeue=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")


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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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


@router.get("/batches/{batch_id}/forecast", response_model=ForecastComparison)
def get_batch_forecast(batch_id: str):
    """
    Local estimate vs the Stage 1 forecast agent's prediction vs the measured
    actual, plus where the estimator's constants came from. The agent forecast
    is issued before processing from ingest-time features and the run history;
    `agent_forecast.status` says whether it was received, is still pending,
    timed out, was unparseable, or was skipped because
    CREWAI_AGENT_FORECAST_ID is unset.
    """
    try:
        return pipeline_orchestrator.get_forecast_comparison(batch_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/run-history")
def get_run_history(
    limit: int = Query(50, ge=1, le=500),
    eligible_only: bool = Query(False, description="Only runs the estimator calibrates from"),
):
    """
    The processing-time knowledge base: one row per completed batch with its
    ingest-time features, outcome, measured machine/queue/wall seconds, the local
    estimate, the agent forecast and both signed errors. Newest first.
    """
    rows = [RunHistoryRow(**_history_row_payload(r)) for r in run_history_service.rows(limit, eligible_only)]
    return {
        "rows": rows,
        "calibration": time_estimator_service.calibration_summary(),
        "file": str(run_history_service.path),
    }


@router.get("/run-history/file")
def download_run_history():
    """Renders the whole run history to CSV and downloads it."""
    if run_history_service.stats()["total_runs_recorded"] == 0:
        raise HTTPException(status_code=404, detail="No run has been recorded yet.")
    path = run_history_service.export_csv()
    return FileResponse(path=str(path), filename=path.name, media_type="text/csv")


def _history_row_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    fields = RunHistoryRow.model_fields.keys()
    payload = {k: row.get(k) for k in fields}
    for int_key in ("record_count", "anomaly_count", "escalated_count", "matched_count"):
        payload[int_key] = int(payload.get(int_key) or 0)
    payload["file_size_mb"] = float(payload.get("file_size_mb") or 0.0)
    payload["gate_passed"] = bool(payload.get("gate_passed"))
    payload["eligible_for_calibration"] = bool(payload.get("eligible_for_calibration"))
    for text_key in ("completed_at", "source", "filename", "outcome", "provenance"):
        payload[text_key] = payload.get(text_key) or ""
    return payload


@router.post("/batches/{batch_id}/publish", response_model=PublishEvent)
def publish_batch_results(batch_id: str):
    """Broadcasts batch completion and reconciliation summary to downstream message bus."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    return pipeline_orchestrator.publish(batch_id)


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
    except ValueError as e:
        # Stage has no agent ID configured — a configuration problem, not a server fault.
        raise HTTPException(status_code=400, detail=str(e))
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
            "forecast_input": _exists(batch.forecast_input_file_path),
            "run_history": _exists(batch.run_history_file_path),
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
    - Stage 1 Processing Time Forecast (CREWAI_AGENT_FORECAST_ID)
    - Stage 4 Anomaly Classification (CREWAI_AGENT_ANOMALY_ID)
    - Stage 7 SLA & Urgency (CREWAI_AGENT_SLA_ID)
    - Stage 6 Exception Verification (CREWAI_AGENT_RECON_ID)
    - Stage 1 Ingestion & Extraction, manual only (CREWAI_AGENT_EXTRACTION_ID)
    - Workbench Collab (CREWAI_AGENT_COLLAB_ID)
    Each entry carries `configured: true|false`; there are no default IDs.
    """
    from app.services.agentic_anomaly_service import agentic_anomaly_service
    return agentic_anomaly_service.agent_bridge.get_configured_agents()





@router.get("/batches/{batch_id}/artifacts/{kind}")
def download_batch_artifact(batch_id: str, kind: str):
    """
    Downloads any stage artefact produced for this batch:
    statement, forecast_input, run_history (the snapshot the forecast agent
    saw), anomaly_candidates, matched, unmatched_bank, outstanding_gl,
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


# =============================================================================
# Stage 6 analyst sign-off & audit trail
#
# Ambiguous ties and reconciling items are the lines the waterfall deliberately
# refuses to settle alone. These endpoints record the human decision as
# append-only evidence — a correction supersedes, it never overwrites.
# =============================================================================
def _find_ambiguous_row(batch_id: str, row_key: str) -> Optional[Dict[str, Any]]:
    """
    Locates one ambiguous tie by its contested bank transaction ID.

    Reads the in-memory Stage 6 result when it is still there, and falls back to
    the exported CSV so sign-off keeps working after a restart.
    """
    results = pipeline_orchestrator.batch_match_results.get(batch_id) or {}
    for row in results.get("ambiguous", []):
        if str(row.get("ingest_external_txn_id")) == row_key:
            return row

    path = settings.batch_results_dir / f"{batch_id}_ambiguous.csv"
    if not path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return None
    if df.empty or "ingest_external_txn_id" not in df.columns:
        return None
    match = df[df["ingest_external_txn_id"].astype(str) == row_key]
    return match.iloc[0].to_dict() if not match.empty else None


def _candidate_ids(row: Dict[str, Any]) -> List[str]:
    """Normalises candidate_internal_txn_ids, which is a list in memory and a
    stringified list once it has been through CSV."""
    raw = row.get("candidate_internal_txn_ids")
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(c).strip() for c in raw if str(c).strip()]
    cleaned = str(raw).strip().strip("[]")
    return [c.strip().strip("'\"") for c in cleaned.split(",") if c.strip().strip("'\"")]


@router.post("/batches/{batch_id}/recon/{dataset}/signoff", response_model=AuditSignoff)
def record_analyst_signoff(batch_id: str, dataset: str, req: SignoffRequest):
    """
    Records an analyst's decision on one reconciliation line.

    For `ambiguous`: CONFIRM_PROVISIONAL, SELECT_ALTERNATIVE (with
    `chosen_internal_txn_id`, which must be one of that tie's own candidates), or
    LEAVE_UNSETTLED. For every other dataset: ATTEST_REVIEWED or
    FLAG_FOR_INVESTIGATION.
    """
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")
    if dataset not in RECON_DATASETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown dataset '{dataset}'. Expected one of: {sorted(RECON_DATASETS)}"
        )

    valid = audit_service.valid_actions(dataset)
    if req.action not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Action '{req.action}' is not valid for dataset '{dataset}'. Expected one of: {sorted(valid)}"
        )

    if not req.row_key.strip():
        raise HTTPException(status_code=400, detail="row_key is required.")

    chosen = req.chosen_internal_txn_id

    if dataset == "ambiguous":
        row = _find_ambiguous_row(batch_id, req.row_key)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No ambiguous tie '{req.row_key}' in batch '{batch_id}'."
            )

        candidates = _candidate_ids(row)

        if req.action == "SELECT_ALTERNATIVE":
            if not chosen:
                raise HTTPException(
                    status_code=400,
                    detail="SELECT_ALTERNATIVE requires chosen_internal_txn_id."
                )
            if candidates and str(chosen) not in candidates:
                # Settling against a row that never competed for this line would
                # hide two errors instead of surfacing one.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"GL entry '{chosen}' was not a candidate for tie '{req.row_key}'. "
                        f"Candidates were: {candidates}"
                    )
                )
        elif req.action == "CONFIRM_PROVISIONAL":
            chosen = row.get("chosen_internal_txn_id")
        else:
            chosen = None

    record, superseded = audit_service.record(
        batch_id=batch_id,
        dataset=dataset,
        row_key=req.row_key.strip(),
        action=req.action,
        analyst=(req.analyst or "console-operator").strip(),
        chosen_internal_txn_id=str(chosen) if chosen else None,
        analyst_notes=(req.analyst_notes or None),
    )
    return record


@router.get("/batches/{batch_id}/signoffs", response_model=List[AuditSignoff])
def list_batch_signoffs(
    batch_id: str,
    dataset: Optional[str] = Query(None, description="Filter to one result set"),
    effective_only: bool = Query(
        False,
        description="Return only the decision currently standing for each row, dropping superseded ones"
    ),
):
    """Returns the sign-off audit trail for a batch, oldest first."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    if effective_only:
        records = list(audit_service.effective_for_batch(batch_id).values())
        records.sort(key=lambda s: s.signed_at)
    else:
        records = audit_service.list_for_batch(batch_id)

    if dataset:
        records = [s for s in records if s.dataset == dataset]
    return records


@router.get("/batches/{batch_id}/signoffs/file")
def download_signoff_trail(batch_id: str):
    """Downloads the append-only sign-off trail as CSV for an auditor."""
    if batch_id not in pipeline_orchestrator.batches:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    path = audit_service.signoff_file(batch_id)
    if not path:
        raise HTTPException(
            status_code=404,
            detail=f"No sign-off has been recorded for batch '{batch_id}' yet."
        )
    return FileResponse(path=str(path), filename=path.name, media_type="text/csv")
