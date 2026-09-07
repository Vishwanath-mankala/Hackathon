"""
Application Configuration.
"""
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
    quarantine_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "recon_results" / "quarantined_batches"
    anomalies_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "anomalies"
    ingestion_storage_dir: Path = PROJECT_ROOT / "File-Gen Scripts" / "OutPut" / "ingestion_storage"

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
    crewai_agent_id: str = "56800"

    # Multi-Agent Specialized Role IDs
    crewai_agent_anomaly_id: str = "56800"      # Stage 4 Anomaly Classification & Risk Scoring
    crewai_agent_sla_id: str = "55551"          # Stage 5 SLA Analysis & Urgency Classification
    crewai_agent_recon_id: str = "56797"        # Stage 6 Reconciliation & Exception Verification
    crewai_agent_extraction_id: str = "56231"   # Stage 2 Ingestion & Financial Statement Data Extraction
    crewai_agent_collab_id: str = "7723"        # Frontend Architecture Collab Agent

    crewai_workflow_id: Optional[str] = "reconciliation-multiagent-flow"
    crewai_timeout_seconds: float = 60.0

    model_config = {
        "env_file": (PROJECT_ROOT / ".env", Path(__file__).resolve().parents[1] / ".env", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
settings.anomalies_dir.mkdir(parents=True, exist_ok=True)
settings.ingestion_storage_dir.mkdir(parents=True, exist_ok=True)
