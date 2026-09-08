"""
Pipeline Orchestrator — Sequences the 8 stages of the batch validation and reconciliation pipeline:
1. Ingestion (SFTP drop polling / upload)
2. Structural Gate (hard file-level checkpoint)
3. Row-level Rule Engine
4. Agentic Anomaly Scoring  -> auto-dispatches Agent CREWAI_AGENT_ANOMALY_ID
5. Auto-Remediation (safe fixes, re-validated through Stage 3) & Human Escalation
6. Tiered GL Matching       -> auto-dispatches Agent CREWAI_AGENT_RECON_ID
7. Processing Time & SLA Estimation -> auto-dispatches Agent CREWAI_AGENT_SLA_ID
8. Downstream Publishing

Every stage runs automatically as soon as its predecessor produces its artefacts.
The only stage that blocks on a human is Stage 5b (analyst escalation review).
"""
import sys
import time
import shutil
import logging
import threading
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.models.pipeline_models import (
    BatchRecord,
    StructuralGateDetails,
    CheckDetail,
    AnomalyItem,
    AgentExecution,
    GLMatchSummary,
    PipelineOverview,
)
from app.services.ingestion_service import ingestion_service
from app.services.agentic_anomaly_service import agentic_anomaly_service
from app.services.time_estimator_service import time_estimator_service
from app.services.publish_service import publish_service
from app.config import settings

logger = logging.getLogger(__name__)

RULE_ENGINE_DIR = str(settings.project_root / "Rule Engine")
if RULE_ENGINE_DIR not in sys.path:
    sys.path.insert(0, RULE_ENGINE_DIR)

import rule_engine  # noqa: E402  (path-injected sibling module)

# Aava execution states that mean the job is finished and no longer worth polling.
TERMINAL_AGENT_STATES = {"SUCCESS", "COMPLETED", "FAILED", "ERROR", "CANCELLED"}


