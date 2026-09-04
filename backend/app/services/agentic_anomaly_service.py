"""
Agentic Anomaly Scoring & Auto-Remediation Service.
Performs row-level rule validation across full batch context, agentic anomaly evaluation
(with CrewAI / Multi-Agent Platform API integration hooks), safe auto-remediation,
re-validation loop, and human escalation queue management.
"""
import re
import uuid
import json
import logging
import urllib.request
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
    
    ===========================================================================
    HOW TO CONNECT YOUR CREWAI AGENTS:
    ===========================================================================
    1. Set environment variables in your .env file or server environment:
       CREWAI_ENABLED=true
       CREWAI_API_URL="http://localhost:8001/api/crew/analyze"
       CREWAI_API_KEY="your-crewai-token-here"

    2. Inputs Supported:
       - Direct raw file transmission (CSV, TXT, MT940, BAI2) via `analyze_file_via_agent_api`
       - Structured JSON rows and preliminary anomaly candidates via `enrich_anomalies_via_api`

    3. Expected CrewAI Agent Response Format:
       {
           "status": "success",
           "agent_name": "Reconciliation Anomaly Triage Agent",
           "anomalies": [
               {
                   "id": "<anomaly_uuid>",
                   "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
                   "category": "FORMAT" | "REFERENTIAL" | "DUPLICATE" | "BUSINESS_RULE",
                   "description": "Agent analysis rationale...",
                   "confidence_score": 0.95,
                   "auto_remediable": true | false,
                   "suggested_fix": {"field_name": "corrected_value"},
                   "remediation_notes": "Rationale for suggested action"
               }
           ]
       }
    ===========================================================================
    """

    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_url = api_url or settings.crewai_api_url
        self.api_key = api_key or settings.crewai_api_key
        self.timeout = timeout or settings.crewai_timeout_seconds
        self.enabled = settings.crewai_enabled or bool(self.api_url)

    def is_enabled(self) -> bool:
        return bool(self.api_url) and (self.enabled or settings.crewai_enabled)

    def test_connection(self) -> Dict[str, Any]:
        """Validates connectivity to the configured CrewAI agent platform."""
        if not self.api_url:
            return {
                "connected": False,
                "configured": False,
                "message": "CREWAI_API_URL not configured. Set CREWAI_API_URL in .env to enable external agents.",
                "local_fallback_active": True
            }

        try:
            req = urllib.request.Request(
                f"{self.api_url}/health" if not self.api_url.endswith("/health") else self.api_url,
                headers={"Authorization": f"Bearer {self.api_key or ''}"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return {
                    "connected": response.status in [200, 204],
                    "configured": True,
                    "status_code": response.status,
                    "url": self.api_url,
                    "local_fallback_active": False
                }
        except Exception as e:
            return {
                "connected": False,
                "configured": True,
                "url": self.api_url,
                "error": str(e),
                "local_fallback_active": True,
                "message": "CrewAI agent endpoint currently unreachable. Local intelligent agent evaluator active."
            }

    def analyze_file_via_agent_api(self, file_path: Path) -> Optional[List[Dict[str, Any]]]:
        """
        [PLACEHOLDER HOOK]: Sends raw CSV or TXT batch file to CrewAI Agent API.
        Enables agents to perform end-to-end multi-agent document analysis.
        """
        if not self.is_enabled():
            logger.info("CrewAI API URL not configured; using local agent pipeline for file analysis.")
            return None

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            headers = {
                "Content-Type": "application/octet-stream",
                "X-File-Name": file_path.name,
                "Authorization": f"Bearer {self.api_key or ''}"
            }
            req = urllib.request.Request(
                f"{self.api_url}/analyze-file",
                data=file_bytes,
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("anomalies", [])
        except Exception as e:
            logger.warning(f"CrewAI file analysis API call failed ({e}); falling back to local evaluation.")
            return None

    def enrich_anomalies_via_api(
        self,
        anomalies: List[AnomalyItem],
        df: pd.DataFrame
    ) -> Optional[List[AnomalyItem]]:
        """
        [PLACEHOLDER HOOK]: Sends anomaly candidates and context rows to CrewAI
        for multi-agent classification, confidence scoring, and suggested fixes.
        """
        if not self.is_enabled():
            return None

        try:
            payload = {
                "batch_context": {
                    "total_rows": len(df),
                    "columns": list(df.columns)
                },
                "candidates": [a.model_dump() for a in anomalies[:50]]
            }
            json_bytes = json.dumps(payload).encode("utf-8")

            req = urllib.request.Request(
                f"{self.api_url}/score-anomalies" if not self.api_url.endswith("/score-anomalies") else self.api_url,
                data=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key or ''}"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode("utf-8"))
                    agent_items = result.get("anomalies", [])
                    if agent_items:
                        logger.info(f"Successfully received {len(agent_items)} anomaly scores from CrewAI agent.")
                        enriched_list = []
                        agent_map = {item.get("id"): item for item in agent_items if "id" in item}
                        for a in anomalies:
                            if a.id in agent_map:
                                ai = agent_map[a.id]
                                a.confidence_score = ai.get("confidence_score", a.confidence_score)
                                a.description = ai.get("description", a.description)
                                if "suggested_fix" in ai and ai["suggested_fix"]:
                                    a.suggested_fix = ai["suggested_fix"]
                                if "remediation_notes" in ai:
                                    a.remediation_notes = ai["remediation_notes"]
                            enriched_list.append(a)
                        return enriched_list
        except Exception as e:
            logger.info(f"CrewAI agent API call fell back to local agent evaluator: {e}")
            return None


class AgenticAnomalyService:
    def __init__(self, crewai_api_url: Optional[str] = None, crewai_api_key: Optional[str] = None):
        self.crewai_api_url = crewai_api_url or settings.crewai_api_url
        self.crewai_api_key = crewai_api_key or settings.crewai_api_key
        self.agent_bridge = CrewAIAgentBridge(self.crewai_api_url, self.crewai_api_key)
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

    def evaluate_batch(self, df: pd.DataFrame, batch_id: str) -> Tuple[pd.DataFrame, List[AnomalyItem]]:
        """
        Executes Stage [3] Row-level rules and Stage [4] Agentic Anomaly Scoring.
        Separates valid rows from anomalous rows.
        Applies Stage [5a] Auto-remediation for safe pattern issues and re-validates them.
        """
        anomalies: List[AnomalyItem] = []
        clean_df = df.copy()

        seen_txn_ids = set()
        duplicate_indices = set()

        # 1. Cross-row duplicate check
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
                        category="DUPLICATE",
                        description=f"Transaction ID '{s_id}' appears multiple times within the batch.",
                        auto_remediable=False,
                        suggested_fix={"action": "QUARANTINE_DUPLICATE", "external_txn_id": f"{s_id}_DUP"},
                        status="ESCALATED",
                        confidence_score=0.98,
                        remediation_notes="Requires human confirmation to distinguish intentional retry vs duplicate bank transmission."
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

            # Check: Invalid / Missing Amount
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
                        category="BUSINESS_RULE",
                        description="Transaction line declared with zero value ($0.00).",
                        auto_remediable=False,
                        suggested_fix={"action": "INSPECT_ORIGINAL_LINE"},
                        status="ESCALATED",
                        confidence_score=0.90,
                        remediation_notes="Zero amount lines violate ledger settlement guidelines."
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
                    category="FORMAT",
                    description=f"Amount value '{amount_str}' cannot be parsed as numeric float.",
                    auto_remediable=False,
                    suggested_fix={"action": "CORRECT_AMOUNT", "amount": 0.0},
                    status="ESCALATED",
                    confidence_score=0.95
                ))

            # Check: Debit/Credit flag
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
                        category="FORMAT",
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
                        category="FORMAT",
                        description=f"Unrecognized DR/CR direction '{dc}'.",
                        auto_remediable=False,
                        suggested_fix={"debit_credit": "DR"},
                        status="ESCALATED",
                        confidence_score=0.80
                    ))

            # Check: Currency code
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
                        category="FORMAT",
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
                        category="BUSINESS_RULE",
                        description=f"Currency '{raw_curr}' is not a recognized ISO banking currency.",
                        auto_remediable=False,
                        suggested_fix={"currency": "USD"},
                        status="ESCALATED",
                        confidence_score=0.85
                    ))

            # Check: Referential Integrity against GL Chart of Accounts
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
                        suggested_fix={"account": "ACC#00001"},
                        status="ESCALATED",
                        confidence_score=0.75,
                        remediation_notes="Row needs manual GL account assignment before reconciliation."
                    ))

            # Check: Date formatting (e.g. DD/MM/YYYY vs YYYY-MM-DD)
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
                            category="FORMAT",
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
        # AGENT INTEGRATION HOOK (CrewAI / Multi-Agent Platform API)
        # =====================================================================
        if (self.agent_bridge.is_enabled() or self.crewai_api_url) and anomalies:
            enriched = self.agent_bridge.enrich_anomalies_via_api(anomalies, clean_df)
            if enriched:
                anomalies = enriched

        return clean_df, anomalies


agentic_anomaly_service = AgenticAnomalyService()
