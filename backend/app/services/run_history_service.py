"""
Run History Service — the processing-time knowledge base.

Every completed batch leaves one row here: what the file looked like at ingest,
what the rule engine found, how long the machine work took, how long the batch
sat at the analyst queue, what the local estimator predicted, and what the
forecast agent predicted. Two consumers read it:

- `TimeEstimatorService` derives its throughput and per-escalation queue-wait
  constants from the eligible rows instead of trusting a laptop-measured number.
- The Stage 1 forecast agent is handed a snapshot of the most recent rows with
  every submission, so it can compare the incoming batch to its peers.

Rows are keyed by batch_id and upserted, not appended: an escalated batch is
finalised twice (once when parked, once when the last escalation clears), and
an agent forecast often lands after the run row has already been written.

The durable copy is the `run_history` table in the SQLite database (one row
per batch, the row dict as JSON). The in-memory dict is the working copy and
is loaded once per process. `run_history.csv` under the forecast directory is
rendered on demand for download; a pre-existing one is imported on the first
load so history recorded before the database existed is not lost.

Single-process only. The orchestrator, the batch registry and this service are
in-memory with a database behind them; two API workers would each hold their
own cache.
"""
import csv
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

from app.models.pipeline_models import BatchRecord, TimeEstimate, BatchForecast, GLMatchSummary
from app.config import settings
from app import db

logger = logging.getLogger(__name__)

# Outcomes a row can carry. ESCALATED_PENDING is the only non-terminal one.
TERMINAL_OUTCOMES = {"RECONCILED", "PUBLISHED", "ESCALATED_RESOLVED", "GATE_QUARANTINED"}
CALIBRATION_OUTCOMES = {"RECONCILED", "PUBLISHED", "ESCALATED_RESOLVED"}

# Machine time below this is floor noise: the formula's minimums add up to
# 0.35s, so a run that measured less carries no information about throughput.
MIN_MACHINE_SECONDS = 0.2

CSV_COLUMNS = [
    "batch_id", "completed_at", "source", "filename", "outcome", "provenance", "gate_passed",
    "record_count", "file_size_mb", "file_size_bytes", "currency", "booking_date_range",
    "declared_vs_actual_count_delta",
    "anomaly_count", "auto_remediated_count", "escalated_count", "quarantined_rows_count", "anomaly_rate_pct",
    "matched_count", "unmatched_count", "ambiguous_count",
    "estimate_at_ingest_sec", "estimate_final_sec",
    "est_parse_sec", "est_gate_sec", "est_rule_sec", "est_triage_sec", "est_gl_match_sec",
    "machine_seconds", "queue_wait_seconds", "wall_seconds",
    "throughput_actual_rec_per_sec", "local_error_pct", "local_ratio", "eligible_for_calibration",
    "forecast_seconds", "forecast_p10_seconds", "forecast_p90_seconds", "forecast_confidence",
    "forecast_error_pct", "forecast_execution_id", "forecast_status",
    "calibration_factor_used", "baseline_throughput_used",
]

# What the forecast agent sees per historical run: the feature vector, the
# outcome it was blind to, and the timings. Bookkeeping columns are dropped.
SNAPSHOT_COLUMNS = [
    "batch_id", "completed_at", "source", "outcome",
    "record_count", "file_size_mb", "declared_vs_actual_count_delta",
    "anomaly_count", "escalated_count", "matched_count",
    "estimate_at_ingest_sec", "estimate_final_sec",
    "machine_seconds", "queue_wait_seconds", "wall_seconds",
    "throughput_actual_rec_per_sec", "local_error_pct", "local_ratio", "forecast_error_pct",
]

# Ingest-time features only. Nothing from Stage 3 onwards: anomaly and
# escalation counts are unknown when the forecast is issued, and a column of
# zeros would leak a false signal and make the forecast un-scoreable.
FORECAST_INPUT_COLUMNS = [
    "batch_id", "received_at", "source", "filename",
    "record_count", "file_size_mb", "file_size_bytes", "currency", "booking_date_range",
    "declared_record_count", "actual_record_count", "declared_control_total",
    "declared_vs_actual_count_delta",
    "local_estimate_sec", "local_est_parse_sec", "local_est_gate_sec",
    "local_est_rule_sec", "local_est_gl_match_sec",
    "calibration_source", "calibration_sample_size", "baseline_throughput_used",
    "sla_target_seconds",
]

