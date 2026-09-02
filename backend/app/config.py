"""
Application Configuration.
"""
from pathlib import Path
from typing import List
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

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = ["*"]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

