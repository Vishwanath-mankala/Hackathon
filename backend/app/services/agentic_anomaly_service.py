"""
Agentic Anomaly Scoring & Auto-Remediation Service.
Performs row-level rule validation across full batch context, agentic anomaly evaluation
(feeding the CrewAI / Aava multi-agent platform), safe auto-remediation,
re-validation loop, and human escalation queue management.
"""
import re
import uuid
import json
import logging
import requests

import pandas as pd
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from pathlib import Path

from app.models.pipeline_models import AnomalyItem
from app.config import settings

logger = logging.getLogger(__name__)

VALID_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR"}
DEFAULT_KNOWN_ACCOUNTS = {f"ACC#{str(i).zfill(5)}" for i in range(1, 100)}


class CrewAIAgentBridge:
    """
    Dedicated Integration Bridge for CrewAI / Multi-Agent Platforms.
    Connects to Aava AI or external CrewAI agent execution endpoints.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        retrieval_url: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        timeout: float = 60.0
    ):
        self.api_url = api_url or settings.crewai_api_url
        self.retrieval_url = retrieval_url or settings.crewai_retrieval_url
        self.api_key = api_key or settings.crewai_api_key
        self.agent_id = str(agent_id or settings.crewai_agent_id or "") or None
        self.timeout = timeout or settings.crewai_timeout_seconds
        self.enabled = settings.crewai_enabled or bool(self.api_url)

    def is_enabled(self) -> bool:
        return bool(self.api_url) and (self.enabled or settings.crewai_enabled)

    def test_connection(self) -> Dict[str, Any]:
        """Validates connectivity to the configured agent platform."""
        if not self.api_url:
            return {
                "connected": False,
                "configured": False,
                "message": "CREWAI_API_URL not configured. Set CREWAI_API_URL in .env to enable external agents.",
                "local_fallback_active": True
            }

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key or ''}",
                "Origin": "https://int-ai.aava.ai"
            }
            res = requests.options(self.api_url, headers=headers, timeout=5)
            if res.status_code in [200, 204, 405]:
                return {
                    "connected": True,
                    "configured": True,
                    "status_code": res.status_code,
                    "execution_url": self.api_url,
                    "retrieval_url": self.retrieval_url,
                    "agent_id": self.agent_id,
                    "local_fallback_active": False,
                    "message": "External Agent platform reachable and ready."
                }
        except Exception:
            pass

        return {
            "connected": bool(self.api_key and self.api_url),
            "configured": bool(self.api_url),
            "execution_url": self.api_url,
            "retrieval_url": self.retrieval_url,
            "agent_id": self.agent_id,
            "configured_agents": self.get_configured_agents(),
            "local_fallback_active": False if self.api_key else True,
            "message": "Aava AI Agent platform configured with Bearer token."
        }

    def get_configured_agents(self) -> List[Dict[str, Any]]:
        """
        Returns the multi-agent roster wired into the pipeline.

        `id` is whatever the corresponding CREWAI_AGENT_*_ID environment variable
        holds — there is no built-in default, because an agent ID is issued by the
        platform and cannot be guessed. `configured` is False when that variable is
        unset, in which case the stage is skipped rather than submitted blind.
        `stage_key` is the orchestrator hook the agent is dispatched from; agents
        with `auto_dispatch=False` are never fired by the pipeline.
        """
        roster = [
            {
                "key": "CREWAI_AGENT_FORECAST_ID",
                "id": settings.crewai_agent_forecast_id,
                "stage_key": "STAGE_1_FORECAST",
                "name": "Processing Time Forecast & Calibration Analyst",
                "role": "Senior Batch Capacity & Forecasting Analyst",
                "stage": "Stage 1: Processing Time Forecast",
                "description": (
                    "Predicts this batch's processing time and SLA breach risk before it is processed, "
                    "from its ingest-time features and the run history of comparable batches."
                ),
                "input_artifact": "{batch_id}_forecast_input.csv + {batch_id}_run_history.csv",
                "auto_dispatch": True,
                "human_intervention": False,
                "is_default": False,
            },
            {
                "key": "CREWAI_AGENT_ANOMALY_ID",
                "id": settings.crewai_agent_anomaly_id,
                "stage_key": "STAGE_4_ANOMALY",
                "name": "Enterprise Risk & Anomaly Detection Engine",
                "role": "Senior Enterprise Risk Analytics Specialist",
                "stage": "Stage 4: Anomaly Classification & Severity Scoring",
                "description": "Classifies Structural, Semantic, Timing and Referential anomaly candidates and assigns risk severity scores.",
                "input_artifact": "{batch_id}_candidates.csv",
                "auto_dispatch": True,
                "human_intervention": False,
                "is_default": True,
            },
            {
                "key": "CREWAI_AGENT_RECON_ID",
                "id": settings.crewai_agent_recon_id,
                "stage_key": "STAGE_6_RECON",
                "name": "Verification Reconciliation & Exception Specialist",
                "role": "Senior Exception Management Specialist",
                "stage": "Stage 6: GL Reconciliation Exception Review",
                "description": "Reviews ambiguous multi-candidate ties and unmatched reconciling items; proposes tie-breaks for analyst sign-off.",
                "input_artifact": "{batch_id}_recon_exceptions.csv",
                "auto_dispatch": True,
                "human_intervention": True,
                "is_default": False,
            },
            {
                "key": "CREWAI_AGENT_SLA_ID",
                "id": settings.crewai_agent_sla_id,
                "stage_key": "STAGE_7_SLA",
                "name": "SLA Analysis & Urgency Classifier",
                "role": "Senior SLA Compliance Analyst Agent",
                "stage": "Stage 7: SLA Prediction & Urgency Triage",
                "description": "Derives batch urgency tier, SLA breach probability and escalation recommendations from the time estimate.",
                "input_artifact": "{batch_id}_sla_metrics.csv",
                "auto_dispatch": True,
                "human_intervention": False,
                "is_default": False,
            },
            {
                "key": "CREWAI_AGENT_EXTRACTION_ID",
                "id": settings.crewai_agent_extraction_id,
                "stage_key": "STAGE_1_EXTRACTION",
                "name": "Financial Statement Extraction & Traceability",
                "role": "Senior Financial Data Extraction Engineer",
                "stage": "Stage 1: Ingestion & Field Extraction",
                "description": "Extracts non-CSV statement formats (MT940, BAI2) into the canonical schema with per-field evidence traceability.",
                "input_artifact": "{batch_id}_{filename} (raw statement)",
                "auto_dispatch": False,
                "human_intervention": False,
                "is_default": False,
            },
            {
                "key": "CREWAI_AGENT_COLLAB_ID",
                "id": settings.crewai_agent_collab_id,
                "stage_key": "NON_PIPELINE",
                "name": "Frontend Architecture Collab Agent",
                "role": "Collab & Orchestration Agent",
                "stage": "Cross-cutting: not part of the batch pipeline",
                "description": "Developer-facing UI/UX architecture collaboration tool. Never fired by the batch pipeline.",
                "input_artifact": "uiux.json (manually authored)",
                "auto_dispatch": False,
                "human_intervention": True,
                "is_default": False,
            },
        ]

        for agent in roster:
            agent["id"] = str(agent["id"]) if agent["id"] else None
            agent["configured"] = agent["id"] is not None

        return roster

    def get_agent_for_stage(self, stage_key: str) -> Optional[Dict[str, Any]]:
        return next((a for a in self.get_configured_agents() if a["stage_key"] == stage_key), None)

    @staticmethod
    def _zip_members(file_path: Path, extra_files: Optional[List[Path]]) -> List[Path]:
        """
        The primary artefact plus any extras, deduplicated by resolved path and
        by archive name (zipfile happily writes two members with one name and
        some readers choke on it). A missing extra is skipped with a warning
        rather than failing the submission — the first batch ever has no
        history to bundle, and its forecast should still go out.
        """
        members: List[Path] = []
        seen_paths = set()
        seen_names = set()
        for candidate in [file_path] + list(extra_files or []):
            p = Path(candidate)
            if not p.exists():
                if p != file_path:
                    logger.warning(f"Bundle member {p.name} does not exist; submitting without it.")
                continue
            key = str(p.resolve())
            if key in seen_paths or p.name in seen_names:
                continue
            seen_paths.add(key)
            seen_names.add(p.name)
            members.append(p)
        return members

    def submit_batch_to_agent(
        self,
        file_path: Path,
        agent_id: Optional[str] = None,
        extra_files: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        """
        Submits a stage artefact to the external Agent API
        (https://int-ai.aava.ai/agents/execute/agent-executions) as multipart/form-data.

        `file_path` is the primary artefact: it names the zip and is reported as
        `target_file`. `extra_files` ride along as further members of the same
        zip — the Stage 1 forecast bundles its history snapshot this way.
        """
        members = self._zip_members(file_path, extra_files)
        bundled = [m.name for m in members]

        if not self.is_enabled():
            return {
                "success": False,
                "message": "External Agent API not enabled or URL not configured.",
                "http_status": "DISABLED",
                "submitted_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "target_file": file_path.name,
                "bundled_files": bundled,
            }

        target_agent_id = agent_id or self.agent_id
        if not target_agent_id:
            return {
                "success": False,
                "message": (
                    "No agent ID supplied and no fallback configured. Set the stage's "
                    "CREWAI_AGENT_*_ID in .env to the ID issued by the agent platform."
                ),
                "http_status": "NOT_CONFIGURED",
                "submitted_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "target_file": file_path.name,
                "bundled_files": bundled,
                "agent_id": None,
            }
        target_agent_id = str(target_agent_id)
        headers = {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://int-ai.aava.ai",
            "Referer": f"https://int-ai.aava.ai/launchpad/build/agent/playground?id={target_agent_id}&fromDashboard=true"
        }
        data = {
            "agentId": target_agent_id,
            "userInputs": "{}"
        }

        try:
            import io
            import zipfile

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for member in members:
                    zf.write(member, arcname=member.name)
            zip_bytes = zip_buf.getvalue()

            files = {
                "files": (f"{file_path.stem}.zip", zip_bytes, "application/zip")
            }
            resp = requests.post(
                self.api_url,
                headers=headers,
                data=data,
                files=files,
                timeout=self.timeout
            )

            if resp.status_code in (200, 201):
                body = resp.json()
                res_data = body.get("data", {})
                return {
                    "success": True,
                    "job_id": res_data.get("jobId"),
                    "agent_execution_id": res_data.get("agentExecutionId"),
                    "message": res_data.get("message", "Agent job submitted successfully"),
                    "http_status": res_data.get("httpStatus", "OK"),
                    "submitted_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "target_file": file_path.name,
                    "bundled_files": bundled,
                    "agent_id": target_agent_id
                }
            else:
                logger.warning(f"Agent execution submission returned HTTP {resp.status_code}: {resp.text}")
                return {
                    "success": False,
                    "http_status": str(resp.status_code),
                    "message": f"Agent platform returned HTTP {resp.status_code}: {resp.text[:200]}",
                    "submitted_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "target_file": file_path.name,
                    "bundled_files": bundled,
                    "agent_id": target_agent_id
                }
        except Exception as e:
            logger.error(f"Failed to submit file to Agent API: {e}")
            return {
                "success": False,
                "http_status": "ERROR",
                "message": f"Connection error: {str(e)}",
                "submitted_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "target_file": file_path.name,
                "bundled_files": bundled,
                "agent_id": target_agent_id
            }

    def get_agent_execution_output(self, execution_id: str) -> Dict[str, Any]:
        """
        Retrieves the asynchronous execution output from the configured agent history endpoint
        (CREWAI_RETRIEVAL_URL, defaults to https://int-ai.aava.ai/agents/execute/history/execution?execution_id={execution_id}).
        """
        if not self.api_key:
            return {
                "success": False,
                "message": "Bearer API key not configured.",
                "executionId": execution_id
            }

        base_url = self.retrieval_url or settings.crewai_retrieval_url
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}execution_id={execution_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://int-ai.aava.ai"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "http_status": 200,
                    "executionId": data.get("executionId", execution_id),
                    "agentId": data.get("agentId"),
                    "agentName": data.get("agentName"),
                    "output": data.get("output"),
                    "status": data.get("status"),
                    "createdAt": data.get("createdAt"),
                    "modifiedAt": data.get("modifiedAt")
                }
            else:
                return {
                    "success": False,
                    "http_status": resp.status_code,
                    "message": f"Platform returned HTTP {resp.status_code}: {resp.text[:200]}",
                    "executionId": execution_id
                }
        except Exception as e:
            logger.error(f"Failed to fetch execution output for {execution_id}: {e}")
            return {
                "success": False,
                "http_status": "ERROR",
                "message": f"Network error: {str(e)}",
                "executionId": execution_id
            }




class AgenticAnomalyService:
    def __init__(
        self,
        crewai_api_url: Optional[str] = None,
        crewai_retrieval_url: Optional[str] = None,
        crewai_api_key: Optional[str] = None,
        crewai_agent_id: Optional[str] = None
    ):
        self.crewai_api_url = crewai_api_url or settings.crewai_api_url
        self.crewai_retrieval_url = crewai_retrieval_url or settings.crewai_retrieval_url
        self.crewai_api_key = crewai_api_key or settings.crewai_api_key
        self.crewai_agent_id = crewai_agent_id or settings.crewai_agent_id
        self.agent_bridge = CrewAIAgentBridge(
            api_url=self.crewai_api_url,
            retrieval_url=self.crewai_retrieval_url,
            api_key=self.crewai_api_key,
            agent_id=self.crewai_agent_id
        )
        self.known_accounts = set(DEFAULT_KNOWN_ACCOUNTS)
        self._load_gl_accounts_cache()

    def _load_gl_accounts_cache(self):
        """Loads accounts from GL cashbook cache if available."""
        if settings.cache_path.exists():
            try:
                df = pd.read_csv(settings.cache_path, usecols=["account"], dtype=str)
                accounts = set(df["account"].dropna().str.strip().unique())
                if accounts:
                    self.known_accounts.update(accounts)
            except Exception as e:
                logger.warning(f"Could not load GL accounts from cache: {e}")

    def evaluate_batch(
        self,
        df: pd.DataFrame,
        batch_id: str,
        batch_file_path: Optional[Path] = None
    ) -> Tuple[pd.DataFrame, List[AnomalyItem], Optional[Path]]:
        """
        Executes Stage [3] Row-level rules and Stage [4] Agentic Anomaly Scoring.
        Separates valid rows from anomalous rows per ARCHITECTURE.md standard dimensions:
        - STRUCTURAL: Malformed amounts, syntax errors, duplicate transaction IDs
        - SEMANTIC: Inverted debit/credit polarity, unrecognized flags, zero amounts, currency drift
        - TIMING: Date formatting slack (slashes vs ISO), post-dating, transposed dates
        - REFERENTIAL: Unknown bank accounts, missing GL chart mappings
        Applies Stage [5a] Auto-remediation for safe pattern issues and re-validates them.
        Generates and saves Stage 3 anomaly candidate files.
        """
        anomalies: List[AnomalyItem] = []
        clean_df = df.copy()

        seen_txn_ids = set()
        duplicate_indices = set()

        # 1. Cross-row duplicate check (STRUCTURAL)
        if "external_txn_id" in clean_df.columns:
            for idx, txn_id in clean_df["external_txn_id"].items():
                s_id = str(txn_id).strip() if pd.notna(txn_id) else ""
                if not s_id:
                    continue
                if s_id in seen_txn_ids:
                    duplicate_indices.add(idx)
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=s_id,
                        account=str(clean_df.at[idx, "account"]) if "account" in clean_df.columns else "UNKNOWN",
                        raw_amount=str(clean_df.at[idx, "amount"]) if "amount" in clean_df.columns else "0",
                        error_type="DUPLICATE_TRANSACTION_ID",
                        severity="CRITICAL",
                        category="STRUCTURAL",
                        description=f"Transaction ID '{s_id}' appears multiple times within the batch.",
                        auto_remediable=False,
                        suggested_fix=None,
                        override_fields=["external_txn_id"],
                        status="ESCALATED",
                        confidence_score=0.98,
                        remediation_notes=(
                            "Two lines share this transaction ID. Only the source statement says whether "
                            "this is a duplicate transmission or a distinct transaction the bank mis-keyed. "
                            "Supply the correct external_txn_id, or quarantine the row."
                        )
                    ))
                else:
                    seen_txn_ids.add(s_id)

        # 2. Row-level field & referential checks
        remediations_to_apply = []

        for idx, row in clean_df.iterrows():
            if idx in duplicate_indices:
                continue

            row_dict = row.to_dict()
            txn_id = str(row_dict.get("external_txn_id", "")).strip()
            account = str(row_dict.get("account", "")).strip()
            amount_str = str(row_dict.get("amount", "")).strip()
            currency = str(row_dict.get("currency", "")).strip().upper()
            dc = str(row_dict.get("debit_credit", "")).strip().upper()
            booking_date = str(row_dict.get("booking_date", "")).strip()
            reference = str(row_dict.get("reference", "")).strip()

            # Check: Invalid / Missing Amount (SEMANTIC or STRUCTURAL)
            try:
                amt = float(amount_str.replace(",", "").replace("$", ""))
                if amt == 0.0:
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="ZERO_AMOUNT_LINE",
                        severity="HIGH",
                        category="SEMANTIC",
                        description="Transaction line declared with zero value ($0.00).",
                        auto_remediable=False,
                        suggested_fix=None,
                        override_fields=["amount"],
                        status="ESCALATED",
                        confidence_score=0.90,
                        remediation_notes=(
                            "Line declared with zero value, which carries no economic substance. "
                            "Read the true amount off the source statement and supply it, or quarantine "
                            "the row if the line is a memo entry."
                        )
                    ))
            except Exception:
                anomalies.append(AnomalyItem(
                    id=str(uuid.uuid4()),
                    row_index=int(idx),
                    external_txn_id=txn_id,
                    account=account,
                    raw_amount=amount_str,
                    booking_date=booking_date,
                    error_type="MALFORMED_AMOUNT",
                    severity="CRITICAL",
                    category="STRUCTURAL",
                    description=f"Amount value '{amount_str}' cannot be parsed as numeric float.",
                    auto_remediable=False,
                    suggested_fix=None,
                    override_fields=["amount"],
                    status="ESCALATED",
                    confidence_score=0.95,
                    remediation_notes=(
                        "The amount could not be parsed, so its true value is unknown. "
                        "Supply the amount from the source statement, or quarantine the row."
                    )
                ))

            # Check: Debit/Credit flag (SEMANTIC)
            if dc not in {"DR", "CR"}:
                fix_dc = None
                if dc in {"D", "DEBIT"}:
                    fix_dc = "DR"
                elif dc in {"C", "CREDIT"}:
                    fix_dc = "CR"

                if fix_dc:
                    item = AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="NON_CANONICAL_DR_CR",
                        severity="LOW",
                        category="SEMANTIC",
                        description=f"Debit/Credit flag '{dc}' is non-standard.",
                        auto_remediable=True,
                        suggested_fix={"debit_credit": fix_dc},
                        status="AUTO_REMEDIATED",
                        confidence_score=0.99,
                        remediation_notes=f"Auto-mapped '{dc}' to canonical '{fix_dc}'."
                    )
                    anomalies.append(item)
                    remediations_to_apply.append((idx, "debit_credit", fix_dc))
                else:
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="UNKNOWN_DR_CR",
                        severity="HIGH",
                        category="SEMANTIC",
                        description=f"Unrecognized DR/CR direction '{dc}'.",
                        auto_remediable=False,
                        suggested_fix=None,
                        override_fields=["debit_credit"],
                        status="ESCALATED",
                        confidence_score=0.80,
                        remediation_notes=(
                            "Direction flag is unrecognised and cannot be mapped to DR or CR without "
                            "guessing, which would invert the transaction's sign. Supply the direction "
                            "from the source statement, or quarantine the row."
                        )
                    ))

            # Check: Currency code (SEMANTIC)
            if currency not in VALID_CURRENCIES:
                raw_curr = str(row_dict.get("currency", "")).strip()
                if raw_curr.upper() in VALID_CURRENCIES:
                    fix_curr = raw_curr.upper()
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="UNNORMALIZED_CURRENCY",
                        severity="LOW",
                        category="SEMANTIC",
                        description=f"Currency '{raw_curr}' has casing or formatting drift.",
                        auto_remediable=True,
                        suggested_fix={"currency": fix_curr},
                        status="AUTO_REMEDIATED",
                        confidence_score=0.99,
                        remediation_notes=f"Normalized currency code to '{fix_curr}'."
                    ))
                    remediations_to_apply.append((idx, "currency", fix_curr))
                else:
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="INVALID_ISO_CURRENCY",
                        severity="HIGH",
                        category="SEMANTIC",
                        description=f"Currency '{raw_curr}' is not a recognized ISO banking currency.",
                        auto_remediable=False,
                        suggested_fix=None,
                        override_fields=["currency"],
                        status="ESCALATED",
                        confidence_score=0.85,
                        remediation_notes=(
                            "Currency is not a recognised ISO-4217 code. Defaulting it would misstate the "
                            "value of the transaction. Supply the correct 3-letter code, or quarantine the row."
                        )
                    ))

            # Check: Referential Integrity against GL Chart of Accounts (REFERENTIAL)
            if account and account not in self.known_accounts:
                normalized_acc = account.upper().replace(" ", "")
                if normalized_acc in self.known_accounts:
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="ACCOUNT_FORMAT_DRIFT",
                        severity="MEDIUM",
                        category="REFERENTIAL",
                        description=f"Account '{account}' matches GL chart of accounts after normalization.",
                        auto_remediable=True,
                        suggested_fix={"account": normalized_acc},
                        status="AUTO_REMEDIATED",
                        confidence_score=0.96,
                        remediation_notes=f"Normalized account identifier to '{normalized_acc}'."
                    ))
                    remediations_to_apply.append((idx, "account", normalized_acc))
                else:
                    anomalies.append(AnomalyItem(
                        id=str(uuid.uuid4()),
                        row_index=int(idx),
                        external_txn_id=txn_id,
                        account=account,
                        raw_amount=amount_str,
                        booking_date=booking_date,
                        error_type="UNKNOWN_GL_ACCOUNT",
                        severity="HIGH",
                        category="REFERENTIAL",
                        description=f"Account '{account}' not present in GL chart of accounts.",
                        auto_remediable=False,
                        suggested_fix=None,
                        override_fields=["account"],
                        status="ESCALATED",
                        confidence_score=0.75,
                        remediation_notes=(
                            "Account is not in the GL chart of accounts. It may be newly opened, renamed, "
                            "or mis-keyed upstream — nothing in the row says which. Assign the correct GL "
                            "account, or quarantine the row."
                        )
                    ))

            # Check: Date formatting (TIMING)
            if booking_date:
                if "/" in booking_date:
                    try:
                        parsed_d = pd.to_datetime(booking_date, dayfirst=True).strftime("%Y-%m-%d")
                        anomalies.append(AnomalyItem(
                            id=str(uuid.uuid4()),
                            row_index=int(idx),
                            external_txn_id=txn_id,
                            account=account,
                            raw_amount=amount_str,
                            booking_date=booking_date,
                            error_type="DATE_FORMAT_SLACK",
                            severity="LOW",
                            category="TIMING",
                            description=f"Date '{booking_date}' uses non-ISO slash format.",
                            auto_remediable=True,
                            suggested_fix={"booking_date": parsed_d, "value_date": parsed_d},
                            status="AUTO_REMEDIATED",
                            confidence_score=0.99,
                            remediation_notes=f"Auto-formatted booking date to ISO '{parsed_d}'."
                        ))
                        remediations_to_apply.append((idx, "booking_date", parsed_d))
                        if "value_date" in clean_df.columns:
                            remediations_to_apply.append((idx, "value_date", parsed_d))
                    except Exception:
                        pass

        # Apply safe auto-remediations
        for r_idx, col, val in remediations_to_apply:
            if col in clean_df.columns:
                clean_df.at[r_idx, col] = val

        # =====================================================================
        # STAGE 3 FILE GENERATION: Export Anomaly Candidates to CSV & JSON
        # =====================================================================
        candidate_csv_path: Optional[Path] = None
        if anomalies:
            try:
                candidate_csv_path = settings.anomalies_dir / f"{batch_id}_candidates.csv"
                candidate_json_path = settings.anomalies_dir / f"{batch_id}_candidates.json"

                candidate_rows = []
                for a in anomalies:
                    candidate_rows.append({
                        "row_index": a.row_index,
                        "external_txn_id": a.external_txn_id,
                        "account": a.account,
                        "raw_amount": a.raw_amount,
                        "booking_date": a.booking_date,
                        "error_type": a.error_type,
                        "category": a.category,
                        "severity": a.severity,
                        "status": a.status,
                        "confidence_score": a.confidence_score,
                        "description": a.description,
                        "suggested_fix": json.dumps(a.suggested_fix) if a.suggested_fix else ""
                    })

                cand_df = pd.DataFrame(candidate_rows)
                cand_df.to_csv(candidate_csv_path, index=False)
                with open(candidate_json_path, "w", encoding="utf-8") as jf:
                    json.dump(candidate_rows, jf, indent=2)
                logger.info(f"Generated Stage 3 anomaly candidates file: {candidate_csv_path}")
            except Exception as e:
                logger.error(f"Failed to write anomaly candidates file: {e}")

        return clean_df, anomalies, candidate_csv_path


agentic_anomaly_service = AgenticAnomalyService()