class PipelineOrchestrator:
    def __init__(self):
        self.batches: Dict[str, BatchRecord] = {}
        self.batch_dfs: Dict[str, pd.DataFrame] = {}
        self.batch_anomalies: Dict[str, List[AnomalyItem]] = {}
        self.batch_match_results: Dict[str, Any] = {}
        self.gl_cache: Optional[pd.DataFrame] = None
        self._recon_engine = None
        self._reconciled_batches: set = set()
        self._ingested_sources: set = set()   # resolved paths already turned into a batch
        self._lock = threading.Lock()
        self._load_gl_cache()
        self._poll_sftp_dropbox()

    # =========================================================================
    # Bootstrap
    # =========================================================================
    def _load_gl_cache(self):
        """Loads the GL cashbook cache used by Stage 6 reconciliation."""
        if not settings.cache_path.exists():
            logger.warning(f"GL cashbook cache not found at {settings.cache_path}; Stage 6 will report zero matches.")
            return
        try:
            self.gl_cache = pd.read_csv(settings.cache_path, dtype=str, keep_default_na=False)
            self._recon_engine = rule_engine.RuleEngine(self.gl_cache, rule_engine.MatchConfig())
            logger.info(f"Loaded GL Cashbook Cache: {len(self.gl_cache)} rows.")
        except Exception as e:
            logger.warning(f"Failed to load GL cache: {e}")

    def _poll_sftp_dropbox(self):
        """
        Stage 1 automated directory polling: ingests every statement waiting in
        incoming_sftp/ at startup.

        An empty dropbox means an empty console. Nothing is ever seeded — a batch
        exists only because a real file arrived, so what the operator sees is
        always something that actually happened.
        """
        if not settings.sftp_auto_ingest:
            return

        pending = sorted(settings.sftp_dir.glob("*.csv"))
        if not pending:
            logger.info("SFTP dropbox is empty; no batches ingested at startup.")
            return

        for f in pending:
            try:
                self.ingest_batch(file_path=f, filename=f.name, source="SFTP", auto_run_pipeline=True)
                self._archive_sftp_file(f)
            except Exception as e:
                logger.warning(f"SFTP auto-ingest failed for {f.name}: {e}")

    def _archive_sftp_file(self, f: Path):
        """
        Moves a picked-up statement into incoming_sftp/processed/.

        A pickup directory that is never drained would re-ingest the same file on
        every restart, producing duplicate batches of one statement. The original
        is moved rather than deleted so it stays recoverable, and the ingested copy
        already lives under data/ingestion_storage/ regardless.
        """
        try:
            processed_dir = settings.sftp_dir / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            destination = processed_dir / f.name
            if destination.exists():
                stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                destination = processed_dir / f"{f.stem}_{stamp}{f.suffix}"
            shutil.move(str(f), str(destination))
        except Exception as e:
            logger.warning(f"Could not archive {f.name} out of the SFTP dropbox: {e}")

    def pull_next_sftp_drop(self, filename: Optional[str] = None):
        """
        Ingests one waiting statement on demand, for an operator who does not want
        to wait for the next restart poll.

        Prefers a real file in the dropbox. Only if the dropbox is empty does it
        fall back to the generated sample feed, and that batch is tagged
        SAMPLE_FEED rather than SFTP so the console never presents generated data
        as a genuine bank arrival.

        Returns (batch, origin) where origin is "SFTP" or "SAMPLE_FEED".
        """
        if filename:
            for candidate in (settings.sftp_dir / filename, settings.batches_dir / filename):
                if candidate.exists():
                    origin = "SFTP" if candidate.parent == settings.sftp_dir else "SAMPLE_FEED"
                    batch = self.ingest_batch(
                        file_path=candidate, filename=candidate.name, source=origin, auto_run_pipeline=True
                    )
                    if origin == "SFTP":
                        self._archive_sftp_file(candidate)
                    return batch, origin
            raise FileNotFoundError(
                f"'{filename}' is not in the SFTP dropbox or the generated sample feed."
            )

        waiting = sorted(settings.sftp_dir.glob("*.csv"))
        if waiting:
            target = waiting[0]
            batch = self.ingest_batch(
                file_path=target, filename=target.name, source="SFTP", auto_run_pipeline=True
            )
            self._archive_sftp_file(target)
            return batch, "SFTP"

        # Dropbox empty — offer the next generated sample not already ingested,
        # so repeated clicks walk the feed instead of re-ingesting one file.
        for sample in sorted(settings.batches_dir.glob("ingest_batch_*.csv")):
            if str(sample.resolve()) in self._ingested_sources:
                continue
            batch = self.ingest_batch(
                file_path=sample, filename=sample.name, source="SAMPLE_FEED", auto_run_pipeline=True
            )
            return batch, "SAMPLE_FEED"

        raise FileNotFoundError(
            "No statement waiting in incoming_sftp/, and every generated sample batch "
            "has already been ingested. Drop a file into incoming_sftp/ or upload one."
        )

    # =========================================================================
    # Stage 1 — Ingestion
    # =========================================================================
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
        batch_id, stored_path, meta, df = ingestion_service.ingest_file(
            file_path=file_path,
            file_bytes=file_bytes,
            filename=filename,
            source=source,
            declared_record_count=declared_record_count,
            declared_control_total=declared_control_total
        )

        now_str = self._now()

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
        if file_path is not None:
            self._ingested_sources.add(str(Path(file_path).resolve()))

        if auto_run_pipeline:
            self.run_pipeline(batch_id, stored_path, meta)

        return record

    # =========================================================================
    # Stages 2 -> 8
    # =========================================================================
    def run_pipeline(self, batch_id: str, stored_path: Path, meta: Dict[str, Any]):
        start_clock = time.time()
        batch = self.batches[batch_id]
        df = self.batch_dfs[batch_id]

        # ---- Stage 2: File-level Structural Gate ----------------------------
        gate_details = self._execute_structural_gate(batch_id, stored_path, df, meta)
        batch.gate_details = gate_details
        batch.gate_passed = gate_details.passed

        if not gate_details.passed:
            batch.stage = "GATE_QUARANTINED"
            batch.updated_at = self._now()
            logger.warning(f"Batch {batch_id} failed structural gate: {gate_details.reasons}")
            return batch

        batch.stage = "GATE_PASSED"

        # ---- Stages 3, 4, 5a: rules, anomaly scoring, auto-remediation ------
        clean_df, anomalies, candidate_file = agentic_anomaly_service.evaluate_batch(df, batch_id, stored_path)

        # Stage 5a re-validation loop: rerun Stage 3 over the remediated frame so
        # an auto-fix that itself violates a rule is caught rather than trusted.
        if any(a.status == "AUTO_REMEDIATED" for a in anomalies):
            clean_df, anomalies, candidate_file = self._revalidate_after_remediation(
                clean_df, anomalies, batch_id, stored_path
            )

        self.batch_dfs[batch_id] = clean_df
        self.batch_anomalies[batch_id] = anomalies
        if candidate_file:
            batch.anomaly_file_path = str(candidate_file)

        escalated = [a for a in anomalies if a.status == "ESCALATED"]

        batch.anomaly_count = len(anomalies)
        batch.auto_remediated_count = sum(1 for a in anomalies if a.status == "AUTO_REMEDIATED")
        batch.escalated_count = len(escalated)
        batch.valid_records_count = len(clean_df) - len(escalated)

        # Stage 4 agent dispatch — fires as soon as the candidate file exists.
        self._dispatch_agent_async(batch, "STAGE_4_ANOMALY", batch.anomaly_file_path)

        batch.time_estimate = time_estimator_service.estimate_processing_time(
            batch_id=batch_id,
            file_size_bytes=batch.file_size_bytes,
            record_count=batch.total_records,
            anomaly_count=batch.anomaly_count,
            escalated_count=batch.escalated_count
        )

        if escalated:
            # ARCHITECTURE.md Stage 5b: the batch holds at the analyst queue.
            # Stage 6 only runs once every escalation is signed off, so an
            # approved correction is matched against the GL rather than skipped.
            batch.stage = "ESCALATED_FOR_REVIEW"
            self._finalize_sla(batch, start_clock)
            batch.updated_at = self._now()
            return batch

        batch.stage = "RULE_VALIDATED"
        self._reconcile_and_finalize(batch, clean_df, start_clock)
        return batch

    def _revalidate_after_remediation(
        self,
        clean_df: pd.DataFrame,
        first_pass: List[AnomalyItem],
        batch_id: str,
        stored_path: Path,
    ):
        """
        ARCHITECTURE.md Stage 5a: "Remediated rows re-enter Stage 3 for
        re-validation before proceeding." Re-runs the rule engine on the
        corrected frame and keeps the first-pass remediation entries as the
        audit trail alongside whatever the second pass still objects to.
        """
        revalidated_df, second_pass, candidate_file = agentic_anomaly_service.evaluate_batch(
            clean_df, batch_id, stored_path
        )

        remediation_log = [a for a in first_pass if a.status == "AUTO_REMEDIATED"]
        for item in remediation_log:
            item.remediation_notes = (
                f"{item.remediation_notes or ''} Re-validated through Stage 3 rule engine."
            ).strip()

        merged = remediation_log + [a for a in second_pass if a.status != "AUTO_REMEDIATED"]
        return revalidated_df, merged, candidate_file

    def _reconcile_and_finalize(
        self,
        batch: BatchRecord,
        valid_df: pd.DataFrame,
        start_clock: float,
    ):
        """Stages 6 -> 8, plus the Stage 6 agent dispatch."""
        if batch.batch_id in self._reconciled_batches:
            # The GL cache is consumed as it is matched, so replaying a batch
            # would settle the same ledger rows twice.
            logger.info(f"Batch {batch.batch_id} already reconciled; skipping Stage 6 replay.")
            return

        gl_summary = self._execute_gl_matching(batch, valid_df)
        self._reconciled_batches.add(batch.batch_id)
        batch.gl_summary = gl_summary
        batch.matched_count = gl_summary.matched_count
        batch.unmatched_count = gl_summary.unmatched_reconciling_items

        # ---- Stage 7: SLA estimate + metrics artefact -----------------------
        self._finalize_sla(batch, start_clock, gl_summary)

        # ---- Stage 6 agent dispatch -----------------------------------------
        self._dispatch_agent_async(batch, "STAGE_6_RECON", batch.ambiguous_file_path or batch.unmatched_file_path)

        # ---- Stage 8: Publish ------------------------------------------------
        batch.stage = "RECONCILED"
        publish_service.publish_batch(batch)
        batch.updated_at = self._now()

    def _finalize_sla(
        self,
        batch: BatchRecord,
        start_clock: float,
        gl_summary: Optional[GLMatchSummary] = None,
    ):
        """Stage 7: records the actual run, exports the SLA feature vector, dispatches the SLA agent."""
        if not batch.time_estimate:
            return

        time_estimator_service.record_actual_run(batch.time_estimate, time.time() - start_clock)
        try:
            sla_path = time_estimator_service.export_sla_metrics(
                estimate=batch.time_estimate,
                escalated_count=batch.escalated_count,
                matched_count=gl_summary.matched_count if gl_summary else 0,
                unmatched_count=gl_summary.unmatched_reconciling_items if gl_summary else 0,
                ambiguous_count=gl_summary.ambiguous_count if gl_summary else 0,
            )
            batch.sla_metrics_file_path = str(sla_path)
        except Exception as e:
            logger.error(f"Failed to export SLA metrics for {batch.batch_id}: {e}")
            return

        self._dispatch_agent_async(batch, "STAGE_7_SLA", batch.sla_metrics_file_path)

    # =========================================================================
    # Stage 2 implementation
    # =========================================================================
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
            settings.quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine_dest = settings.quarantine_dir / file_path.name
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

    # =========================================================================
    # Stage 6 implementation — full 4-tier waterfall
    # =========================================================================
    def _execute_gl_matching(self, batch: BatchRecord, df: pd.DataFrame) -> GLMatchSummary:
        """
        Runs the shared 4-tier waterfall rule engine (Tier 1 exact -> Tier 2 date
        tolerance -> Tier 3 reference overlap -> Tier 4 amount slack) for this
        batch against the GL cashbook cache, then exports the Stage 6 artefacts
        that the reconciliation exception agent consumes.
        """
        batch_id = batch.batch_id

        if self._recon_engine is None or df.empty:
            self.batch_match_results[batch_id] = {"matched": [], "unmatched_reconciling": [], "ambiguous": []}
            return GLMatchSummary(
                total_eligible_rows=len(df),
                matched_count=0,
                tier_1_exact=0,
                tier_2_date=0,
                tier_3_ref=0,
                tier_4_amount=0,
                unmatched_reconciling_items=len(df),
                outstanding_gl_items=len(self._recon_engine.cache) if self._recon_engine else 0,
                ambiguous_count=0,
                match_rate_pct=0.0
            )

        # One engine across all batches: GL rows already settled by an earlier
        # batch are removed from the cache, exactly as the standalone runner does.
        engine = self._recon_engine
        before_matches = len(engine.matches)
        before_unmatched = len(engine.unmatched_ingest)
        before_ambiguous = len(engine.ambiguous)

        engine.process_batch(df, batch.filename)

        batch_matches = engine.matches[before_matches:]
        batch_unmatched = engine.unmatched_ingest[before_unmatched:]
        batch_ambiguous = engine.ambiguous[before_ambiguous:]

        drop_cols = ("amount_abs", "date_parsed")
        matches_df = pd.DataFrame(batch_matches)
        unmatched_df = pd.DataFrame(
            [{k: v for k, v in r.items() if k not in drop_cols} for r in batch_unmatched]
        )
        ambiguous_df = pd.DataFrame(batch_ambiguous)
        outstanding_df = engine.remaining_cache_df()

        tier_counts: Dict[str, int] = {}
        if not matches_df.empty and "matchRule" in matches_df.columns:
            tier_counts = {str(k): int(v) for k, v in matches_df["matchRule"].value_counts().items()}

        matched_records = matches_df.to_dict(orient="records") if not matches_df.empty else []
        unmatched_records = unmatched_df.to_dict(orient="records") if not unmatched_df.empty else []
        ambiguous_records = ambiguous_df.to_dict(orient="records") if not ambiguous_df.empty else []

        self.batch_match_results[batch_id] = {
            "matched": matched_records,
            "unmatched_reconciling": unmatched_records,
            "ambiguous": ambiguous_records,
        }

        self._export_recon_artifacts(batch, matches_df, unmatched_df, outstanding_df, ambiguous_df)

        total_matched = len(matched_records)
        return GLMatchSummary(
            total_eligible_rows=len(df),
            matched_count=total_matched,
            tier_1_exact=tier_counts.get("TIER_1_EXACT", 0),
            tier_2_date=tier_counts.get("TIER_2_DATE_TOLERANCE", 0),
            tier_3_ref=tier_counts.get("TIER_3_REFERENCE_MATCH", 0),
            tier_4_amount=tier_counts.get("TIER_4_AMOUNT_TOLERANCE", 0),
            unmatched_reconciling_items=len(unmatched_records),
            outstanding_gl_items=len(outstanding_df),
            ambiguous_count=len(ambiguous_records),
            match_rate_pct=round((total_matched / max(1, len(df))) * 100, 1)
        )

    def _export_recon_artifacts(
        self,
        batch: BatchRecord,
        matches_df: pd.DataFrame,
        unmatched_df: pd.DataFrame,
        outstanding_df: pd.DataFrame,
        ambiguous_df: pd.DataFrame,
    ):
        """
        Writes the per-batch Stage 6 CSVs. `{batch_id}_recon_exceptions.csv` is
        the input artefact for the reconciliation exception agent — it carries
        every line the waterfall could not settle outright.
        """
        out_dir = settings.batch_results_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        bid = batch.batch_id

        try:
            matched_path = out_dir / f"{bid}_matched.csv"
            matches_df.to_csv(matched_path, index=False)
            batch.matched_file_path = str(matched_path)

            unmatched_path = out_dir / f"{bid}_unmatched_bank.csv"
            unmatched_df.to_csv(unmatched_path, index=False)
            batch.unmatched_file_path = str(unmatched_path)

            outstanding_path = out_dir / f"{bid}_outstanding_gl.csv"
            outstanding_df.to_csv(outstanding_path, index=False)
            batch.outstanding_file_path = str(outstanding_path)

            ambiguous_path = out_dir / f"{bid}_ambiguous.csv"
            ambiguous_df.to_csv(ambiguous_path, index=False)

            # Combined exception feed for the Stage 6 agent.
            frames = []
            if not ambiguous_df.empty:
                amb = ambiguous_df.copy()
                amb["exception_type"] = "AMBIGUOUS_TIE"
                frames.append(amb)
            if not unmatched_df.empty:
                unm = unmatched_df.copy()
                unm["exception_type"] = "RECONCILING_ITEM_BANK_ONLY"
                frames.append(unm)

            exceptions_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
                columns=["exception_type"]
            )
            exceptions_path = out_dir / f"{bid}_recon_exceptions.csv"
            exceptions_df.to_csv(exceptions_path, index=False)
            batch.ambiguous_file_path = str(exceptions_path)
        except Exception as e:
            logger.error(f"Failed to export Stage 6 artefacts for {bid}: {e}")

    # =========================================================================
    # Stage 5b — Human-in-the-loop resolution
    # =========================================================================
    def resolve_escalation(
        self,
        batch_id: str,
        anomaly_id: str,
        action: str,
        override_values: Optional[Dict[str, Any]] = None,
        analyst_notes: Optional[str] = None
    ) -> BatchRecord:
        """
        Analyst accepts the suggested fix, supplies a manual override, or
        quarantines the row. Once the last escalation clears, Stages 6-8 run
        automatically without any further operator action.
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
            # Only anomalies with a correction derivable from the row itself carry a
            # suggested_fix. Approving anything else would write a fabricated value
            # into the ledger under an analyst's name.
            if not target.suggested_fix:
                raise ValueError(
                    f"Anomaly {anomaly_id} ({target.error_type}) has no correction that can be derived "
                    f"from the row, so there is nothing to approve. Supply the correct value with "
                    f"OVERRIDE (fields: {target.override_fields or 'see remediation notes'}), "
                    f"or QUARANTINE the row."
                )

            applied = {k: v for k, v in target.suggested_fix.items() if k in df.columns}
            if not applied:
                raise ValueError(
                    f"Anomaly {anomaly_id} suggests {target.suggested_fix}, but none of those fields "
                    f"exist in this batch. Use OVERRIDE or QUARANTINE."
                )
            for k, v in applied.items():
                df.at[r_idx, k] = v
            target.status = "HUMAN_RESOLVED"
            target.remediation_notes = f"Approved derived fix {applied}. Notes: {analyst_notes or 'None'}"

        elif action == "OVERRIDE":
            if not override_values:
                raise ValueError(
                    f"OVERRIDE requires override_values. Expected field(s): "
                    f"{target.override_fields or 'see remediation notes'}."
                )

            unknown = [k for k in override_values if k not in df.columns]
            if unknown:
                raise ValueError(
                    f"Cannot override {unknown}: not a column in this batch. "
                    f"Columns available: {sorted(df.columns)}"
                )

            blank = [k for k, v in override_values.items() if v is None or str(v).strip() == ""]
            if blank:
                raise ValueError(f"Override values for {blank} are blank. Supply a value or quarantine the row.")

            for k, v in override_values.items():
                df.at[r_idx, k] = v
            target.status = "HUMAN_RESOLVED"
            target.remediation_notes = f"Analyst manual override applied: {override_values}. Notes: {analyst_notes or 'None'}"

        elif action == "QUARANTINE":
            target.status = "QUARANTINED"
            target.remediation_notes = f"Row quarantined by analyst. Notes: {analyst_notes or 'None'}"
            batch.quarantined_rows_count += 1

        else:
            raise ValueError(
                f"Unknown action '{action}'. Expected APPROVE, OVERRIDE or QUARANTINE."
            )

        remaining_escalated = [a for a in anomalies if a.status == "ESCALATED"]
        batch.escalated_count = len(remaining_escalated)

        if not remaining_escalated:
            valid_df = df[~df.index.isin([a.row_index for a in anomalies if a.status == "QUARANTINED"])].copy()
            batch.valid_records_count = len(valid_df)
            self._reconcile_and_finalize(batch, valid_df, time.time())

        batch.updated_at = self._now()
        return batch

    # =========================================================================
    # Automatic multi-agent dispatch
    # =========================================================================
    def _dispatch_agent_async(self, batch: BatchRecord, stage_key: str, artifact_path: Optional[str]):
        """
        Fires the agent registered for `stage_key` against `artifact_path` on a
        background thread so the synchronous pipeline never blocks on the
        external platform. Records the outcome on batch.agent_executions.
        """
        agent = agentic_anomaly_service.agent_bridge.get_agent_for_stage(stage_key)
        if not agent:
            return

        execution = AgentExecution(
            stage=stage_key,
            agent_id=agent["id"],
            agent_name=agent["name"],
            trigger="AUTOMATIC",
        )
        batch.agent_executions[stage_key] = execution

        if not agent.get("configured"):
            execution.status = "SKIPPED"
            execution.message = (
                f"No agent ID configured for this stage. Set {agent['key']} in .env "
                "to the ID issued by the agent platform."
            )
            return

        if not settings.auto_agent_dispatch or not agent.get("auto_dispatch"):
            execution.status = "SKIPPED"
            execution.message = "Automatic dispatch disabled for this agent."
            return

        if not artifact_path or not Path(artifact_path).exists():
            execution.status = "SKIPPED"
            execution.message = f"No input artefact produced for {stage_key}; nothing to classify."
            return

        if not agentic_anomaly_service.agent_bridge.is_enabled():
            execution.status = "SKIPPED"
            execution.message = "External agent platform not configured (set CREWAI_API_URL / CREWAI_API_KEY)."
            return

        execution.status = "SUBMITTING"
        execution.target_file = Path(artifact_path).name

        threading.Thread(
            target=self._submit_agent_job,
            args=(batch.batch_id, stage_key, Path(artifact_path), agent["id"]),
            daemon=True,
            name=f"agent-{stage_key}-{batch.batch_id}",
        ).start()

    def _submit_agent_job(self, batch_id: str, stage_key: str, artifact: Path, agent_id: str):
        result = agentic_anomaly_service.agent_bridge.submit_batch_to_agent(artifact, agent_id=agent_id)

        with self._lock:
            batch = self.batches.get(batch_id)
            if not batch:
                return
            execution = batch.agent_executions.get(stage_key)
            if not execution:
                return

            execution.success = bool(result.get("success"))
            execution.job_id = result.get("job_id")
            execution.agent_execution_id = result.get("agent_execution_id")
            execution.message = result.get("message")
            execution.http_status = str(result.get("http_status"))
            execution.submitted_at = result.get("submitted_at")
            execution.status = "SUBMITTED" if execution.success else "FAILED"
            batch.agent_execution = execution.model_dump()
            batch.updated_at = self._now()

    def refresh_agent_outputs(self, batch_id: str) -> Dict[str, AgentExecution]:
        """
        Pulls the latest execution output for every non-terminal agent job on
        this batch. Called by the console's polling endpoint — the operator
        never has to press anything to make an agent run.
        """
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")

        batch = self.batches[batch_id]
        bridge = agentic_anomaly_service.agent_bridge

        for execution in batch.agent_executions.values():
            if not execution.agent_execution_id:
                continue
            if execution.status in TERMINAL_AGENT_STATES:
                continue

            data = bridge.get_agent_execution_output(execution.agent_execution_id)
            if not data.get("success"):
                execution.message = data.get("message") or execution.message
                continue

            execution.output = data.get("output")
            execution.status = (data.get("status") or "IN_PROGRESS").upper()
            if execution.status in TERMINAL_AGENT_STATES:
                execution.completed_at = data.get("modifiedAt") or self._now()

        batch.updated_at = self._now()
        return batch.agent_executions

    def trigger_agent_classification(
        self,
        batch_id: str,
        stage_key: str = "STAGE_4_ANOMALY",
        agent_id: Optional[str] = None
    ) -> AgentExecution:
        """
        Manual re-dispatch of a stage's agent. The pipeline already fires these
        automatically; this exists for re-running a failed submission.
        """
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")

        batch = self.batches[batch_id]
        artifact = self._artifact_for_stage(batch, stage_key)
        if not artifact:
            raise FileNotFoundError(
                f"No input artefact available on disk for stage '{stage_key}' of batch '{batch_id}'."
            )

        agent = agentic_anomaly_service.agent_bridge.get_agent_for_stage(stage_key)
        if not agent:
            raise KeyError(f"No agent configured for stage '{stage_key}'.")

        resolved_agent_id = agent_id or agent["id"]
        if not resolved_agent_id:
            raise ValueError(
                f"No agent ID configured for stage '{stage_key}'. Set {agent['key']} in .env, "
                "or pass agent_id explicitly."
            )
        resolved_agent_id = str(resolved_agent_id)
        execution = AgentExecution(
            stage=stage_key,
            agent_id=resolved_agent_id,
            agent_name=agent["name"],
            trigger="MANUAL",
            status="SUBMITTING",
            target_file=artifact.name,
        )
        batch.agent_executions[stage_key] = execution

        self._submit_agent_job(batch_id, stage_key, artifact, resolved_agent_id)
        return batch.agent_executions[stage_key]

    def _artifact_for_stage(self, batch: BatchRecord, stage_key: str) -> Optional[Path]:
        mapping = {
            "STAGE_1_EXTRACTION": batch.batch_file_path,
            "STAGE_4_ANOMALY": batch.anomaly_file_path or batch.batch_file_path,
            "STAGE_6_RECON": batch.ambiguous_file_path or batch.unmatched_file_path,
            "STAGE_7_SLA": batch.sla_metrics_file_path,
        }
        candidate = mapping.get(stage_key)
        if candidate and Path(candidate).exists():
            return Path(candidate)
        return None

    # =========================================================================
    # Read models
    # =========================================================================
    def get_overview(self) -> PipelineOverview:
        b_list = list(self.batches.values())
        return PipelineOverview(
            total_batches=len(b_list),
            active_batches=sum(1 for b in b_list if b.stage in ["INGESTED", "GATE_PASSED", "RULE_VALIDATED", "ESCALATED_FOR_REVIEW"]),
            completed_batches=sum(1 for b in b_list if b.stage in ["RECONCILED", "PUBLISHED"]),
            quarantined_batches=sum(1 for b in b_list if b.stage == "GATE_QUARANTINED"),
            total_records_processed=sum(b.total_records for b in b_list),
            sla_breaches=sum(1 for b in b_list if b.time_estimate and b.time_estimate.sla_status == "BREACHED"),
            at_risk_count=sum(1 for b in b_list if b.time_estimate and b.time_estimate.sla_status == "AT_RISK"),
            batches=b_list
        )

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


pipeline_orchestrator = PipelineOrchestrator()
