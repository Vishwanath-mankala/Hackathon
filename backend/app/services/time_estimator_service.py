"""
Processing Time & SLA Estimator Service.
Predicts processing time and completion ETA based on file size, record count,
anomaly severity distribution, and historical throughput benchmarks.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import csv
import math

from app.models.pipeline_models import TimeEstimate
from app.config import settings


class TimeEstimatorService:
    def __init__(self):
        # Baseline throughput: records processed per second on standard infrastructure
        self.baseline_throughput: float = 1450.0  # records/sec
        self.sla_target_seconds: float = 900.0   # Default 15-minute SLA target
        self.historical_runs = []

    def estimate_processing_time(
        self,
        batch_id: str,
        file_size_bytes: int,
        record_count: int,
        anomaly_count: int = 0,
        escalated_count: int = 0
    ) -> TimeEstimate:
        file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

        # 1. Parsing & Ingestion overhead (depends on byte size & I/O)
        parse_time = round(max(0.1, file_size_mb * 0.15), 3)

        # 2. Structural Gate verification time
        gate_time = round(max(0.05, record_count / 15000.0), 3)

        # 3. Row-level Rule execution time (cross-row checks)
        rule_time = round(max(0.1, record_count / (self.baseline_throughput * 1.5)), 3)

        # 4. Anomaly scoring & triage overhead
        # Automated triage takes ~0.02s per anomaly; human escalation adds queue wait estimate (~10s per item)
        anomaly_triage = round(
            (anomaly_count * 0.02) + (escalated_count * 8.0),
            3
        )

        # 5. GL Matching engine execution time (tiered waterfall matching)
        gl_match_time = round(max(0.1, record_count / (self.baseline_throughput * 0.8)), 3)

        total_sec = round(parse_time + gate_time + rule_time + anomaly_triage + gl_match_time, 2)

        # Effective throughput in records per second
        effective_throughput = round(record_count / max(0.5, total_sec), 1)

        # Calculate expected ETA timestamp
        eta_dt = datetime.utcnow() + timedelta(seconds=total_sec)
        eta_str = eta_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        # SLA Status Evaluation
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
            sla_status=sla_status
        )

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
            "total_estimated_seconds": estimate.total_estimated_seconds,
            "sla_target_seconds": estimate.sla_target_seconds,
            "sla_consumed_pct": round(
                estimate.total_estimated_seconds / max(1.0, estimate.sla_target_seconds) * 100, 2
            ),
            "sla_status": estimate.sla_status,
            "eta_timestamp": estimate.eta_timestamp,
            "actual_duration_seconds": estimate.actual_duration_seconds or "",
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)
        return out_path

    def record_actual_run(self, estimate: TimeEstimate, actual_seconds: float):
        estimate.actual_duration_seconds = round(actual_seconds, 2)
        estimate.completed_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        self.historical_runs.append({
            "batch_id": estimate.batch_id,
            "records": estimate.total_records,
            "estimated_sec": estimate.total_estimated_seconds,
            "actual_sec": actual_seconds,
            "error_pct": round(abs(estimate.total_estimated_seconds - actual_seconds) / max(0.1, actual_seconds) * 100, 1),
            "completed_at": estimate.completed_at
        })


time_estimator_service = TimeEstimatorService()

