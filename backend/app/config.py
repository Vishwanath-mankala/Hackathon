"""
Application Configuration.
"""
import logging
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Reconciliation & Feed Processing API"
    app_version: str = "1.0.0"
    app_description: str = (
        "Production-ready FastAPI REST API backend wrapping feed generation, "
        "structural gating, tiered rule engine reconciliation, and diagnostics."
    )
    debug: bool = True

    # Directories
    project_root: Path = PROJECT_ROOT
    output_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut"
    batches_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "ingestion_batches"
    manifest_path: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "ingestion_batches" / "manifest.csv"
    cache_path: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "cache_gl_cashbook.csv"
    results_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "recon_results"
    anomalies_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "anomalies"

    # Runtime batch artefact directories (written by the live pipeline)
    quarantine_dir: Path = PROJECT_ROOT / "data" / "quarantined_batches"
    ingestion_storage_dir: Path = PROJECT_ROOT / "data" / "ingestion_storage"
    batch_results_dir: Path = PROJECT_ROOT / "data" / "batch_results"
    sla_metrics_dir: Path = PROJECT_ROOT / "data" / "sla_metrics"
    # Stage 1 forecast inputs, per-batch history snapshots and the master
    # run_history.csv — the knowledge base the estimator calibrates from and the
    # forecast agent reasons over. Point it at persistent storage in deployment.
    forecast_dir: Path = PROJECT_ROOT / "data" / "forecasts"
    sftp_dir: Path = PROJECT_ROOT / "incoming_sftp"

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = ["*"]

    # =========================================================================
    # Agent Platform Integration (CrewAI / Multi-Agent API)
    # =========================================================================
    crewai_enabled: bool = True
    crewai_api_url: str = "https://int-ai.aava.ai/agents/execute/agent-executions"
    crewai_retrieval_url: str = "https://int-ai.aava.ai/agents/execute/history/execution"
    crewai_api_key: Optional[str] = None

    # =========================================================================
    # Multi-Agent Role IDs
    #
    # There are no defaults on purpose. An agent ID is issued by the agent
    # platform when the agent is created there — it cannot be guessed, and a
    # wrong ID submits a batch to somebody else's agent. Set each one in .env
    # from the platform's agent page. A stage whose ID is unset is reported as
    # SKIPPED (not configured) and the deterministic local pipeline result
    # stands.
    # =========================================================================
    crewai_agent_id: Optional[str] = None            # optional global fallback
    crewai_agent_forecast_id: Optional[str] = None   # Stage 1 Processing Time Forecast (history-aware)
    crewai_agent_anomaly_id: Optional[str] = None    # Stage 4 Anomaly Classification & Risk Scoring
    crewai_agent_sla_id: Optional[str] = None        # Stage 7 SLA Analysis & Urgency Classification
    crewai_agent_recon_id: Optional[str] = None      # Stage 6 Reconciliation & Exception Verification
    crewai_agent_extraction_id: Optional[str] = None # Stage 1 Ingestion & Statement Data Extraction
    crewai_agent_collab_id: Optional[str] = None     # Non-pipeline developer collab agent

    crewai_workflow_id: Optional[str] = "reconciliation-multiagent-flow"
    crewai_timeout_seconds: float = 60.0

    # Automatic (non-interactive) agent dispatch — Stage 4 / 6 / 7 agents are
    # fired by the orchestrator as their input artefacts become available.
    auto_agent_dispatch: bool = True

    # Auto-ingest every statement waiting in incoming_sftp/ at application start
    # (ARCHITECTURE.md Stage 1: "Automated directory polling for incoming SFTP drops").
    sftp_auto_ingest: bool = True

    # =========================================================================
    # Processing-time calibration & forecast
    #
    # The estimator derives its throughput and per-escalation queue-wait from
    # the run history rather than trusting a laptop-measured constant. It only
    # does so once enough runs of a meaningful size exist; tiny test batches
    # sit on the formula's floors and carry no timing signal.
    # =========================================================================
    calibration_min_runs: int = 5          # eligible runs before HISTORY replaces DEFAULT
    calibration_min_records: int = 200     # runs smaller than this are floor noise
    calibration_window: int = 50           # most recent eligible runs considered
    forecast_history_rows: int = 60        # rows of history bundled for the forecast agent
    forecast_poll_seconds: float = 10.0    # server-side poll interval for a forecast result
    forecast_poll_max_attempts: int = 90   # ~15 minutes, then TIMED_OUT

    # One env file for the whole backend, at the repo root next to .env.example.
    # It used to also load backend/.env and the CWD-relative ".env", which meant a
    # stale copy could silently shadow the real one — see _warn_on_stray_env_files.
    model_config = {
        "env_file": PROJECT_ROOT / ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


def _warn_on_stray_env_files() -> None:
    """
    Only PROJECT_ROOT/.env is read. A second file elsewhere looks like it is
    configuring the app but is silently ignored, so say so loudly rather than
    letting someone edit the wrong file.
    """
    canonical = (PROJECT_ROOT / ".env").resolve()
    seen = {canonical}

    for candidate in (PROJECT_ROOT / "backend" / ".env", Path.cwd() / ".env"):
        try:
            if not candidate.exists():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
        except OSError:
            continue

        logging.getLogger(__name__).warning(
            "Ignoring stray env file %s — configuration is read only from %s. "
            "Delete the stray copy to avoid confusion.",
            resolved, canonical,
        )


_warn_on_stray_env_files()

for _d in (
    settings.anomalies_dir,
    settings.ingestion_storage_dir,
    settings.quarantine_dir,
    settings.batch_results_dir,
    settings.sla_metrics_dir,
    settings.forecast_dir,
    settings.sftp_dir,
):
    _d.mkdir(parents=True, exist_ok=True)