NUMERIC_COLUMNS = {
    "record_count", "file_size_mb", "file_size_bytes", "declared_vs_actual_count_delta",
    "anomaly_count", "auto_remediated_count", "escalated_count", "quarantined_rows_count",
    "anomaly_rate_pct", "matched_count", "unmatched_count", "ambiguous_count",
    "estimate_at_ingest_sec", "estimate_final_sec",
    "est_parse_sec", "est_gate_sec", "est_rule_sec", "est_triage_sec", "est_gl_match_sec",
    "machine_seconds", "queue_wait_seconds", "wall_seconds",
    "throughput_actual_rec_per_sec", "local_error_pct", "local_ratio",
    "forecast_seconds", "forecast_p10_seconds", "forecast_p90_seconds", "forecast_error_pct",
    "calibration_factor_used", "baseline_throughput_used",
}
BOOL_COLUMNS = {"gate_passed", "eligible_for_calibration"}


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signed_error_pct(estimate: Optional[float], actual: Optional[float]) -> Optional[float]:
    """Positive = over-estimated. Signed on purpose: abs() hides systematic bias."""
    if estimate is None or actual is None or actual <= 0:
        return None
    return round((estimate - actual) / actual * 100.0, 1)


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


class RunHistoryService:
    def __init__(self):
        self._dir: Optional[Path] = None
        self._rows: Dict[str, Dict[str, Any]] = {}          # insertion-ordered, keyed by batch_id
        self._pending_forecasts: Dict[str, BatchForecast] = {}
        self._ingest_features: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._revision = 0
        self._loaded = False

    # ------------------------------------------------------------------
    # Location & lifecycle
    # ------------------------------------------------------------------
    @property
    def directory(self) -> Path:
        return self._dir or settings.forecast_dir

    @property
    def path(self) -> Path:
        return self.directory / "run_history.csv"

    @property
    def revision(self) -> int:
        """Bumps on every change; the estimator recalibrates lazily when it moves."""
        return self._revision

    def configure(self, directory: Path):
        """Test hook: point the service at a scratch directory and start empty."""
        with self._lock:
            self._dir = Path(directory)
            self._dir.mkdir(parents=True, exist_ok=True)
            self.reset()

    def reset(self):
        """Test hook: forget every row, in memory and in the table. The demo
        reset endpoint never calls this — history is kept there."""
        with self._lock:
            self._rows.clear()
            self._pending_forecasts.clear()
            self._ingest_features.clear()
            try:
                with db.tx() as cx:
                    cx.execute("DELETE FROM run_history")
            except Exception as e:
                logger.error(f"Could not clear run_history table: {e}")
            self._loaded = True
            self._revision += 1

    def forget_transients(self):
        """Drops in-flight per-batch state (parked forecasts, ingest features)
        without touching a single recorded row. Used by the demo reset."""
        with self._lock:
            self._pending_forecasts.clear()
            self._ingest_features.clear()

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            with db.read() as cx:
                for r in cx.execute("SELECT row_json FROM run_history"):
                    row = json.loads(r["row_json"])
                    if row.get("batch_id"):
                        self._rows[row["batch_id"]] = row
        except Exception as e:
            logger.error(f"Could not read run_history table: {e}")
            return

        if self._rows:
            logger.info(f"Loaded {len(self._rows)} run-history rows from {settings.db_path}.")
            return

        # One-time import of a history file written before the database existed.
        path = self.path
        if not path.exists():
            return
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for raw in csv.DictReader(f):
                    row = self._coerce(raw)
                    if row.get("batch_id"):
                        self._rows[row["batch_id"]] = row
            if self._rows:
                self._flush_many(self._rows.values())
                logger.info(f"Imported {len(self._rows)} run-history rows from {path} into the database.")
        except Exception as e:
            logger.error(f"Could not import run history from {path}: {e}")

    @staticmethod
    def _coerce(raw: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {}
        for col in CSV_COLUMNS:
            v = raw.get(col, "")
            if col in NUMERIC_COLUMNS:
                row[col] = _num(v)
            elif col in BOOL_COLUMNS:
                row[col] = str(v).strip().lower() in ("true", "1", "yes")
            else:
                row[col] = v if v not in (None, "") else None
        return row

    def _flush(self, batch_id: str):
        """Upserts one row. Never raises into the pipeline — a history write
        failure is logged and the in-memory state stays authoritative."""
        row = self._rows.get(batch_id)
        if row is None:
            return
        try:
            self._flush_many([row])
        except Exception as e:
            logger.error(f"Could not persist run-history row {batch_id}: {e}")

    @staticmethod
    def _flush_many(rows: Iterable[Dict[str, Any]]):
        with db.tx() as cx:
            cx.executemany(
                """INSERT INTO run_history (batch_id, completed_at, outcome, provenance, row_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(batch_id) DO UPDATE SET
                     completed_at=excluded.completed_at, outcome=excluded.outcome,
                     provenance=excluded.provenance, row_json=excluded.row_json""",
                [
                    (r["batch_id"], r.get("completed_at"), r.get("outcome"), r.get("provenance"), json.dumps(r))
                    for r in rows
                ],
            )

    def export_csv(self) -> Path:
        """Renders the whole history to `run_history.csv` for download."""
        path = self.path
        with self._lock:
            self._ensure_loaded()
            rows = list(self._rows.values())
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: self._cell(row.get(c)) for c in CSV_COLUMNS})
        return path

    @staticmethod
    def _cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return round(value, 4)
        return value

    # ------------------------------------------------------------------
    # Stage 1: forecast input + history snapshot for the agent
    # ------------------------------------------------------------------
    def write_forecast_input(self, batch: BatchRecord, estimate: TimeEstimate, meta: Dict[str, Any]) -> Path:
        """
        Writes `{batch_id}_forecast_input.csv` — the single-row feature vector the
        forecast agent predicts from — and remembers those features so the run
        row written later carries the same values.
        """
        declared = meta.get("declared_record_count")
        actual = meta.get("actual_record_count", batch.total_records)
        delta = (int(declared) - int(actual)) if declared is not None and actual is not None else 0

        features = {
            "batch_id": batch.batch_id,
            "received_at": batch.created_at,
            "source": batch.source,
            "filename": batch.filename,
            "record_count": batch.total_records,
            "file_size_mb": estimate.file_size_mb,
            "file_size_bytes": batch.file_size_bytes,
            "currency": meta.get("currency") or "",
            "booking_date_range": meta.get("booking_date_range") or "",
            "declared_record_count": declared if declared is not None else "",
            "actual_record_count": actual,
            "declared_control_total": meta.get("declared_control_total", ""),
            "declared_vs_actual_count_delta": delta,
            "local_estimate_sec": estimate.total_estimated_seconds,
            "local_est_parse_sec": estimate.estimated_parse_time_sec,
            "local_est_gate_sec": estimate.estimated_gate_time_sec,
            "local_est_rule_sec": estimate.estimated_rule_time_sec,
            "local_est_gl_match_sec": estimate.estimated_gl_match_sec,
            "calibration_source": estimate.calibration_source,
            "calibration_sample_size": estimate.calibration_sample_size,
            "baseline_throughput_used": estimate.baseline_throughput_used,
            "sla_target_seconds": estimate.sla_target_seconds,
        }

        with self._lock:
            self._ingest_features[batch.batch_id] = {
                "currency": features["currency"],
                "booking_date_range": features["booking_date_range"],
                "declared_vs_actual_count_delta": delta,
                "estimate_at_ingest_sec": estimate.total_estimated_seconds,
            }

        out = self.directory / f"{batch.batch_id}_forecast_input.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FORECAST_INPUT_COLUMNS)
            writer.writeheader()
            writer.writerow({c: self._cell(features.get(c)) for c in FORECAST_INPUT_COLUMNS})
        return out

    def snapshot_history_for(self, batch_id: str) -> Path:
        """
        Writes `{batch_id}_run_history.csv`: the newest terminal rows, newest
        first, projected to the columns an agent needs. Header-only when there
        is no history yet — an empty file says "nothing to compare against"
        unambiguously; a missing one would be ambiguous. Per-batch so a
        daemon-thread zip never reads a file the pipeline thread is rewriting,
        and so the evidence behind a forecast stays inspectable afterwards.
        """
        with self._lock:
            self._ensure_loaded()
            rows = [
                r for r in self._rows.values()
                if r.get("outcome") in TERMINAL_OUTCOMES and r.get("batch_id") != batch_id
            ]
            rows.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
            rows = rows[: settings.forecast_history_rows]

            out = self.directory / f"{batch_id}_run_history.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=SNAPSHOT_COLUMNS)
                writer.writeheader()
                for r in rows:
                    writer.writerow({c: self._cell(r.get(c)) for c in SNAPSHOT_COLUMNS})
            return out

    # ------------------------------------------------------------------
    # Stage 7: record the run
    # ------------------------------------------------------------------
    def record_run(
        self,
        batch: BatchRecord,
        machine_seconds: float,
        queue_wait_seconds: float,
        wall_seconds: float,
        outcome: str,
        gl_summary: Optional[GLMatchSummary] = None,
    ) -> Dict[str, Any]:
        """Upserts the row for this batch and folds in any forecast that arrived first."""
        est = batch.time_estimate
        with self._lock:
            self._ensure_loaded()
            features = self._ingest_features.get(batch.batch_id, {})
            previous = self._rows.get(batch.batch_id, {})

            record_count = batch.total_records
            machine = round(max(0.0, machine_seconds), 3)
            queue = round(max(0.0, queue_wait_seconds), 3)
            wall = round(max(0.0, wall_seconds), 3)
            estimate_final = est.total_estimated_seconds if est else None

            row: Dict[str, Any] = {
                "batch_id": batch.batch_id,
                "completed_at": _now(),
                "source": batch.source,
                "filename": batch.filename,
                "outcome": outcome,
                "provenance": "LIVE",
                "gate_passed": bool(batch.gate_passed),
                "record_count": record_count,
                "file_size_mb": est.file_size_mb if est else round(batch.file_size_bytes / (1024 * 1024), 2),
                "file_size_bytes": batch.file_size_bytes,
                "currency": features.get("currency") or previous.get("currency"),
                "booking_date_range": features.get("booking_date_range") or previous.get("booking_date_range"),
                "declared_vs_actual_count_delta": features.get(
                    "declared_vs_actual_count_delta", previous.get("declared_vs_actual_count_delta", 0)
                ),
                "anomaly_count": batch.anomaly_count,
                "auto_remediated_count": batch.auto_remediated_count,
                "escalated_count": self._escalated_for_row(batch, previous),
                "quarantined_rows_count": batch.quarantined_rows_count,
                "anomaly_rate_pct": round(batch.anomaly_count / max(1, record_count) * 100.0, 2),
                "matched_count": gl_summary.matched_count if gl_summary else batch.matched_count,
                "unmatched_count": gl_summary.unmatched_reconciling_items if gl_summary else batch.unmatched_count,
                "ambiguous_count": gl_summary.ambiguous_count if gl_summary else 0,
                "estimate_at_ingest_sec": features.get("estimate_at_ingest_sec", previous.get("estimate_at_ingest_sec")),
                "estimate_final_sec": estimate_final,
                "est_parse_sec": est.estimated_parse_time_sec if est else None,
                "est_gate_sec": est.estimated_gate_time_sec if est else None,
                "est_rule_sec": est.estimated_rule_time_sec if est else None,
                "est_triage_sec": est.estimated_anomaly_triage_sec if est else None,
                "est_gl_match_sec": est.estimated_gl_match_sec if est else None,
                "machine_seconds": machine,
                "queue_wait_seconds": queue,
                "wall_seconds": wall,
                "throughput_actual_rec_per_sec": round(record_count / machine, 1) if machine >= 0.05 else None,
                "local_error_pct": _signed_error_pct(estimate_final, wall),
                "local_ratio": round(wall / estimate_final, 4) if estimate_final else None,
                "calibration_factor_used": est.calibration_factor if est else None,
                "baseline_throughput_used": est.baseline_throughput_used if est else None,
            }

            # Carry forward any forecast already attached to an earlier version of
            # this row (the parked -> resolved transition), then merge a forecast
            # that arrived before any row existed.
            for col in ("forecast_seconds", "forecast_p10_seconds", "forecast_p90_seconds",
                        "forecast_confidence", "forecast_execution_id", "forecast_status"):
                row[col] = previous.get(col)
            pending = self._pending_forecasts.pop(batch.batch_id, None)
            if pending is not None:
                self._apply_forecast(row, pending)
            row["forecast_error_pct"] = _signed_error_pct(row.get("forecast_seconds"), wall)
            row["eligible_for_calibration"] = self._is_eligible(row)

            self._rows[batch.batch_id] = row
            self._revision += 1
            self._flush(batch.batch_id)
            return dict(row)

    @staticmethod
    def _escalated_for_row(batch: BatchRecord, previous: Dict[str, Any]) -> int:
        """
        By the time a resolved batch is finalised, batch.escalated_count has
        already dropped to zero. Keep the count that was actually queued so the
        queue-wait-per-escalation derivation has a denominator.
        """
        if batch.escalated_count:
            return batch.escalated_count
        prior = previous.get("escalated_count")
        return int(prior) if prior else 0

    @staticmethod
    def _is_eligible(row: Dict[str, Any]) -> bool:
        return (
            row.get("outcome") in CALIBRATION_OUTCOMES
            and bool(row.get("gate_passed"))
            and (row.get("record_count") or 0) >= settings.calibration_min_records
            and (row.get("machine_seconds") or 0.0) >= MIN_MACHINE_SECONDS
            and (row.get("estimate_final_sec") or 0.0) > 0
        )

    # ------------------------------------------------------------------
    # Forecast capture (arrives asynchronously, possibly before the run row)
    # ------------------------------------------------------------------
    def attach_forecast(self, batch_id: str, forecast: BatchForecast) -> Optional[Dict[str, Any]]:
        """
        Records the agent's prediction against the batch's row. If the run has
        not been recorded yet the forecast is parked and merged by record_run.
        Returns the updated row, or None when parked.
        """
        with self._lock:
            self._ensure_loaded()
            row = self._rows.get(batch_id)
            if row is None or row.get("outcome") == "ESCALATED_PENDING":
                # Not scored against a pending row's partial wall-clock.
                self._pending_forecasts[batch_id] = forecast
                if row is not None:
                    self._apply_forecast(row, forecast)
                    row["forecast_error_pct"] = None
                    self._revision += 1
                    self._flush(batch_id)
                return None

            self._apply_forecast(row, forecast)
            row["forecast_error_pct"] = _signed_error_pct(row.get("forecast_seconds"), row.get("wall_seconds"))
            self._revision += 1
            self._flush(batch_id)
            return dict(row)

    @staticmethod
    def _apply_forecast(row: Dict[str, Any], forecast: BatchForecast):
        row["forecast_seconds"] = forecast.forecast_seconds
        row["forecast_p10_seconds"] = forecast.p10_seconds
        row["forecast_p90_seconds"] = forecast.p90_seconds
        row["forecast_confidence"] = forecast.confidence
        row["forecast_execution_id"] = forecast.agent_execution_id
        row["forecast_status"] = forecast.status

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            row = self._rows.get(batch_id)
            return dict(row) if row else None

    def rows(self, limit: int = 50, eligible_only: bool = False) -> List[Dict[str, Any]]:
        """Newest first."""
        with self._lock:
            self._ensure_loaded()
            out = [dict(r) for r in self._rows.values() if not eligible_only or r.get("eligible_for_calibration")]
        out.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
        return out[:limit]

    def calibration_sample(self, window: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        The eligible rows the estimator calibrates from, newest first.

        Rows measured with the current stopwatch (`LIVE`) are preferred as soon
        as there are enough of them: backfilled rows come from an older clock
        and possibly an older machine regime, and should only carry the
        calibration while the deployment is too young to have its own data.
        """
        limit = window or settings.calibration_window
        eligible = self.rows(limit=10_000, eligible_only=True)
        live = [r for r in eligible if r.get("provenance") == "LIVE"]
        if len(live) >= settings.calibration_min_runs:
            return live[:limit]
        return eligible[:limit]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            rows = list(self._rows.values())
        forecast_errors = [abs(r["forecast_error_pct"]) for r in rows if r.get("forecast_error_pct") is not None]
        local_errors = [
            abs(r["local_error_pct"]) for r in rows
            if r.get("local_error_pct") is not None and r.get("eligible_for_calibration")
        ]
        return {
            "total_runs_recorded": len(rows),
            "forecasts_received": sum(1 for r in rows if r.get("forecast_seconds") is not None),
            "forecast_median_abs_error_pct": round(median(forecast_errors), 1) if forecast_errors else None,
            "local_median_abs_error_pct": round(median(local_errors), 1) if local_errors else None,
        }

    # ------------------------------------------------------------------
    # One-time backfill from the Stage 7 artefacts already on disk
    # ------------------------------------------------------------------
    def backfill_from_sla_metrics(self) -> int:
        """
        Seeds the history from `{batch_id}_sla_metrics.csv` files written by
        earlier runs of this pipeline. Real measurements, not invented data —
        but taken before the queue-wait clock was fixed, so they are tagged
        BACKFILL_SLA_METRICS and their escalated rows fail the eligibility
        filter on their own. Idempotent: a batch already in the history is
        never touched.
        """
        added = 0
        with self._lock:
            self._ensure_loaded()
            for path in sorted(settings.sla_metrics_dir.glob("*_sla_metrics.csv")):
                try:
                    with open(path, newline="", encoding="utf-8") as f:
                        rows = list(csv.DictReader(f))
                except Exception:
                    continue
                if not rows:
                    continue
                src = rows[0]
                batch_id = src.get("batch_id")
                if not batch_id or batch_id in self._rows:
                    continue

                actual = _num(src.get("actual_duration_seconds"))
                records = int(_num(src.get("total_records")) or 0)
                escalated = int(_num(src.get("escalated_count")) or 0)
                estimate = _num(src.get("total_estimated_seconds"))
                mtime = datetime.utcfromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S UTC")

                row = {c: None for c in CSV_COLUMNS}
                row.update({
                    "batch_id": batch_id,
                    "completed_at": mtime,
                    "source": "UNKNOWN",
                    "filename": "",
                    "outcome": "ESCALATED_RESOLVED" if escalated else "RECONCILED",
                    "provenance": "BACKFILL_SLA_METRICS",
                    "gate_passed": True,
                    "record_count": records,
                    "file_size_mb": _num(src.get("file_size_mb")) or 0.0,
                    "file_size_bytes": int((_num(src.get("file_size_mb")) or 0.0) * 1024 * 1024),
                    "declared_vs_actual_count_delta": 0,
                    "anomaly_count": int(_num(src.get("anomaly_count")) or 0),
                    "auto_remediated_count": 0,
                    "escalated_count": escalated,
                    "quarantined_rows_count": 0,
                    "anomaly_rate_pct": round((_num(src.get("anomaly_count")) or 0) / max(1, records) * 100, 2),
                    "matched_count": int(_num(src.get("matched_count")) or 0),
                    "unmatched_count": int(_num(src.get("unmatched_count")) or 0),
                    "ambiguous_count": int(_num(src.get("ambiguous_count")) or 0),
                    "estimate_final_sec": estimate,
                    "est_parse_sec": _num(src.get("estimated_parse_time_sec")),
                    "est_gate_sec": _num(src.get("estimated_gate_time_sec")),
                    "est_rule_sec": _num(src.get("estimated_rule_time_sec")),
                    "est_triage_sec": _num(src.get("estimated_anomaly_triage_sec")),
                    "est_gl_match_sec": _num(src.get("estimated_gl_match_sec")),
                    # The old clock measured machine time only (and reset on resolve).
                    "machine_seconds": actual,
                    "queue_wait_seconds": 0.0,
                    "wall_seconds": actual,
                    "throughput_actual_rec_per_sec": round(records / actual, 1) if actual and actual >= 0.05 else None,
                    "local_error_pct": _signed_error_pct(estimate, actual),
                    "local_ratio": round(actual / estimate, 4) if estimate and actual is not None else None,
                    "baseline_throughput_used": 1450.0,
                    "calibration_factor_used": 1.0,
                })
                row["eligible_for_calibration"] = self._is_eligible(row)
                self._rows[batch_id] = row
                added += 1

            if added:
                self._revision += 1
                try:
                    self._flush_many(
                        r for r in self._rows.values() if r.get("provenance") == "BACKFILL_SLA_METRICS"
                    )
                except Exception as e:
                    logger.error(f"Could not persist backfilled run history: {e}")
                logger.info(f"Backfilled {added} run-history rows from existing SLA metrics artefacts.")
        return added


run_history_service = RunHistoryService()
