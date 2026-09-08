"""
Processing Time & SLA Estimator Service.

Predicts processing time and completion ETA from file size, record count and
anomaly severity, and judges the result against the SLA budget.

The formula's shape is declared; two of its constants are measured. We only ever
observe ONE total duration per run, so the per-stage coefficients (parse rate,
gate divisor, stage weights, per-anomaly cost) cannot be separated from the data
and stay as declared structure. What the run history does identify is:

- `baseline_throughput` — every non-floored term is a records/throughput ratio,
  so it inverts cleanly from machine time on batches big enough to leave the
  floors.
- `queue_wait_per_escalation` — analyst wall-clock per escalated row, from
  batches that were parked and later resolved.

A residual factor (median measured/estimated machine time) is computed for
display so an operator can see how far the declared structure is from reality,
but it is not applied: it would only absorb the terms we have no signal on.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
import csv
import logging

from app.models.pipeline_models import TimeEstimate, CalibrationSummary
from app.services.run_history_service import run_history_service
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_BASELINE_THROUGHPUT = 1450.0        # records/sec, the original laptop figure
DEFAULT_QUEUE_WAIT_PER_ESCALATION = 8.0     # seconds of analyst wait per escalated row
DEFAULT_SLA_TARGET_SECONDS = 900.0          # 15-minute cut-off

THROUGHPUT_CLAMP = (100.0, 20000.0)
QUEUE_WAIT_CLAMP = (1.0, 3600.0)

# Declared per-stage structure (see module docstring: not measured).
PARSE_SEC_PER_MB = 0.15
GATE_RECORDS_PER_SEC = 15000.0
RULE_STAGE_WEIGHT = 1.5        # rule engine runs at 1.5x baseline throughput
GL_STAGE_WEIGHT = 0.8          # waterfall matching runs at 0.8x baseline throughput
TRIAGE_SEC_PER_ANOMALY = 0.02
# Sum of the throughput-scaled terms per record: 1/1.5 + 1/0.8
THROUGHPUT_TERM_PER_RECORD = (1.0 / RULE_STAGE_WEIGHT) + (1.0 / GL_STAGE_WEIGHT)


class TimeEstimatorService:
    def __init__(self):
        self.sla_target_seconds: float = DEFAULT_SLA_TARGET_SECONDS
        self.baseline_throughput: float = DEFAULT_BASELINE_THROUGHPUT
        self.queue_wait_per_escalation: float = DEFAULT_QUEUE_WAIT_PER_ESCALATION
        self.residual_factor: float = 1.0
        self.calibration_source: str = "DEFAULT"
        self.calibration_sample_size: int = 0
        self._cal_revision: int = -1

    # ------------------------------------------------------------------
    # Calibration from the run history
    # ------------------------------------------------------------------
    def reset_calibration(self):
        """Test hook: forget any derived constants."""
        self.baseline_throughput = DEFAULT_BASELINE_THROUGHPUT
        self.queue_wait_per_escalation = DEFAULT_QUEUE_WAIT_PER_ESCALATION
        self.residual_factor = 1.0
        self.calibration_source = "DEFAULT"
        self.calibration_sample_size = 0
        self._cal_revision = -1

    def _refresh_calibration(self):
        """Recomputes only when the history has changed since the last estimate."""
        rev = run_history_service.revision
        if rev == self._cal_revision:
            return
        self._cal_revision = rev

        sample = run_history_service.calibration_sample()
        self.calibration_sample_size = len(sample)

        if len(sample) < settings.calibration_min_runs:
            self.baseline_throughput = DEFAULT_BASELINE_THROUGHPUT
            self.queue_wait_per_escalation = DEFAULT_QUEUE_WAIT_PER_ESCALATION
            self.residual_factor = 1.0
            self.calibration_source = "DEFAULT"
            return

        throughput = self._derive_throughput(sample)
        self.baseline_throughput = throughput if throughput is not None else DEFAULT_BASELINE_THROUGHPUT
        queue_wait = self._derive_queue_wait(sample)
        self.queue_wait_per_escalation = (
            queue_wait if queue_wait is not None else DEFAULT_QUEUE_WAIT_PER_ESCALATION
        )
        self.residual_factor = self._derive_residual_factor(sample)
        self.calibration_source = "HISTORY" if throughput is not None else "DEFAULT"
        logger.info(
            "Estimator calibrated from %d runs: throughput %.0f rec/s (default %.0f), "
            "queue wait %.1fs/escalation (default %.1f), residual factor %.2f",
            len(sample), self.baseline_throughput, DEFAULT_BASELINE_THROUGHPUT,
            self.queue_wait_per_escalation, DEFAULT_QUEUE_WAIT_PER_ESCALATION, self.residual_factor,
        )

    @staticmethod
    def _derive_throughput(rows: List[Dict[str, Any]]) -> Optional[float]:
        """
        rule_time + gl_time = records * THROUGHPUT_TERM_PER_RECORD / BT, and every
        other machine term is a known constant on a real batch, so invert:
        BT = records * term / (machine - parse - gate - anomaly*0.02).
        Runs where that denominator is mostly floor noise are skipped.
        """
        samples = []
        for r in rows:
            machine = r.get("machine_seconds") or 0.0
            records = r.get("record_count") or 0
            denom = (
                machine
                - (r.get("est_parse_sec") or 0.0)
                - (r.get("est_gate_sec") or 0.0)
                - (r.get("anomaly_count") or 0) * TRIAGE_SEC_PER_ANOMALY
            )
            if records <= 0 or denom < 0.2 or denom < 0.4 * machine:
                continue
            samples.append(records * THROUGHPUT_TERM_PER_RECORD / denom)
        if not samples:
            return None
        bt = median(samples)
        clamped = min(max(bt, THROUGHPUT_CLAMP[0]), THROUGHPUT_CLAMP[1])
        if clamped != bt:
            logger.warning("Derived throughput %.0f rec/s clamped to %.0f", bt, clamped)
        return round(clamped, 1)

    @staticmethod
    def _derive_queue_wait(rows: List[Dict[str, Any]]) -> Optional[float]:
        """Median analyst wait per escalated row, over batches that were parked and resolved."""
        samples = [
            (r.get("queue_wait_seconds") or 0.0) / r["escalated_count"]
            for r in rows
            if r.get("outcome") == "ESCALATED_RESOLVED"
            and (r.get("escalated_count") or 0) > 0
            and (r.get("queue_wait_seconds") or 0.0) > 0
        ]
        if len(samples) < 3:
            return None
        qw = median(samples)
        clamped = min(max(qw, QUEUE_WAIT_CLAMP[0]), QUEUE_WAIT_CLAMP[1])
        return round(clamped, 2)

    @staticmethod
    def _derive_residual_factor(rows: List[Dict[str, Any]]) -> float:
        """Median measured/estimated machine time. Display only; never applied."""
        ratios = []
        for r in rows:
            machine = r.get("machine_seconds") or 0.0
            est_machine = (
                (r.get("est_parse_sec") or 0.0) + (r.get("est_gate_sec") or 0.0)
                + (r.get("est_rule_sec") or 0.0) + (r.get("est_gl_match_sec") or 0.0)
                + (r.get("anomaly_count") or 0) * TRIAGE_SEC_PER_ANOMALY
            )
            if machine > 0 and est_machine > 0:
                ratios.append(machine / est_machine)
        if not ratios:
            return 1.0
        return round(min(max(median(ratios), 0.1), 10.0), 3)

    def calibration_summary(self) -> CalibrationSummary:
        self._refresh_calibration()
        stats = run_history_service.stats()
        return CalibrationSummary(
            source=self.calibration_source,
            sample_size=self.calibration_sample_size,
            min_runs_required=settings.calibration_min_runs,
            baseline_throughput=self.baseline_throughput,
            default_throughput=DEFAULT_BASELINE_THROUGHPUT,
            queue_wait_per_escalation_sec=self.queue_wait_per_escalation,
            default_queue_wait_sec=DEFAULT_QUEUE_WAIT_PER_ESCALATION,
            residual_factor=self.residual_factor,
            **stats,
        )

    # ------------------------------------------------------------------
    # Estimate
    # ------------------------------------------------------------------
    def estimate_processing_time(
        self,
        batch_id: str,
        file_size_bytes: int,
        record_count: int,
        anomaly_count: int = 0,
        escalated_count: int = 0
    ) -> TimeEstimate:
        self._refresh_calibration()
        bt = self.baseline_throughput
        file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

        # 1. Parsing & ingestion overhead (byte size & I/O)
        parse_time = round(max(0.1, file_size_mb * PARSE_SEC_PER_MB), 3)

        # 2. Structural gate verification
        gate_time = round(max(0.05, record_count / GATE_RECORDS_PER_SEC), 3)

        # 3. Row-level rule execution (cross-row checks)
        rule_time = round(max(0.1, record_count / (bt * RULE_STAGE_WEIGHT)), 3)

        # 4. Anomaly scoring & triage. Automated triage is compute; escalation is
        #    analyst wall-clock and is what actually threatens an SLA.
        triage_compute = anomaly_count * TRIAGE_SEC_PER_ANOMALY
        queue_wait = round(escalated_count * self.queue_wait_per_escalation, 3)
        anomaly_triage = round(triage_compute + queue_wait, 3)

        # 5. GL matching engine (tiered waterfall)
        gl_match_time = round(max(0.1, record_count / (bt * GL_STAGE_WEIGHT)), 3)

        machine = round(parse_time + gate_time + rule_time + triage_compute + gl_match_time, 3)
        total_sec = round(machine + queue_wait, 2)

        effective_throughput = round(record_count / max(0.5, total_sec), 1)

        eta_dt = datetime.utcnow() + timedelta(seconds=total_sec)
        eta_str = eta_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        if total_sec <= (self.sla_target_seconds * 0.8):
            sla_status = "ON_TRACK"
        elif total_sec <= self.sla_target_seconds:
            sla_status = "AT_RISK"
        else:
            sla_status = "BREACHED"

        return TimeEstimate(
            batch_id=batch_id,
            file_size_bytes=file_size_bytes,
            file_size_mb=file_size_mb,
            total_records=record_count,
            anomaly_count=anomaly_count,
            throughput_records_per_sec=effective_throughput,
            estimated_parse_time_sec=parse_time,
            estimated_gate_time_sec=gate_time,
            estimated_rule_time_sec=rule_time,
            estimated_anomaly_triage_sec=anomaly_triage,
            estimated_gl_match_sec=gl_match_time,
            total_estimated_seconds=total_sec,
            eta_timestamp=eta_str,
            sla_target_seconds=self.sla_target_seconds,
            sla_status=sla_status,
            estimated_machine_seconds=machine,
            estimated_queue_wait_sec=queue_wait,
            calibration_source=self.calibration_source,
            calibration_sample_size=self.calibration_sample_size,
            calibration_factor=self.residual_factor,
            baseline_throughput_used=bt,
        )

    # ------------------------------------------------------------------
    # Stage 7 artefact + actuals
    # ------------------------------------------------------------------
    def export_sla_metrics(
        self,
        estimate: TimeEstimate,
        escalated_count: int = 0,
        matched_count: int = 0,
        unmatched_count: int = 0,
        ambiguous_count: int = 0,
    ) -> Path:
        """
        Stage 7 artefact. Writes the SLA feature vector consumed by the
        SLA Analysis & Urgency Classifier agent (CREWAI_AGENT_SLA_ID).
        """
        out_path = settings.sla_metrics_dir / f"{estimate.batch_id}_sla_metrics.csv"
        row = {
            "batch_id": estimate.batch_id,
            "total_records": estimate.total_records,
            "file_size_mb": estimate.file_size_mb,
            "anomaly_count": estimate.anomaly_count,
            "escalated_count": escalated_count,
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "ambiguous_count": ambiguous_count,
            "throughput_records_per_sec": estimate.throughput_records_per_sec,
            "estimated_parse_time_sec": estimate.estimated_parse_time_sec,
            "estimated_gate_time_sec": estimate.estimated_gate_time_sec,
            "estimated_rule_time_sec": estimate.estimated_rule_time_sec,
            "estimated_anomaly_triage_sec": estimate.estimated_anomaly_triage_sec,
            "estimated_gl_match_sec": estimate.estimated_gl_match_sec,
            "estimated_queue_wait_sec": estimate.estimated_queue_wait_sec,
            "total_estimated_seconds": estimate.total_estimated_seconds,
            "sla_target_seconds": estimate.sla_target_seconds,
            "sla_consumed_pct": round(
                estimate.total_estimated_seconds / max(1.0, estimate.sla_target_seconds) * 100, 2
            ),
            "sla_status": estimate.sla_status,
            "eta_timestamp": estimate.eta_timestamp,
            "actual_duration_seconds": estimate.actual_duration_seconds if estimate.actual_duration_seconds is not None else "",
            "machine_seconds": estimate.machine_seconds if estimate.machine_seconds is not None else "",
            "queue_wait_seconds": estimate.queue_wait_seconds if estimate.queue_wait_seconds is not None else "",
            "calibration_source": estimate.calibration_source,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)
        return out_path

    def record_actual_run(
        self,
        estimate: TimeEstimate,
        machine_seconds: float,
        queue_wait_seconds: float = 0.0,
        wall_seconds: Optional[float] = None,
    ):
        """Stamps the measured timings on the estimate. Wall-clock is what the SLA is judged on."""
        wall = wall_seconds if wall_seconds is not None else machine_seconds + queue_wait_seconds
        estimate.machine_seconds = round(machine_seconds, 3)
        estimate.queue_wait_seconds = round(queue_wait_seconds, 3)
        estimate.actual_duration_seconds = round(wall, 3)
        estimate.completed_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


time_estimator_service = TimeEstimatorService()
