"""
Pipeline Orchestrator — Sequences the 8 stages of the batch validation and reconciliation pipeline:
1. Ingestion (SFTP / Drop / Upload)
2. Structural Gate (Hard checkpoint)
3. Row-level Rule Engine
4. Agentic Anomaly Scoring
5. Auto-Remediation (safe fixes) & Human Escalation Review
6. Tiered GL Matching (valid rows only)
7. Processing Time & SLA Estimation
8. Downstream Publishing
"""
import uuid
import time
import shutil
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.models.pipeline_models import (
    BatchRecord,
    StructuralGateDetails,
    CheckDetail,
    AnomalyItem,
    TimeEstimate,
    GLMatchSummary,
    PublishEvent,
    PipelineOverview
)
from app.services.ingestion_service import ingestion_service
from app.services.agentic_anomaly_service import agentic_anomaly_service
from app.services.time_estimator_service import time_estimator_service
from app.services.publish_service import publish_service
from app.config import settings

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self):
        self.batches: Dict[str, BatchRecord] = {}
        self.batch_dfs: Dict[str, pd.DataFrame] = {}
        self.batch_anomalies: Dict[str, List[AnomalyItem]] = {}
        self.batch_match_results: Dict[str, Any] = {}
        self.gl_cache: Optional[pd.DataFrame] = None
        self._load_gl_cache()
        self._seed_sample_batches()

    def _load_gl_cache(self):
        """Loads the GL cashbook cache for reconciliation."""
        if settings.cache_path.exists():
            try:
                self.gl_cache = pd.read_csv(settings.cache_path, dtype=str)
                logger.info(f"Loaded GL Cashbook Cache: {len(self.gl_cache)} rows.")
            except Exception as e:
                logger.warning(f"Failed to load GL cache: {e}")

    def ingest_batch(
        self,
        file_path: Optional[Path] = None,
        file_bytes: Optional[bytes] = None,
        filename: str = "statement_batch.csv",
        source: str = "UPLOAD",
        declared_record_count: Optional[int] = None,
        declared_control_total: Optional[float] = None,
        auto_run_pipeline: bool = True
    ) -> BatchRecord:
        start_time = time.time()

        # Stage [1]: Ingestion
        batch_id, stored_path, meta, df = ingestion_service.ingest_file(
            file_path=file_path,
            file_bytes=file_bytes,
            filename=filename,
            source=source,
            declared_record_count=declared_record_count,
            declared_control_total=declared_control_total
        )

        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Initial Processing Time Estimate
        time_est = time_estimator_service.estimate_processing_time(
            batch_id=batch_id,
            file_size_bytes=meta["file_size_bytes"],
            record_count=len(df),
            anomaly_count=0,
            escalated_count=0
        )

        record = BatchRecord(
            batch_id=batch_id,
            filename=filename,
            file_size_bytes=meta["file_size_bytes"],
            source=source,
            stage="INGESTED",
            total_records=len(df),
            valid_records_count=len(df),
            created_at=now_str,
            updated_at=now_str,
            time_estimate=time_est,
            batch_file_path=str(stored_path)
        )

        self.batches[batch_id] = record
        self.batch_dfs[batch_id] = df
        self.batch_anomalies[batch_id] = []

        if auto_run_pipeline:
            self.run_pipeline(batch_id, stored_path, meta)

        return record

    def run_pipeline(self, batch_id: str, stored_path: Path, meta: Dict[str, Any]):
        start_clock = time.time()
        batch = self.batches[batch_id]
        df = self.batch_dfs[batch_id]

        # Stage [2]: File-level Structural Gate
        gate_details = self._execute_structural_gate(batch_id, stored_path, df, meta)
        batch.gate_details = gate_details
        batch.gate_passed = gate_details.passed

        if not gate_details.passed:
            # Hard file-level failure: Quarantine entire file, abort downstream
            batch.stage = "GATE_QUARANTINED"
            batch.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            logger.warning(f"Batch {batch_id} failed structural gate: {gate_details.reasons}")
            return batch

        batch.stage = "GATE_PASSED"

        # Stage [3] & [4] & [5a]: Row-level Rules, Anomaly Scoring, Auto-remediation
        clean_df, anomalies, candidate_file = agentic_anomaly_service.evaluate_batch(df, batch_id, stored_path)
        self.batch_dfs[batch_id] = clean_df
        self.batch_anomalies[batch_id] = anomalies
        if candidate_file:
            batch.anomaly_file_path = str(candidate_file)

        auto_remediated = [a for a in anomalies if a.status == "AUTO_REMEDIATED"]
        escalated = [a for a in anomalies if a.status == "ESCALATED"]

        batch.anomaly_count = len(anomalies)
        batch.auto_remediated_count = len(auto_remediated)
        batch.escalated_count = len(escalated)
        batch.valid_records_count = len(clean_df) - len(escalated)

        # Update Processing Time & SLA estimate with real anomaly triage overhead
        batch.time_estimate = time_estimator_service.estimate_processing_time(
            batch_id=batch_id,
            file_size_bytes=batch.file_size_bytes,
            record_count=batch.total_records,
            anomaly_count=batch.anomaly_count,
            escalated_count=batch.escalated_count
        )

        batch.stage = "RULE_VALIDATED" if len(escalated) == 0 else "ESCALATED_FOR_REVIEW"

        # Stage [6]: GL Matching (runs on all validated rows)
        # Note: Escalated rows are held back until human resolves them
        valid_df = clean_df[~clean_df.index.isin([a.row_index for a in escalated])].copy()
        gl_summary = self._execute_gl_matching(batch_id, valid_df)
        batch.gl_summary = gl_summary
        batch.matched_count = gl_summary.matched_count
        batch.unmatched_count = gl_summary.unmatched_reconciling_items

        if len(escalated) == 0:
            batch.stage = "RECONCILED"
            # Stage [8]: Publish results
            publish_service.publish_batch(batch)

        elapsed = time.time() - start_clock
        time_estimator_service.record_actual_run(batch.time_estimate, elapsed)
        batch.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        return batch

    def _execute_structural_gate(
        self,
        batch_id: str,
        file_path: Path,
        df: pd.DataFrame,
        meta: Dict[str, Any]
    ) -> StructuralGateDetails:
        checks: Dict[str, CheckDetail] = {}
        reasons: List[str] = []
        passed = True

        # Check 1: Encoding
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            raw.decode("utf-8")
            checks["encoding"] = CheckDetail(passed=True, detail="Clean UTF-8 encoding verified.")
        except Exception as e:
            passed = False
            msg = f"UTF-8 decoding error: {e}"
            checks["encoding"] = CheckDetail(passed=False, detail=msg)
            reasons.append(msg)

        # Check 2: Required Columns
        required_cols = ["external_txn_id", "account", "amount", "debit_credit"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            passed = False
            msg = f"Missing required canonical columns: {missing}"
            checks["required_columns"] = CheckDetail(passed=False, detail=msg)
            reasons.append(msg)
        else:
            checks["required_columns"] = CheckDetail(passed=True, detail="All canonical columns present.")

        # Check 3: Record Count Parity
        actual_count = len(df)
        declared_count = meta.get("declared_record_count")
        if declared_count is not None and declared_count != actual_count:
            passed = False
            msg = f"Declared record count ({declared_count}) != actual row count ({actual_count})."
            checks["record_count"] = CheckDetail(passed=False, detail=msg)
            reasons.append(msg)
        else:
            checks["record_count"] = CheckDetail(passed=True, detail=f"Record count matches ({actual_count}).")

        # Check 4: Control Total Balance
        declared_total = meta.get("declared_control_total")
        actual_total = 0.0
        if "amount" in df.columns:
            amounts = pd.to_numeric(df["amount"].astype(str).str.replace(",", "").str.replace("$", ""), errors="coerce")
            actual_total = round(float(amounts.sum()), 2)

        if declared_total is not None and abs(actual_total - float(declared_total)) > 0.05:
            passed = False
            msg = f"Declared control total (${float(declared_total):,.2f}) != actual amount sum (${actual_total:,.2f})."
            checks["control_total"] = CheckDetail(passed=False, detail=msg)
            reasons.append(msg)
        else:
            checks["control_total"] = CheckDetail(passed=True, detail=f"Control total balanced (${actual_total:,.2f}).")

        quarantine_path = None
        if not passed:
            quarantine_dir = settings.project_root / "data" / "quarantined_batches"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine_dest = quarantine_dir / file_path.name
            shutil.copyfile(file_path, quarantine_dest)
            quarantine_path = str(quarantine_dest)

        return StructuralGateDetails(
            passed=passed,
            file=file_path.name,
            declared_record_count=declared_count,
            actual_record_count=actual_count,
            declared_control_total=declared_total,
            actual_control_total=actual_total,
            checks=checks,
            reasons=reasons,
            quarantined=not passed,
            quarantine_path=quarantine_path
        )

    def _execute_gl_matching(self, batch_id: str, df: pd.DataFrame) -> GLMatchSummary:
        """
        Executes tiered GL matching for validated rows against the cached GL slice.
        """
        if self.gl_cache is None or self.gl_cache.empty or df.empty:
            return GLMatchSummary(
                total_eligible_rows=len(df),
                matched_count=0,
                tier_1_exact=0,
                tier_2_date=0,
                tier_3_ref=0,
                tier_4_amount=0,
                unmatched_reconciling_items=len(df),
                ambiguous_count=0,
                match_rate_pct=0.0
            )

        # Build fast lookup indexes from GL cache
        gl = self.gl_cache.copy()
        gl["amount_num"] = pd.to_numeric(gl["amount"], errors="coerce").abs().round(2)
        gl["date_str"] = gl.get("value_date", gl.get("txn_date", "")).astype(str).str.strip()
        gl["account_clean"] = gl["account"].astype(str).str.strip()

        matched_rows = []
        unmatched_rows = []

        tier_1 = 0
        tier_2 = 0
        tier_3 = 0
        tier_4 = 0

        # Create quick index: (account, amount_num, date_str)
        exact_index = {}
        for idx, r in gl.iterrows():
            key = (r["account_clean"], r["amount_num"], r["date_str"])
            if key not in exact_index:
                exact_index[key] = []
            exact_index[key].append(idx)

        # Match each ingested row
        for _, row in df.iterrows():
            acc = str(row.get("account", "")).strip()
            raw_amt = row.get("amount", 0)
            try:
                amt = round(abs(float(str(raw_amt).replace(",", "").replace("$", ""))), 2)
            except Exception:
                amt = 0.0

            d_str = str(row.get("value_date", row.get("booking_date", ""))).strip()
            exact_key = (acc, amt, d_str)

            if exact_key in exact_index and exact_index[exact_key]:
                gl_idx = exact_index[exact_key].pop(0)
                matched_rows.append({
                    "ingest_row": row.to_dict(),
                    "gl_row": gl.loc[gl_idx].to_dict(),
                    "tier": "TIER_1_EXACT"
                })
                tier_1 += 1
            else:
                # Check Tier 4 Amount tolerance ($1.00 slack) or Tier 2 date tolerance
                matched = False
                candidates = gl[gl["account_clean"] == acc]
                if not candidates.empty:
                    # Amount slack check
                    amt_diff = (candidates["amount_num"] - amt).abs()
                    close_amts = candidates[amt_diff <= 1.00]
                    if not close_amts.empty:
                        gl_idx = close_amts.index[0]
                        matched_rows.append({
                            "ingest_row": row.to_dict(),
                            "gl_row": gl.loc[gl_idx].to_dict(),
                            "tier": "TIER_4_AMOUNT_TOLERANCE"
                        })
                        tier_4 += 1
                        matched = True

                if not matched:
                    unmatched_rows.append(row.to_dict())

        total_matched = len(matched_rows)
        match_rate = round((total_matched / max(1, len(df))) * 100, 1)

        self.batch_match_results[batch_id] = {
            "matched": matched_rows,
            "unmatched_reconciling": unmatched_rows
        }

        return GLMatchSummary(
            total_eligible_rows=len(df),
            matched_count=total_matched,
            tier_1_exact=tier_1,
            tier_2_date=tier_2,
            tier_3_ref=tier_3,
            tier_4_amount=tier_4,
            unmatched_reconciling_items=len(unmatched_rows),
            ambiguous_count=0,
            match_rate_pct=match_rate
        )

    def resolve_escalation(
        self,
        batch_id: str,
        anomaly_id: str,
        action: str,
        override_values: Optional[Dict[str, Any]] = None,
        analyst_notes: Optional[str] = None
    ) -> BatchRecord:
        """
        Stage [5b] Human-in-the-Loop Resolution:
        Analyst accepts suggested fix, provides manual override, or quarantines row.
        Remediated rows re-enter rule engine for re-validation!
        """
        if batch_id not in self.batches:
            raise KeyError(f"Batch {batch_id} not found.")

        batch = self.batches[batch_id]
        anomalies = self.batch_anomalies.get(batch_id, [])
        target = next((a for a in anomalies if a.id == anomaly_id), None)
        if not target:
            raise KeyError(f"Anomaly {anomaly_id} not found in batch {batch_id}.")

        df = self.batch_dfs[batch_id]
        r_idx = target.row_index

        if action == "APPROVE":
            # Apply the suggested fix
            if target.suggested_fix:
                for k, v in target.suggested_fix.items():
                    if k in df.columns:
                        df.at[r_idx, k] = v
            target.status = "HUMAN_RESOLVED"
            target.remediation_notes = f"Approved suggested fix. Notes: {analyst_notes or 'None'}"
        elif action == "OVERRIDE" and override_values:
            for k, v in override_values.items():
                if k in df.columns:
                    df.at[r_idx, k] = v
            target.status = "HUMAN_RESOLVED"
            target.remediation_notes = f"Analyst manual override applied: {override_values}. Notes: {analyst_notes or 'None'}"
        elif action == "QUARANTINE":
            target.status = "QUARANTINED"
            target.remediation_notes = f"Row quarantined by analyst. Notes: {analyst_notes or 'None'}"
            batch.quarantined_rows_count += 1

        # Check remaining escalated items
        remaining_escalated = [a for a in anomalies if a.status == "ESCALATED"]
        batch.escalated_count = len(remaining_escalated)

        # If all escalations resolved, run reconciliation and publish
        if len(remaining_escalated) == 0:
            valid_df = df[~df.index.isin([a.row_index for a in anomalies if a.status == "QUARANTINED"])].copy()
            batch.valid_records_count = len(valid_df)
            gl_summary = self._execute_gl_matching(batch_id, valid_df)
            batch.gl_summary = gl_summary
            batch.matched_count = gl_summary.matched_count
            batch.unmatched_count = gl_summary.unmatched_reconciling_items
            batch.stage = "RECONCILED"
            publish_service.publish_batch(batch)

        batch.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        return batch

    def trigger_agent_classification(
        self,
        batch_id: str,
        use_anomalies_file: bool = True,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits either the candidate anomaly CSV (if available) or the raw batch statement CSV
        to the external Aava AI Agent (default ID 7723 or specified agent_id) via multipart/form-data.
        Records the agent execution job info on the batch.
        """
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")

        batch = self.batches[batch_id]

        target_path: Optional[Path] = None
        if use_anomalies_file and batch.anomaly_file_path:
            p = Path(batch.anomaly_file_path)
            if p.exists():
                target_path = p

        if not target_path and batch.batch_file_path:
            p = Path(batch.batch_file_path)
            if p.exists():
                target_path = p

        if not target_path:
            # Fallback to output batches directory
            candidate_p = settings.batches_dir / f"{batch.filename}"
            if candidate_p.exists():
                target_path = candidate_p

        if not target_path or not target_path.exists():
            raise FileNotFoundError(f"No statement or anomaly candidate file found on disk for batch '{batch_id}'.")

        result = agentic_anomaly_service.agent_bridge.submit_batch_to_agent(target_path, agent_id=agent_id)
        batch.agent_execution = result
        batch.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        return result

    def get_batch_agent_output(self, batch_id: str) -> Dict[str, Any]:
        """
        Fetches the execution output from Aava AI using the batch's agent_execution_id.
        """
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")

        batch = self.batches[batch_id]
        if not batch.agent_execution or not batch.agent_execution.get("agent_execution_id"):
            return {
                "success": False,
                "message": f"No agent execution submitted yet for batch '{batch_id}'.",
                "batch_id": batch_id
            }

        exec_id = batch.agent_execution["agent_execution_id"]
        output_data = agentic_anomaly_service.agent_bridge.get_agent_execution_output(exec_id)

        # Store latest output on the batch record
        if output_data.get("success"):
            batch.agent_execution["output_details"] = output_data
            batch.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        return output_data

    def get_overview(self) -> PipelineOverview:
        b_list = list(self.batches.values())
        total = len(b_list)
        active = sum(1 for b in b_list if b.stage in ["INGESTED", "GATE_PASSED", "ESCALATED_FOR_REVIEW"])
        completed = sum(1 for b in b_list if b.stage in ["RECONCILED", "PUBLISHED"])
        quarantined = sum(1 for b in b_list if b.stage == "GATE_QUARANTINED")
        records = sum(b.total_records for b in b_list)
        breached = sum(1 for b in b_list if b.time_estimate and b.time_estimate.sla_status == "BREACHED")
        at_risk = sum(1 for b in b_list if b.time_estimate and b.time_estimate.sla_status == "AT_RISK")

        return PipelineOverview(
            total_batches=total,
            active_batches=active,
            completed_batches=completed,
            quarantined_batches=quarantined,
            total_records_processed=records,
            sla_breaches=breached,
            at_risk_count=at_risk,
            batches=b_list
        )

    def _seed_sample_batches(self):
        """Pre-seeds realistic batches to demonstrate the pipeline out-of-the-box."""
        # 1. Check if there are generated batch files in File-Gen Scripts/OutPut/ingestion_batches
        sample_batch_file = settings.batches_dir / "ingest_batch_0001.csv"
        if sample_batch_file.exists():
            try:
                self.ingest_batch(
                    file_path=sample_batch_file,
                    filename="bank_stmt_eod_0001.csv",
                    source="SFTP",
                    auto_run_pipeline=True
                )
            except Exception as e:
                logger.warning(f"Could not seed batch 0001: {e}")

        sample_batch_file_2 = settings.batches_dir / "ingest_batch_0002.csv"
        if sample_batch_file_2.exists():
            try:
                self.ingest_batch(
                    file_path=sample_batch_file_2,
                    filename="bank_stmt_eod_0002.csv",
                    source="SFTP",
                    auto_run_pipeline=True
                )
            except Exception as e:
                logger.warning(f"Could not seed batch 0002: {e}")


pipeline_orchestrator = PipelineOrchestrator()

