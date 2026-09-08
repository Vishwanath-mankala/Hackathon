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

Stage 1 also dispatches the forecast agent (CREWAI_AGENT_FORECAST_ID) before any
processing starts, with the batch's ingest-time features and a snapshot of the
run history, and captures its prediction server-side so the history learns
whether or not anyone has the console open.
"""
import re
import sys
import json
import time
import shutil
import logging
import threading
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from app.models.pipeline_models import (
    BatchRecord,
    BatchForecast,
    ForecastComparison,
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
from app.services.run_history_service import run_history_service
from app.services.feed_queue_service import feed_queue_service
from app.services.publish_service import publish_service
from app.config import settings
from app import db

logger = logging.getLogger(__name__)

RULE_ENGINE_DIR = str(settings.project_root / "Rule Engine")
if RULE_ENGINE_DIR not in sys.path:
    sys.path.insert(0, RULE_ENGINE_DIR)

import rule_engine  # noqa: E402  (path-injected sibling module)

# Aava execution states that mean the job is finished and no longer worth polling.
TERMINAL_AGENT_STATES = {"SUCCESS", "COMPLETED", "FAILED", "ERROR", "CANCELLED"}

# Stages a batch can only be in while the pipeline is actually running it. A
# batch found in one of these at startup was cut off by a restart.
MID_PIPELINE_STAGES = {"INGESTED", "GATE_PASSED", "RULE_VALIDATED"}


class QueueConflict(Exception):
    """The requested feed file has already been turned into a batch."""


# Engine-prepared GL cache rows, keyed by (path, mtime). Parsing them is the
# expensive part of building a RuleEngine; it happens once per process.
_GL_SNAPSHOT: Dict[Any, List[Dict[str, Any]]] = {}
_GL_SNAPSHOT_LOCK = threading.Lock()


class PipelineOrchestrator:
    def __init__(self):
        self.batches: Dict[str, BatchRecord] = {}
        self.batch_dfs: Dict[str, pd.DataFrame] = {}
        self.batch_anomalies: Dict[str, List[AnomalyItem]] = {}
        self.batch_match_results: Dict[str, Any] = {}
        self.gl_cache: Optional[pd.DataFrame] = None
        self._recon_engine = None
        self._reconciled_batches: set = set()
        # Per-batch stopwatch: machine time accumulates while processing, queue
        # time while parked at the analyst queue. See _clock_*.
        self._clocks: Dict[str, Dict[str, Any]] = {}
        # Guards the batch records themselves. Daemon threads (agent submit,
        # forecast poll) hold it while they update an execution and then
        # checkpoint, so it has to be re-entrant.
        self._lock = threading.RLock()
        # Serialises whole pipeline runs. Stage 6 slices the shared RuleEngine's
        # match list by position, so two batches running at once would each
        # collect the other's matches; and it makes claiming a feed-queue row
        # trivially atomic.
        self._pipeline_lock = threading.RLock()

        db.init_schema()
        consumed = self._load_state()
        self._load_gl_cache(consumed)
        try:
            run_history_service.backfill_from_sla_metrics()
        except Exception as e:
            logger.warning(f"Run-history backfill skipped: {e}")
        try:
            total = self.sync_feed_queue()
            logger.info("Sample-feed queue: %s", self._queue_summary_line(total))
        except Exception as e:
            logger.warning(f"Sample-feed queue sync skipped: {e}")
        self._poll_sftp_dropbox()

    # =========================================================================
    # Bootstrap
    # =========================================================================
    def _load_state(self) -> set:
        """
        Rehydrates the batch registry, anomalies and match results from the
        database, restarts the stopwatch of any batch parked at the analyst
        queue so its wait spans the restart, marks batches that were cut off
        mid-pipeline, and returns the GL ids already consumed by Stage 6.
        """
        consumed: set = set()
        now_mono = time.monotonic()
        now_epoch = time.time()
        interrupted: List[str] = []

        with db.read() as cx:
            for r in cx.execute("SELECT * FROM batches ORDER BY created_at"):
                try:
                    batch = BatchRecord.model_validate_json(r["record_json"])
                except Exception as e:
                    logger.error(f"Skipping unreadable batch row {r['batch_id']}: {e}")
                    continue
                self.batches[batch.batch_id] = batch
                if batch.stage == "ESCALATED_FOR_REVIEW" and r["held_at_epoch"] is not None:
                    self._clocks[batch.batch_id] = {
                        "segment_start": now_mono,
                        "machine_accum": r["machine_accum"] or 0.0,
                        "queue_accum": r["queue_accum"] or 0.0,
                        "held_at": now_mono - (now_epoch - r["held_at_epoch"]),
                        "held_at_epoch": r["held_at_epoch"],
                    }
                elif batch.stage in MID_PIPELINE_STAGES:
                    interrupted.append(batch.batch_id)

            for r in cx.execute("SELECT batch_id, items_json FROM batch_anomalies"):
                try:
                    self.batch_anomalies[r["batch_id"]] = [
                        AnomalyItem.model_validate(item) for item in json.loads(r["items_json"])
                    ]
                except Exception as e:
                    logger.error(f"Skipping unreadable anomalies for {r['batch_id']}: {e}")

            for r in cx.execute("SELECT batch_id, results_json FROM batch_match_results"):
                try:
                    results = json.loads(r["results_json"])
                except Exception as e:
                    logger.error(f"Skipping unreadable match results for {r['batch_id']}: {e}")
                    continue
                self.batch_match_results[r["batch_id"]] = results
                for m in results.get("matched", []):
                    gl_id = m.get("internal_txn_id")
                    if gl_id:
                        consumed.add(str(gl_id))

        for batch_id in self.batches:
            self.batch_anomalies.setdefault(batch_id, [])
        self._reconciled_batches = set(self.batch_match_results)

        for batch_id in interrupted:
            batch = self.batches[batch_id]
            batch.stage = "INTERRUPTED"
            batch.failure_reason = "The API restarted while this batch was mid-pipeline."
            batch.updated_at = self._now()
            self._checkpoint(batch_id)
            logger.warning(f"Batch {batch_id} was mid-pipeline at restart; marked INTERRUPTED.")

        events = sorted(
            (b.publish_event for b in self.batches.values() if b.publish_event),
            key=lambda e: e.published_at, reverse=True,
        )
        publish_service.rehydrate(events)

        if self.batches:
            logger.info(
                "Restored %d batches from %s (%d parked at the analyst queue, %d interrupted).",
                len(self.batches), settings.db_path, len(self._clocks), len(interrupted),
            )
        return consumed

    def _load_gl_cache(self, consumed_ids: Optional[set] = None):
        """
        Loads the GL cashbook cache used by Stage 6 reconciliation, minus the
        rows batches in the registry have already settled.

        The engine's constructor parses every cache row (about 14 s for 37k
        rows) and removes a matched row from its lists as it goes, with no way
        to put one back. So the parsed rows are kept as a pristine snapshot,
        built once per process, and every engine — at startup minus the
        consumed ids, or on a demo reset in full — is assembled from copies of
        that snapshot in well under a second.
        """
        if not settings.cache_path.exists():
            logger.warning(f"GL cashbook cache not found at {settings.cache_path}; Stage 6 will report zero matches.")
            return
        try:
            pristine = self._pristine_gl_rows()
            consumed = consumed_ids or set()
            self._recon_engine = self._engine_from_pristine(pristine, consumed)
            self.gl_cache = self._recon_engine.remaining_cache_df()
            logger.info(
                "Loaded GL Cashbook Cache: %d rows available (%d already consumed by restored batches).",
                len(self._recon_engine.cache), len(pristine) - len(self._recon_engine.cache),
            )
        except Exception as e:
            logger.warning(f"Failed to load GL cache: {e}")

    @staticmethod
    def _pristine_gl_rows() -> List[Dict[str, Any]]:
        """The engine-prepared cache rows, parsed once per process per cache file."""
        path = settings.cache_path
        key = (str(path.resolve()), path.stat().st_mtime_ns)
        with _GL_SNAPSHOT_LOCK:
            cached = _GL_SNAPSHOT.get(key)
            if cached is None:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
                engine = rule_engine.RuleEngine(frame, rule_engine.MatchConfig())
                cached = engine.cache
                _GL_SNAPSHOT.clear()
                _GL_SNAPSHOT[key] = cached
            return cached

    @staticmethod
    def _engine_from_pristine(pristine: List[Dict[str, Any]], consumed: set):
        """
        A fresh engine holding copies of every pristine row not in `consumed`.
        Relies on the engine's public state (`cache`, `cache_by_account`,
        `matches`, `ambiguous`, `unmatched_ingest`) exactly as its constructor
        lays it out.
        """
        engine = rule_engine.RuleEngine(pd.DataFrame(), rule_engine.MatchConfig())
        rows = [dict(r) for r in pristine if str(r.get("internal_txn_id")) not in consumed]
        by_account: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by_account.setdefault(str(r.get("account", "")).strip(), []).append(r)
        engine.cache = rows
        engine.cache_by_account = by_account
        engine.matches = []
        engine.ambiguous = []
        engine.unmatched_ingest = []
        return engine

    # =========================================================================
    # Durable state
    # =========================================================================
    def _checkpoint(
        self,
        batch_id: str,
        *,
        anomalies: bool = False,
        results: bool = False,
        queue_row: Optional[Dict[str, Any]] = None,
    ):
        """
        Writes the batch (and optionally its anomalies / match results) to the
        database in one transaction. Serialisation happens under the record
        lock so a daemon-thread update cannot land half-way through a dump.
        Never raises into the pipeline: a persistence failure is logged and the
        in-memory state stays authoritative.
        """
        with self._lock:
            batch = self.batches.get(batch_id)
            if not batch:
                return
            clock = self._clocks.get(batch_id) or {}
            try:
                record_json = batch.model_dump_json()
                anomalies_json = (
                    json.dumps([a.model_dump() for a in self.batch_anomalies.get(batch_id, [])])
                    if anomalies else None
                )
                results_json = (
                    json.dumps(self.batch_match_results[batch_id])
                    if results and batch_id in self.batch_match_results else None
                )
                with db.tx() as cx:
                    cx.execute(
                        """INSERT INTO batches
                           (batch_id, created_at, updated_at, stage, source, filename, record_json,
                            machine_accum, queue_accum, held_at_epoch)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(batch_id) DO UPDATE SET
                             updated_at=excluded.updated_at, stage=excluded.stage,
                             record_json=excluded.record_json, machine_accum=excluded.machine_accum,
                             queue_accum=excluded.queue_accum, held_at_epoch=excluded.held_at_epoch""",
                        (
                            batch.batch_id, batch.created_at, batch.updated_at, batch.stage,
                            batch.source, batch.filename, record_json,
                            self._banked_machine(batch_id), clock.get("queue_accum", 0.0),
                            clock.get("held_at_epoch"),
                        ),
                    )
                    if anomalies_json is not None:
                        cx.execute(
                            "INSERT INTO batch_anomalies (batch_id, items_json) VALUES (?, ?) "
                            "ON CONFLICT(batch_id) DO UPDATE SET items_json=excluded.items_json",
                            (batch_id, anomalies_json),
                        )
                    if results_json is not None:
                        cx.execute(
                            "INSERT INTO batch_match_results (batch_id, results_json) VALUES (?, ?) "
                            "ON CONFLICT(batch_id) DO UPDATE SET results_json=excluded.results_json",
                            (batch_id, results_json),
                        )
                    if queue_row is not None:
                        feed_queue_service.mark_ingested(cx, int(queue_row["sequence"]), batch_id)
            except Exception as e:
                logger.error(f"Could not persist batch {batch_id}: {e}")

    def _banked_machine(self, batch_id: str) -> float:
        """Machine seconds to store: what has been banked, plus the running
        segment if the batch is not parked (so a restart mid-run keeps it)."""
        c = self._clocks.get(batch_id)
        if not c:
            return 0.0
        if c["held_at"] is not None:
            return c["machine_accum"]
        return c["machine_accum"] + (time.monotonic() - c["segment_start"])

    def _frame_path(self, batch_id: str) -> Path:
        return settings.working_frames_dir / f"{batch_id}.pkl"

    def _save_working_frame(self, batch_id: str):
        """Pickle, not CSV: the frame's index labels and NaN cells have to
        survive exactly, because anomalies address rows by index label."""
        df = self.batch_dfs.get(batch_id)
        if df is None:
            return
        try:
            path = self._frame_path(batch_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_pickle(path)
        except Exception as e:
            logger.error(f"Could not save working frame for {batch_id}: {e}")

    def _load_working_frame(self, batch_id: str) -> Optional[pd.DataFrame]:
        path = self._frame_path(batch_id)
        if not path.exists():
            return None
        try:
            df = pd.read_pickle(path)
            self.batch_dfs[batch_id] = df
            return df
        except Exception as e:
            logger.error(f"Could not load working frame for {batch_id}: {e}")
            return None

    def _drop_working_frame(self, batch_id: str):
        try:
            path = self._frame_path(batch_id)
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning(f"Could not remove working frame for {batch_id}: {e}")

    # =========================================================================
    # Sample-feed queue
    # =========================================================================
    def sync_feed_queue(self, reset: bool = False) -> int:
        return feed_queue_service.sync_from_manifest(reset=reset)

    def queue_status(self) -> Dict[str, Any]:
        return feed_queue_service.status()

    @staticmethod
    def _queue_summary_line(total: int) -> str:
        s = feed_queue_service.status()
        return (
            f"{s['pending']} pending, {s['ingested']} ingested, {s['failed']} failed, "
            f"{s['missing']} missing of {total}"
            + (f"; next {s['next']['file']}" if s["next"] else "")
        )

    def reset_state(self, requeue: bool = True) -> Dict[str, Any]:
        """
        Demo reset: forget every batch and put the sample feed back to the
        start. Keeps the run history (real measurements), the sign-off trails
        and every artefact on disk; clears the registry, anomalies, match
        results, parked clocks and working frames, and restores the GL cache
        to its full size.
        """
        with self._pipeline_lock, self._lock:
            cleared = len(self.batches)
            with db.tx() as cx:
                db.clear_tables(cx, "batches", "batch_anomalies", "batch_match_results")
                if requeue:
                    cx.execute("DELETE FROM feed_queue")
            self.batches.clear()
            self.batch_dfs.clear()
            self.batch_anomalies.clear()
            self.batch_match_results.clear()
            self._reconciled_batches.clear()
            self._clocks.clear()
            publish_service.clear()
            run_history_service.forget_transients()
            for pkl in settings.working_frames_dir.glob("*.pkl"):
                try:
                    pkl.unlink()
                except OSError:
                    pass
            self._load_gl_cache(set())
            if requeue:
                self.sync_feed_queue(reset=True)
            return {
                "queue": self.queue_status(),
                "batches_cleared": cleared,
                "gl_cache_rows": len(self._recon_engine.cache) if self._recon_engine else 0,
                "run_history_rows_kept": run_history_service.stats()["total_runs_recorded"],
            }

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
        Ingests the next statement from the sample-feed queue on demand. The
        queue (manifest.csv loaded into the database) is the source: its
        position survives a restart, so repeated pulls walk the feed in order
        instead of re-ingesting the first file. Real SFTP arrivals in
        incoming_sftp/ are picked up by the startup poll.

        With `filename`, ingests that specific queued file: PENDING or FAILED
        rows are ingested (FAILED is the retry path); an INGESTED row raises
        QueueConflict naming its batch; MISSING or unknown raises
        FileNotFoundError.

        Returns (batch, "SAMPLE_FEED", remaining_pending).
        """
        with self._pipeline_lock:
            if filename:
                row = feed_queue_service.get(filename)
                if row is None:
                    raise FileNotFoundError(
                        f"'{filename}' is not in the sample-feed queue. "
                        f"Files are listed in {settings.manifest_path}."
                    )
                if row["status"] == "INGESTED":
                    raise QueueConflict(
                        f"'{filename}' has already been ingested as batch {row['batch_id']}."
                    )
                if row["status"] == "MISSING":
                    raise FileNotFoundError(
                        f"'{filename}' is listed in the manifest but is not on disk under {settings.batches_dir}."
                    )
            else:
                row = feed_queue_service.next_pending()
                if row is None:
                    s = feed_queue_service.status()
                    raise FileNotFoundError(
                        f"The sample feed is exhausted: {s['ingested']} ingested, {s['failed']} failed, "
                        f"{s['missing']} missing of {s['total']}. Reset the feed to start over, "
                        "or upload a statement."
                    )

            source_path = settings.batches_dir / row["file"]
            declared_count = row.get("declared_record_count")
            declared_total = row.get("declared_control_total")
            try:
                batch = self.ingest_batch(
                    file_path=source_path,
                    filename=row["file"],
                    source="SAMPLE_FEED",
                    declared_record_count=int(declared_count) if declared_count is not None else None,
                    declared_control_total=float(declared_total) if declared_total is not None else None,
                    auto_run_pipeline=True,
                    queue_row=row,
                )
            except Exception as e:
                # No batch exists if ingest_file itself failed; a FAILED row is
                # skipped by blind pulls rather than retried forever.
                if feed_queue_service.get(row["file"]) and feed_queue_service.get(row["file"])["status"] != "INGESTED":
                    feed_queue_service.mark_failed(int(row["sequence"]), str(e))
                raise

            remaining = feed_queue_service.status()["pending"]
            return batch, "SAMPLE_FEED", remaining

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
        auto_run_pipeline: bool = True,
        queue_row: Optional[Dict[str, Any]] = None,
    ) -> BatchRecord:
        with self._pipeline_lock:
            # The clock starts before the file is stored and parsed: the estimate
            # models parse time, so the measurement has to include it.
            ingest_started = time.monotonic()
            batch_id, stored_path, meta, df = ingestion_service.ingest_file(
                file_path=file_path,
                file_bytes=file_bytes,
                filename=filename,
                source=source,
                declared_record_count=declared_record_count,
                declared_control_total=declared_control_total
            )
            self._clock_start(batch_id, ingest_started)

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
                estimate_at_ingest_sec=time_est.total_estimated_seconds,
                batch_file_path=str(stored_path)
            )

            self.batches[batch_id] = record
            self.batch_dfs[batch_id] = df
            self.batch_anomalies[batch_id] = []

            # First durable copy — and, for a feed pull, the queue row is marked
            # INGESTED in the same transaction so the two cannot disagree.
            self._checkpoint(batch_id, queue_row=queue_row)

            try:
                # Stage 1 forecast: issued before processing from what is known
                # now plus the history of comparable batches. Registered after
                # the batch is in the registry, since the submit thread looks it
                # up by id.
                self._dispatch_forecast(record, meta)

                if auto_run_pipeline:
                    self.run_pipeline(batch_id, stored_path, meta)
            except Exception as e:
                record.stage = "FAILED"
                record.failure_reason = f"{type(e).__name__}: {e}"
                record.updated_at = self._now()
                logger.exception(f"Pipeline failed for batch {batch_id}")
                raise
            finally:
                self._checkpoint(batch_id, anomalies=True, results=True)

            return record

    def _dispatch_forecast(self, batch: BatchRecord, meta: Dict[str, Any]):
        try:
            input_path = run_history_service.write_forecast_input(batch, batch.time_estimate, meta)
            history_path = run_history_service.snapshot_history_for(batch.batch_id)
            batch.forecast_input_file_path = str(input_path)
            batch.run_history_file_path = str(history_path)
        except Exception as e:
            logger.error(f"Could not write forecast bundle for {batch.batch_id}: {e}")
            batch.agent_forecast = BatchForecast(status="FAILED", message=f"Forecast bundle not written: {e}")
            return

        self._dispatch_agent_async(
            batch, "STAGE_1_FORECAST", batch.forecast_input_file_path,
            extra_paths=[batch.run_history_file_path],
        )
        execution = batch.agent_executions.get("STAGE_1_FORECAST")
        if execution and execution.status == "SKIPPED":
            batch.agent_forecast = BatchForecast(status="SKIPPED", message=execution.message)
        else:
            batch.agent_forecast = BatchForecast(status="PENDING", issued_at=self._now())

    # =========================================================================
    # Stages 2 -> 8
    # =========================================================================
    def run_pipeline(self, batch_id: str, stored_path: Path, meta: Dict[str, Any]):
        batch = self.batches[batch_id]
        df = self.batch_dfs[batch_id]
        if batch_id not in self._clocks:
            self._clock_start(batch_id)

        # ---- Stage 2: File-level Structural Gate ----------------------------
        gate_details = self._execute_structural_gate(batch_id, stored_path, df, meta)
        batch.gate_details = gate_details
        batch.gate_passed = gate_details.passed

        if not gate_details.passed:
            batch.stage = "GATE_QUARANTINED"
            batch.updated_at = self._now()
            logger.warning(f"Batch {batch_id} failed structural gate: {gate_details.reasons}")
            # A quarantined batch is still a run with a measured duration; the
            # history keeps it (ineligible for calibration) so the forecast agent
            # can learn what a file that fails the gate looks like at ingest.
            self._record_history(batch, "GATE_QUARANTINED")
            return batch

        batch.stage = "GATE_PASSED"

        # ---- Stages 3, 4, 5a: rules, anomaly scoring, auto-remediation ------
        clean_df, anomalies, candidate_file = agentic_anomaly_service.evaluate_batch(df, batch_id, stored_path)

        # Stage 5a re-validation loop: rerun Stage 3 over the remediated frame so
        # an auto-fix that itself violates a rule is caught rather than trusted.
        if any(a.status == "AUTO_REMEDIATED" for a in anomalies):
            first_pass_file = candidate_file
            clean_df, anomalies, candidate_file = self._revalidate_after_remediation(
                clean_df, anomalies, batch_id, stored_path
            )
            # A second pass that finds nothing writes no file; the first pass's
            # candidates are still the Stage 4 agent's input.
            candidate_file = candidate_file or first_pass_file

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
            self._clock_hold(batch_id)
            self._finalize_sla(batch)
            batch.updated_at = self._now()
            # The analyst's overrides go into this frame, possibly after a
            # restart, so it has to outlive the process.
            self._save_working_frame(batch_id)
            return batch

        batch.stage = "RULE_VALIDATED"
        self._reconcile_and_finalize(batch, clean_df)
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
    ):
        """Stages 6 -> 8, plus the Stage 6 agent dispatch."""
        if batch.batch_id in self._reconciled_batches:
            # The GL cache is consumed as it is matched, so replaying a batch
            # would settle the same ledger rows twice.
            logger.info(f"Batch {batch.batch_id} already reconciled; skipping Stage 6 replay.")
            return

        gl_summary = self._execute_gl_matching(batch, valid_df)
        self._reconciled_batches.add(batch.batch_id)
        self._drop_working_frame(batch.batch_id)
        batch.gl_summary = gl_summary
        batch.matched_count = gl_summary.matched_count
        batch.unmatched_count = gl_summary.unmatched_reconciling_items

        # ---- Stage 7: SLA estimate + metrics artefact -----------------------
        self._finalize_sla(batch, gl_summary)

        # ---- Stage 6 agent dispatch -----------------------------------------
        self._dispatch_agent_async(batch, "STAGE_6_RECON", batch.ambiguous_file_path or batch.unmatched_file_path)

        # ---- Stage 8: Publish ------------------------------------------------
        batch.stage = "RECONCILED"
        publish_service.publish_batch(batch)
        batch.updated_at = self._now()

    def _finalize_sla(
        self,
        batch: BatchRecord,
        gl_summary: Optional[GLMatchSummary] = None,
    ):
        """
        Stage 7: records the actual run (machine time and analyst queue wait
        separately), writes the history row, exports the SLA feature vector and
        dispatches the SLA agent. Runs once when a batch parks at the analyst
        queue and again when it is released; the history row is upserted.
        """
        if not batch.time_estimate:
            return

        # Keyed off the stopwatch, not batch.stage: on release this runs before
        # the stage flips to RECONCILED.
        if self._is_parked(batch.batch_id):
            outcome = "ESCALATED_PENDING"
        elif self._was_parked(batch.batch_id):
            outcome = "ESCALATED_RESOLVED"
        else:
            outcome = "RECONCILED"
        self._record_history(batch, outcome, gl_summary)

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

    def _record_history(self, batch: BatchRecord, outcome: str, gl_summary: Optional[GLMatchSummary] = None):
        """Reads the stopwatch, stamps the actuals on the batch and upserts its history row."""
        machine, queue, wall = self._clock_read(batch.batch_id)
        batch.machine_seconds = round(machine, 3)
        batch.queue_wait_seconds = round(queue, 3)
        batch.wall_seconds = round(wall, 3)
        if batch.time_estimate:
            time_estimator_service.record_actual_run(batch.time_estimate, machine, queue, wall)
        try:
            run_history_service.record_run(batch, machine, queue, wall, outcome, gl_summary)
        except Exception as e:
            logger.error(f"Could not record run history for {batch.batch_id}: {e}")
        # A forecast that arrived while the batch was parked can now be scored.
        self._score_forecast(batch)

    # =========================================================================
    # Stopwatch
    #
    # There is deliberately no clock value to pass around: a caller that could
    # pass one could pass a fresh one, which is how analyst queue wait went
    # unmeasured for 54 batches. time.monotonic() so NTP steps cannot skew it.
    # =========================================================================
    def _clock_start(self, batch_id: str, started_at: Optional[float] = None):
        self._clocks[batch_id] = {
            "segment_start": started_at if started_at is not None else time.monotonic(),
            "machine_accum": 0.0,
            "queue_accum": 0.0,
            "held_at": None,
            "held_at_epoch": None,   # wall-clock twin of held_at; survives a restart
        }

    def _clock_hold(self, batch_id: str):
        """Entering the analyst queue: bank the machine time, start counting wait."""
        c = self._clocks.get(batch_id)
        if not c or c["held_at"] is not None:
            return
        now = time.monotonic()
        c["machine_accum"] += now - c["segment_start"]
        c["held_at"] = now
        c["held_at_epoch"] = time.time()

    def _clock_release(self, batch_id: str):
        """Last escalation cleared: bank the wait, machine time resumes."""
        c = self._clocks.get(batch_id)
        if not c or c["held_at"] is None:
            return
        now = time.monotonic()
        c["queue_accum"] += now - c["held_at"]
        c["held_at"] = None
        c["held_at_epoch"] = None
        c["segment_start"] = now

    def _is_parked(self, batch_id: str) -> bool:
        c = self._clocks.get(batch_id)
        return bool(c and c["held_at"] is not None)

    def _was_parked(self, batch_id: str) -> bool:
        c = self._clocks.get(batch_id)
        return bool(c and c["queue_accum"] > 0)

    def _clock_read(self, batch_id: str) -> Tuple[float, float, float]:
        """(machine, queue_wait, wall) seconds so far. Non-destructive."""
        c = self._clocks.get(batch_id)
        if not c:
            return 0.0, 0.0, 0.0
        now = time.monotonic()
        machine = c["machine_accum"]
        queue = c["queue_accum"]
        if c["held_at"] is not None:
            queue += now - c["held_at"]
        else:
            machine += now - c["segment_start"]
        return machine, queue, machine + queue

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

        # These records are served straight out of /recon as JSON. The ingested
        # frame is read with pandas defaults, so an empty cell is a float NaN —
        # which json.dumps refuses. Nullify at this boundary so an empty
        # reference or narrative never turns the read model into a 500.
        matched_records = self._json_safe_records(matches_df)
        unmatched_records = self._json_safe_records(unmatched_df)
        ambiguous_records = self._json_safe_records(ambiguous_df)

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

        with self._pipeline_lock:
            try:
                return self._resolve_escalation_locked(batch_id, anomaly_id, action, override_values, analyst_notes)
            finally:
                self._checkpoint(batch_id, anomalies=True, results=True)

    def _resolve_escalation_locked(
        self,
        batch_id: str,
        anomaly_id: str,
        action: str,
        override_values: Optional[Dict[str, Any]],
        analyst_notes: Optional[str],
    ) -> BatchRecord:
        batch = self.batches[batch_id]
        anomalies = self.batch_anomalies.get(batch_id, [])
        target = next((a for a in anomalies if a.id == anomaly_id), None)
        if not target:
            raise KeyError(f"Anomaly {anomaly_id} not found in batch {batch_id}.")

        df = self.batch_dfs.get(batch_id)
        if df is None:
            # Parked before a restart: the frame was pickled when the batch parked.
            df = self._load_working_frame(batch_id)
        if df is None:
            raise ValueError(
                f"The working data for batch {batch_id} is no longer available, so an override "
                "cannot be applied. Re-ingest the statement."
            )
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
            # The batch has been parked since Stage 5b; that wait is the actual
            # SLA cost and is what the forecast is scored against.
            self._clock_release(batch_id)
            self._reconcile_and_finalize(batch, valid_df)
        else:
            # Still parked: keep the overridden frame durable for the next resolve.
            self._save_working_frame(batch_id)

        batch.updated_at = self._now()
        return batch

    # =========================================================================
    # Automatic multi-agent dispatch
    # =========================================================================
    def _dispatch_agent_async(
        self,
        batch: BatchRecord,
        stage_key: str,
        artifact_path: Optional[str],
        extra_paths: Optional[List[str]] = None,
    ):
        """
        Fires the agent registered for `stage_key` against `artifact_path` on a
        background thread so the synchronous pipeline never blocks on the
        external platform. `extra_paths` are bundled into the same zip. Records
        the outcome on batch.agent_executions.
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
        extras = [Path(p) for p in (extra_paths or []) if p]

        threading.Thread(
            target=self._submit_agent_job,
            args=(batch.batch_id, stage_key, Path(artifact_path), agent["id"], extras),
            daemon=True,
            name=f"agent-{stage_key}-{batch.batch_id}",
        ).start()

    def _submit_agent_job(
        self,
        batch_id: str,
        stage_key: str,
        artifact: Path,
        agent_id: str,
        extras: Optional[List[Path]] = None,
    ):
        result = agentic_anomaly_service.agent_bridge.submit_batch_to_agent(
            artifact, agent_id=agent_id, extra_files=extras
        )

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
            execution.bundled_files = list(result.get("bundled_files") or [artifact.name])
            execution.status = "SUBMITTED" if execution.success else "FAILED"
            batch.agent_execution = execution.model_dump()
            batch.updated_at = self._now()

            if stage_key == "STAGE_1_FORECAST":
                if execution.success and execution.agent_execution_id:
                    if batch.agent_forecast:
                        batch.agent_forecast.agent_execution_id = execution.agent_execution_id
                    threading.Thread(
                        target=self._await_forecast,
                        args=(batch_id,),
                        daemon=True,
                        name=f"forecast-poll-{batch_id}",
                    ).start()
                elif batch.agent_forecast:
                    batch.agent_forecast.status = "FAILED"
                    batch.agent_forecast.message = execution.message

            self._checkpoint(batch_id)

    def refresh_agent_outputs(self, batch_id: str) -> Dict[str, AgentExecution]:
        """
        Pulls the latest execution output for every non-terminal agent job on
        this batch. Called by the console's polling endpoint — the operator
        never has to press anything to make an agent run.
        """
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")

        batch = self.batches[batch_id]
        changed = False
        for execution in list(batch.agent_executions.values()):
            before = (execution.status, execution.output is not None)
            self._refresh_one(batch, execution)
            changed = changed or before != (execution.status, execution.output is not None)

        batch.updated_at = self._now()
        if changed:
            self._checkpoint(batch_id)
        return batch.agent_executions

    def _refresh_one(self, batch: BatchRecord, execution: AgentExecution) -> bool:
        """
        One platform poll for one execution. Shared by the console endpoint and
        the server-side forecast poller, so the two cannot drift; mutation is
        under the lock because both can hit the same execution at once.
        Returns True once the execution is terminal.
        """
        if not execution.agent_execution_id:
            return execution.status in TERMINAL_AGENT_STATES or execution.status == "SKIPPED"
        if execution.status in TERMINAL_AGENT_STATES:
            return True

        data = agentic_anomaly_service.agent_bridge.get_agent_execution_output(execution.agent_execution_id)

        with self._lock:
            if not data.get("success"):
                execution.message = data.get("message") or execution.message
                return False

            execution.output = data.get("output")
            execution.status = (data.get("status") or "IN_PROGRESS").upper()
            terminal = execution.status in TERMINAL_AGENT_STATES
            if terminal:
                execution.completed_at = data.get("modifiedAt") or self._now()
                if execution.stage == "STAGE_1_FORECAST" and not execution.forecast_captured:
                    self._capture_forecast(batch, execution)
            return terminal

    # =========================================================================
    # Forecast capture — closes the loop without a browser
    # =========================================================================
    def _await_forecast(self, batch_id: str):
        """
        Bounded poll for the forecast result. Stops on a terminal state or
        after forecast_poll_max_attempts, marking the forecast TIMED_OUT so the
        history row never carries an imputed value.
        """
        for _ in range(settings.forecast_poll_max_attempts):
            time.sleep(settings.forecast_poll_seconds)
            batch = self.batches.get(batch_id)
            if not batch:
                return
            execution = batch.agent_executions.get("STAGE_1_FORECAST")
            if not execution or not execution.agent_execution_id:
                return
            try:
                if self._refresh_one(batch, execution):
                    self._checkpoint(batch_id)
                    return
            except Exception as e:
                logger.warning(f"Forecast poll failed for {batch_id}: {e}")

        with self._lock:
            batch = self.batches.get(batch_id)
            if batch and batch.agent_forecast and batch.agent_forecast.status == "PENDING":
                batch.agent_forecast.status = "TIMED_OUT"
                batch.agent_forecast.message = (
                    f"No result after {settings.forecast_poll_max_attempts} polls; "
                    "the history row keeps a blank forecast rather than a guess."
                )
                self._attach_forecast_to_history(batch)
                self._checkpoint(batch_id)

    def _capture_forecast(self, batch: BatchRecord, execution: AgentExecution):
        """Parses the agent's answer into BatchForecast and records it in the history. Idempotent."""
        execution.forecast_captured = True
        forecast = batch.agent_forecast or BatchForecast()
        forecast.agent_execution_id = execution.agent_execution_id
        forecast.received_at = self._now()

        if execution.status not in ("SUCCESS", "COMPLETED"):
            forecast.status = "FAILED"
            forecast.message = execution.message or f"Agent execution ended {execution.status}."
            batch.agent_forecast = forecast
            self._attach_forecast_to_history(batch)
            return

        parsed = self._parse_forecast_output(execution.output)
        if not parsed or parsed.get("forecast_seconds") is None:
            forecast.status = "UNPARSEABLE"
            forecast.message = (
                "The agent replied, but not with the JSON contract in AGENTS.md; "
                "see the raw output. Nothing was recorded as a prediction."
            )
            batch.agent_forecast = forecast
            self._attach_forecast_to_history(batch)
            return

        forecast.status = "RECEIVED"
        forecast.message = None
        forecast.forecast_seconds = parsed.get("forecast_seconds")
        forecast.p10_seconds = parsed.get("p10_seconds")
        forecast.p90_seconds = parsed.get("p90_seconds")
        forecast.confidence = parsed.get("confidence")
        forecast.breach_probability_pct = parsed.get("breach_probability_pct")
        forecast.expected_escalation_rate_pct = parsed.get("expected_escalation_rate_pct")
        forecast.dominant_uncertainty = parsed.get("dominant_uncertainty")
        forecast.comparable_batches = parsed.get("comparable_batches") or []
        forecast.reasoning = parsed.get("reasoning")
        forecast.dashboard_line = parsed.get("dashboard_line")
        batch.agent_forecast = forecast
        self._attach_forecast_to_history(batch)
        self._score_forecast(batch)

    def _attach_forecast_to_history(self, batch: BatchRecord):
        if not batch.agent_forecast:
            return
        try:
            run_history_service.attach_forecast(batch.batch_id, batch.agent_forecast)
        except Exception as e:
            logger.error(f"Could not attach forecast to history for {batch.batch_id}: {e}")

    def _score_forecast(self, batch: BatchRecord):
        """Signed error vs measured wall-clock, once both exist and the batch is not parked."""
        f = batch.agent_forecast
        if not f or f.status != "RECEIVED" or f.forecast_seconds is None:
            return
        if self._is_parked(batch.batch_id) or not batch.wall_seconds:
            return
        f.error_pct = round((f.forecast_seconds - batch.wall_seconds) / batch.wall_seconds * 100.0, 1)

    @staticmethod
    def _parse_forecast_output(raw: Any) -> Optional[Dict[str, Any]]:
        """
        Tolerant reader for the forecast contract: a dict, a JSON string, a
        ```json-fenced string, or JSON embedded in prose. Anything else → None,
        never an exception. Numeric fields are coerced; garbage in a field is
        dropped rather than trusted.
        """
        obj: Any = raw
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
            candidate = fenced.group(1).strip() if fenced else text
            if not candidate.startswith("{"):
                start, end = candidate.find("{"), candidate.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    return None
                candidate = candidate[start:end + 1]
            try:
                obj = json.loads(candidate)
            except (ValueError, TypeError):
                return None
        if not isinstance(obj, dict):
            return None

        def num(key: str) -> Optional[float]:
            v = obj.get(key)
            if v is None or isinstance(v, bool):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def text(key: str) -> Optional[str]:
            v = obj.get(key)
            return str(v) if v is not None and not isinstance(v, (dict, list)) else None

        comparables = obj.get("comparable_batches")
        if not isinstance(comparables, list):
            comparables = []

        return {
            "forecast_seconds": num("forecast_seconds"),
            "p10_seconds": num("p10_seconds"),
            "p90_seconds": num("p90_seconds"),
            "confidence": text("confidence"),
            "breach_probability_pct": num("breach_probability_pct"),
            "expected_escalation_rate_pct": num("expected_escalation_rate_pct"),
            "dominant_uncertainty": text("dominant_uncertainty"),
            "comparable_batches": [str(c) for c in comparables][:20],
            "reasoning": text("reasoning"),
            "dashboard_line": text("dashboard_line"),
        }

    def get_forecast_comparison(self, batch_id: str) -> ForecastComparison:
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")
        batch = self.batches[batch_id]
        if not batch.time_estimate:
            raise ValueError(f"No estimate available for '{batch_id}'.")

        actual = None
        if batch.wall_seconds is not None:
            actual = {
                "machine_seconds": batch.machine_seconds,
                "queue_wait_seconds": batch.queue_wait_seconds,
                "wall_seconds": batch.wall_seconds,
                "still_parked": False,
            }
        if self._is_parked(batch_id):
            # Show the live wait so the operator sees the budget burning.
            machine, queue, wall = self._clock_read(batch_id)
            actual = {
                "machine_seconds": round(machine, 3),
                "queue_wait_seconds": round(queue, 3),
                "wall_seconds": round(wall, 3),
                "still_parked": True,
            }

        return ForecastComparison(
            batch_id=batch_id,
            stage=batch.stage,
            local_estimate=batch.time_estimate,
            agent_forecast=batch.agent_forecast,
            execution=batch.agent_executions.get("STAGE_1_FORECAST"),
            actual=actual,
            calibration=time_estimator_service.calibration_summary(),
        )

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
        artifact, extras = self._bundle_for_stage(batch, stage_key)
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
        if stage_key == "STAGE_1_FORECAST":
            batch.agent_forecast = BatchForecast(status="PENDING", issued_at=self._now())

        self._submit_agent_job(batch_id, stage_key, artifact, resolved_agent_id, extras)
        self._checkpoint(batch_id)
        return batch.agent_executions[stage_key]

    # =========================================================================
    # Stage 8 — publish (also the manual re-publish endpoint)
    # =========================================================================
    def publish(self, batch_id: str):
        if batch_id not in self.batches:
            raise KeyError(f"Batch '{batch_id}' not found.")
        batch = self.batches[batch_id]
        event = publish_service.publish_batch(batch)
        self._checkpoint(batch_id)
        return event

    def _bundle_for_stage(self, batch: BatchRecord, stage_key: str) -> Tuple[Optional[Path], List[Path]]:
        """
        (primary artefact, extra members) for a stage. One place for the
        mapping so a manual retry sends exactly the bundle the automatic
        dispatch did.
        """
        mapping: Dict[str, Tuple[Optional[str], List[Optional[str]]]] = {
            "STAGE_1_FORECAST": (batch.forecast_input_file_path, [batch.run_history_file_path]),
            "STAGE_1_EXTRACTION": (batch.batch_file_path, []),
            "STAGE_4_ANOMALY": (batch.anomaly_file_path or batch.batch_file_path, []),
            "STAGE_6_RECON": (batch.ambiguous_file_path or batch.unmatched_file_path, []),
            "STAGE_7_SLA": (batch.sla_metrics_file_path, []),
        }
        primary, extras = mapping.get(stage_key, (None, []))
        if not primary or not Path(primary).exists():
            return None, []
        return Path(primary), [Path(p) for p in extras if p and Path(p).exists()]

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
    def _json_safe_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """to_dict(records) with every NaN/NaT replaced by None."""
        if df is None or df.empty:
            return []
        return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


pipeline_orchestrator = PipelineOrchestrator()
