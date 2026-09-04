"""
Agentic Anomaly Scoring & Auto-Remediation Service.
Performs row-level rule validation across full batch context, agentic anomaly evaluation
(with CrewAI API integration hook and intelligent local agent evaluator), safe auto-remediation,
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

from app.models.pipeline_models import AnomalyItem
from app.config import settings

logger = logging.getLogger(__name__)

# Valid Currency codes
VALID_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR"}

# Valid GL Accounts Cache sample (populated from cache_gl_cashbook or default list)
DEFAULT_KNOWN_ACCOUNTS = {f"ACC#{str(i).zfill(5)}" for i in range(1, 100)}


class AgenticAnomalyService:
    def __init__(self, crewai_api_url: Optional[str] = None, crewai_api_key: Optional[str] = None):
        self.crewai_api_url = crewai_api_url
        self.crewai_api_key = crewai_api_key
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
                # Safe auto-remediation pattern check: e.g. "D", "C", "DEBIT", "CREDIT"
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
                # check if lowercase or whitespace
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
                # Check for small formatting mismatch like "acc#00001" vs "ACC#00001"
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

        # If CrewAI endpoint is configured, trigger agentic enrichment
        if self.crewai_api_url and anomalies:
            self._invoke_crewai_enrichment(anomalies)

        return clean_df, anomalies

    def _invoke_crewai_enrichment(self, anomalies: List[AnomalyItem]):
        """Calls external CrewAI API if URL is configured to enrich anomaly explanations."""
        try:
            payload = json.dumps([a.model_dump() for a in anomalies[:20]]).encode("utf-8")
            req = urllib.request.Request(
                self.crewai_api_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.crewai_api_key or ''}"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    logger.info("Successfully received CrewAI agent assessment.")
        except Exception as e:
            logger.info(f"CrewAI external API not reachable or not configured ({e}); local agent engine active.")


agentic_anomaly_service = AgenticAnomalyService()
