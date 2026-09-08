"""
Processing-time forecast, run-history knowledge base and estimator calibration.

Covers the two bugs that motivated the feature — analyst queue wait was never
measured, and a test suite of 2-row batches could poison calibration — and the
forecast round trip: bundle contents, dispatch bookkeeping, tolerant parsing,
and reconciling a prediction that arrives before or after the run row.
"""
import csv
import io
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.pipeline_models import BatchRecord, BatchForecast
from app.services.run_history_service import run_history_service, FORECAST_INPUT_COLUMNS
from app.services.time_estimator_service import (
    time_estimator_service,
    DEFAULT_BASELINE_THROUGHPUT,
    THROUGHPUT_CLAMP,
)
from app.services.pipeline_orchestrator import pipeline_orchestrator, PipelineOrchestrator
from app.services import agentic_anomaly_service as agent_module

client = TestClient(app)

HEADER = "external_txn_id,account,currency,amount,debit_credit,booking_date,value_date,reference,narrative\n"


def _ingest(rows: str, name: str = "stmt.csv", **form):
    files = {"file": (name, (HEADER + rows).encode("utf-8"), "text/csv")}
    res = client.post("/api/pipeline/ingest", files=files, data=form or None)
    assert res.status_code == 200, res.text
    return res.json()


def _synthetic_run(batch_id: str, records: int, machine_seconds: float, outcome: str = "RECONCILED",
                   escalated: int = 0, queue_wait: float = 0.0):
    """Writes one history row as if a batch of `records` rows took `machine_seconds`."""
    est = time_estimator_service.estimate_processing_time(
        batch_id=batch_id, file_size_bytes=records * 120, record_count=records,
        anomaly_count=0, escalated_count=escalated,
    )
    batch = BatchRecord(
        batch_id=batch_id, filename=f"{batch_id}.csv", file_size_bytes=records * 120,
        total_records=records, valid_records_count=records, gate_passed=True,
        escalated_count=escalated, created_at="2026-09-08 10:00:00 UTC",
        updated_at="2026-09-08 10:00:00 UTC", time_estimate=est,
    )
    return run_history_service.record_run(
        batch, machine_seconds, queue_wait, machine_seconds + queue_wait, outcome
    )


# ---------------------------------------------------------------------------
# Timing: the stopwatch measures analyst queue wait
# ---------------------------------------------------------------------------
def test_escalation_queue_wait_is_measured():
    """
    Regression for the fresh-clock bug: a batch parked at the analyst queue used
    to record ~0.01s because the resolve path restarted the clock. The wait is
    the actual SLA cost, and it must land in exactly one history row.
    """
    res = _ingest(
        "TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n"
        "TXN-2,ACC#00001,USD,0.00,CR,2023-04-11,2023-04-11,REF-2,zero amount\n"
    )
    batch_id = res["batch_id"]
    assert res["stage"] == "ESCALATED_FOR_REVIEW"

    parked = run_history_service.get(batch_id)
    assert parked and parked["outcome"] == "ESCALATED_PENDING"

    time.sleep(0.35)

    escalated = [a for a in client.get(f"/api/pipeline/batches/{batch_id}/anomalies").json()
                 if a["status"] == "ESCALATED"]
    for item in escalated:
        r = client.post(f"/api/pipeline/batches/{batch_id}/anomalies/{item['id']}/resolve",
                        json={"action": "QUARANTINE", "analyst_notes": "test"})
        assert r.status_code == 200, r.text

    batch = client.get(f"/api/pipeline/batches/{batch_id}").json()
    assert batch["stage"] in ("RECONCILED", "PUBLISHED")
    assert batch["queue_wait_seconds"] >= 0.30, batch["queue_wait_seconds"]
    assert batch["wall_seconds"] >= batch["machine_seconds"] + batch["queue_wait_seconds"] - 0.01

    rows = [r for r in run_history_service.rows(limit=500) if r["batch_id"] == batch_id]
    assert len(rows) == 1, "parked + released must upsert one row, not append two"
    assert rows[0]["outcome"] == "ESCALATED_RESOLVED"
    assert rows[0]["queue_wait_seconds"] >= 0.30
    assert rows[0]["escalated_count"] >= 1, "the queued count must survive resolution"


def test_run_history_row_written_for_clean_batch():
    res = _ingest("TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n")
    row = run_history_service.get(res["batch_id"])
    assert row is not None
    assert row["outcome"] in ("RECONCILED", "PUBLISHED")
    assert row["machine_seconds"] > 0
    assert row["queue_wait_seconds"] == 0
    assert row["wall_seconds"] >= row["machine_seconds"]
    assert row["estimate_at_ingest_sec"] is not None
    assert row["provenance"] == "LIVE"
    # Durable: a cold reload from the database returns the same row.
    run_history_service._rows.clear()
    run_history_service._loaded = False
    assert run_history_service.get(res["batch_id"]) == row


def test_quarantined_batch_recorded_but_excluded_from_calibration():
    res = _ingest(
        "TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n",
        declared_record_count=5, declared_control_total=100.0,
    )
    assert res["stage"] == "GATE_QUARANTINED"
    row = run_history_service.get(res["batch_id"])
    assert row and row["outcome"] == "GATE_QUARANTINED"
    assert row["eligible_for_calibration"] is False
    assert all(r["batch_id"] != res["batch_id"] for r in run_history_service.calibration_sample())


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
def test_calibration_ignores_tiny_runs():
    """Twenty 2-row batches carry no throughput signal and must leave the defaults alone."""
    for i in range(20):
        _synthetic_run(f"TINY-{i}", records=2, machine_seconds=0.01)
    est = time_estimator_service.estimate_processing_time("probe", 1000, 500)
    assert est.calibration_source == "DEFAULT"
    assert est.baseline_throughput_used == DEFAULT_BASELINE_THROUGHPUT
    assert est.calibration_sample_size == 0


def test_calibration_derives_throughput_from_history():
    """10 × 500-record runs at 0.96s machine time → ~1183 rec/s, not the 1450 default."""
    for i in range(10):
        _synthetic_run(f"REAL-{i}", records=500, machine_seconds=0.96)
    est = time_estimator_service.estimate_processing_time("probe", 60000, 500)
    assert est.calibration_source == "HISTORY"
    assert est.calibration_sample_size == 10
    assert 1100 < est.baseline_throughput_used < 1300, est.baseline_throughput_used
    # A slower measured throughput means a longer estimate than the default gave.
    time_estimator_service.reset_calibration()
    run_history_service.reset()
    default_est = time_estimator_service.estimate_processing_time("probe", 60000, 500)
    assert est.estimated_machine_seconds > default_est.estimated_machine_seconds


def test_calibration_is_clamped():
    """Six runs that stalled for 100s each would imply ~10 rec/s; the floor holds."""
    for i in range(6):
        _synthetic_run(f"STALL-{i}", records=500, machine_seconds=100.0)
    est = time_estimator_service.estimate_processing_time("probe", 1, 500)
    assert est.calibration_source == "HISTORY"
    assert est.baseline_throughput_used == THROUGHPUT_CLAMP[0]


def test_calibration_derives_queue_wait_from_resolved_batches():
    for i in range(5):
        _synthetic_run(f"BASE-{i}", records=500, machine_seconds=0.96)
    for i in range(3):
        _synthetic_run(f"ESC-{i}", records=500, machine_seconds=0.96,
                       outcome="ESCALATED_RESOLVED", escalated=2, queue_wait=60.0)
    est = time_estimator_service.estimate_processing_time("probe", 60000, 500, anomaly_count=2, escalated_count=1)
    assert est.estimated_queue_wait_sec == pytest.approx(30.0)


def test_backfill_carries_calibration_only_until_live_runs_exist():
    """
    Old SLA artefacts seed the history (real runs, older clock). They calibrate
    the estimator on a young deployment, and step aside once enough runs have
    been measured with the current stopwatch.
    """
    header = ("batch_id,total_records,file_size_mb,anomaly_count,escalated_count,matched_count,unmatched_count,"
              "ambiguous_count,throughput_records_per_sec,estimated_parse_time_sec,estimated_gate_time_sec,"
              "estimated_rule_time_sec,estimated_anomaly_triage_sec,estimated_gl_match_sec,total_estimated_seconds,"
              "sla_target_seconds,sla_consumed_pct,sla_status,eta_timestamp,actual_duration_seconds\n")
    for i in range(8):
        # 500 rows in 4.0s: a slow old regime (≈250 rec/s).
        (settings.sla_metrics_dir / f"OLD-{i}_sla_metrics.csv").write_text(
            header + f"OLD-{i},500,0.06,0,0,480,20,0,600,0.1,0.05,0.23,0.0,0.43,0.81,900.0,0.09,ON_TRACK,x,4.0\n"
        )
    # Earlier tests may have left their own (tiny, ineligible) SLA artefacts in
    # the scratch directory; only the eight OLD-* rows matter here.
    added = run_history_service.backfill_from_sla_metrics()
    assert added >= 8
    assert run_history_service.backfill_from_sla_metrics() == 0, "backfill must be idempotent"
    for i in range(8):
        assert run_history_service.get(f"OLD-{i}")["provenance"] == "BACKFILL_SLA_METRICS"

    est = time_estimator_service.estimate_processing_time("probe", 60000, 500)
    assert est.calibration_source == "HISTORY"
    assert est.baseline_throughput_used < 400, "young deployment calibrates from the backfill"

    # Five live runs at the current machine's real speed take over.
    for i in range(5):
        _synthetic_run(f"LIVE-{i}", records=500, machine_seconds=0.96)
    est = time_estimator_service.estimate_processing_time("probe", 60000, 500)
    assert est.calibration_sample_size == 5
    assert 1100 < est.baseline_throughput_used < 1300, est.baseline_throughput_used


def test_estimator_exposes_calibration_provenance():
    res = _ingest("TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n")
    est = client.get(f"/api/pipeline/batches/{res['batch_id']}/estimator").json()
    for key in ("calibration_source", "calibration_sample_size", "estimated_queue_wait_sec",
                "estimated_machine_seconds", "baseline_throughput_used"):
        assert key in est
    assert est["calibration_source"] == "DEFAULT"

    history = client.get("/api/pipeline/run-history").json()
    assert history["calibration"]["source"] == "DEFAULT"
    assert history["calibration"]["min_runs_required"] == settings.calibration_min_runs
    assert any(r["batch_id"] == res["batch_id"] for r in history["rows"])


# ---------------------------------------------------------------------------
# Forecast bundle & dispatch
# ---------------------------------------------------------------------------
def test_forecast_input_leaks_no_post_ingest_features():
    """The forecast is blind by design: nothing from Stage 3 onwards may be in its input."""
    res = _ingest(
        "TXN-1,ACC#00001,usd,100.00,D,10/04/2023,10/04/2023,REF-1,anomalous\n"
        "TXN-2,ACC#00001,USD,50.00,CR,2023-04-11,2023-04-11,REF-2,fine\n"
    )
    batch = pipeline_orchestrator.batches[res["batch_id"]]
    assert batch.forecast_input_file_path and Path(batch.forecast_input_file_path).exists()
    with open(batch.forecast_input_file_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    header = set(rows[0].keys())
    assert header == set(FORECAST_INPUT_COLUMNS)
    for forbidden in ("anomaly_count", "escalated_count", "matched_count", "est_triage_sec"):
        assert forbidden not in header
    assert rows[0]["record_count"] == "2"

    # The history snapshot exists too (header-only is fine on a cold start).
    assert batch.run_history_file_path and Path(batch.run_history_file_path).exists()
    art = client.get(f"/api/pipeline/batches/{res['batch_id']}/artifacts/run_history")
    assert art.status_code == 200


def test_forecast_agent_dispatch_recorded_at_ingest():
    res = _ingest("TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n")
    batch_id = res["batch_id"]
    executions = client.get(f"/api/pipeline/batches/{batch_id}/agent/status").json()["executions"]
    assert "STAGE_1_FORECAST" in executions
    exec_ = executions["STAGE_1_FORECAST"]
    assert exec_["trigger"] == "AUTOMATIC"

    comparison = client.get(f"/api/pipeline/batches/{batch_id}/forecast")
    assert comparison.status_code == 200, comparison.text
    body = comparison.json()
    assert body["local_estimate"]["batch_id"] == batch_id
    assert body["actual"]["wall_seconds"] > 0
    assert body["calibration"]["source"] in ("DEFAULT", "HISTORY")

    if not settings.crewai_agent_forecast_id:
        assert exec_["status"] == "SKIPPED"
        assert "CREWAI_AGENT_FORECAST_ID" in (exec_["message"] or "")
        assert body["agent_forecast"]["status"] == "SKIPPED"
    else:
        # The ID is set but the suite disables the platform (conftest), so the
        # dispatch is recorded and skipped rather than sent.
        assert exec_["status"] in {"SUBMITTING", "SUBMITTED", "FAILED", "SKIPPED"}
        assert body["agent_forecast"]["status"] in {"PENDING", "FAILED", "RECEIVED", "SKIPPED"}


def test_submit_batch_to_agent_zips_every_member(tmp_path, monkeypatch):
    primary = tmp_path / "B1_forecast_input.csv"
    history = tmp_path / "B1_run_history.csv"
    missing = tmp_path / "does_not_exist.csv"
    primary.write_text("a,b\n1,2\n")
    history.write_text("x\n")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": {"jobId": 7, "agentExecutionId": "exec-1", "message": "ok", "httpStatus": "OK"}}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        captured["files"] = files
        captured["data"] = data
        return FakeResponse()

    monkeypatch.setattr(agent_module.requests, "post", fake_post)
    bridge = agent_module.CrewAIAgentBridge(api_url="https://example.invalid/submit", api_key="k", agent_id="42")

    result = bridge.submit_batch_to_agent(primary, agent_id="42", extra_files=[history, missing, history])
    assert result["success"] is True
    assert result["target_file"] == primary.name
    assert result["bundled_files"] == [primary.name, history.name]

    name, payload, mime = captured["files"]["files"]
    assert name == "B1_forecast_input.zip"
    assert mime == "application/zip"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        assert sorted(zf.namelist()) == sorted([primary.name, history.name])
    assert captured["data"]["agentId"] == "42"


# ---------------------------------------------------------------------------
# Forecast capture & reconciliation with the history row
# ---------------------------------------------------------------------------
def test_forecast_output_parsing_is_defensive():
    parse = PipelineOrchestrator._parse_forecast_output
    good = {"forecast_seconds": 12.5, "p10_seconds": 9, "p90_seconds": "18.2", "confidence": "HIGH",
            "comparable_batches": ["A", 2], "breach_probability_pct": 3}
    assert parse(good)["forecast_seconds"] == 12.5
    assert parse(good)["p90_seconds"] == 18.2
    assert parse(good)["comparable_batches"] == ["A", "2"]
    assert parse('{"forecast_seconds": 4}')["forecast_seconds"] == 4.0
    assert parse('```json\n{"forecast_seconds": 5}\n```')["forecast_seconds"] == 5.0
    assert parse('Here is my answer:\n{"forecast_seconds": 6}\nThanks.')["forecast_seconds"] == 6.0
    assert parse('{"forecast_seconds": "lots"}')["forecast_seconds"] is None
    assert parse("just prose, no json") is None
    assert parse("") is None
    assert parse(None) is None
    assert parse([1, 2]) is None
    assert parse('{"nope": 1') is None


def test_late_forecast_updates_existing_row():
    _synthetic_run("LATE-1", records=500, machine_seconds=1.0)
    forecast = BatchForecast(status="RECEIVED", forecast_seconds=1.25, confidence="MEDIUM", agent_execution_id="e1")
    row = run_history_service.attach_forecast("LATE-1", forecast)
    assert row is not None
    assert row["forecast_seconds"] == 1.25
    assert row["forecast_error_pct"] == pytest.approx(25.0)   # signed: over-estimated by 25%
    assert row["forecast_execution_id"] == "e1"
    assert len([r for r in run_history_service.rows(500) if r["batch_id"] == "LATE-1"]) == 1


def test_forecast_before_run_is_held_and_merged():
    forecast = BatchForecast(status="RECEIVED", forecast_seconds=0.8, agent_execution_id="e2")
    assert run_history_service.attach_forecast("EARLY-1", forecast) is None
    assert run_history_service.get("EARLY-1") is None

    row = _synthetic_run("EARLY-1", records=500, machine_seconds=1.0)
    assert row["forecast_seconds"] == 0.8
    assert row["forecast_error_pct"] == pytest.approx(-20.0)


def test_forecast_against_parked_batch_is_not_scored_until_release():
    _synthetic_run("PARK-1", records=500, machine_seconds=0.5, outcome="ESCALATED_PENDING", escalated=1)
    forecast = BatchForecast(status="RECEIVED", forecast_seconds=30.0, agent_execution_id="e3")
    assert run_history_service.attach_forecast("PARK-1", forecast) is None
    parked = run_history_service.get("PARK-1")
    assert parked["forecast_seconds"] == 30.0 and parked["forecast_error_pct"] is None

    row = _synthetic_run("PARK-1", records=500, machine_seconds=0.5, outcome="ESCALATED_RESOLVED",
                         escalated=1, queue_wait=29.5)
    assert row["forecast_error_pct"] == pytest.approx(0.0)
    assert len([r for r in run_history_service.rows(500) if r["batch_id"] == "PARK-1"]) == 1


def test_capture_forecast_scores_against_completed_batch():
    res = _ingest("TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n")
    batch = pipeline_orchestrator.batches[res["batch_id"]]
    execution = batch.agent_executions["STAGE_1_FORECAST"]
    execution.agent_execution_id = "exec-test"
    execution.status = "SUCCESS"
    execution.output = '{"forecast_seconds": %s, "confidence": "LOW", "reasoning": "history empty"}' % (
        batch.wall_seconds * 2
    )
    pipeline_orchestrator._capture_forecast(batch, execution)

    assert batch.agent_forecast.status == "RECEIVED"
    assert batch.agent_forecast.error_pct == pytest.approx(100.0, abs=0.5)
    assert execution.forecast_captured is True
    row = run_history_service.get(batch.batch_id)
    assert row["forecast_error_pct"] == pytest.approx(100.0, abs=0.5)

    # Idempotent: a second capture does not double-apply anything.
    pipeline_orchestrator._capture_forecast(batch, execution)
    assert run_history_service.get(batch.batch_id)["forecast_seconds"] == batch.agent_forecast.forecast_seconds

    body = client.get(f"/api/pipeline/batches/{batch.batch_id}/forecast").json()
    assert body["agent_forecast"]["status"] == "RECEIVED"
    assert body["agent_forecast"]["error_pct"] == pytest.approx(100.0, abs=0.5)


def test_unparseable_forecast_records_nothing():
    res = _ingest("TXN-1,ACC#00001,USD,100.00,DR,2023-04-10,2023-04-10,REF-1,fine\n")
    batch = pipeline_orchestrator.batches[res["batch_id"]]
    execution = batch.agent_executions["STAGE_1_FORECAST"]
    execution.agent_execution_id = "exec-prose"
    execution.status = "SUCCESS"
    execution.output = "I think it will take about a minute."
    pipeline_orchestrator._capture_forecast(batch, execution)
    assert batch.agent_forecast.status == "UNPARSEABLE"
    assert batch.agent_forecast.forecast_seconds is None
    assert run_history_service.get(batch.batch_id)["forecast_seconds"] is None


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
def test_concurrent_record_run_keeps_every_row():
    errors = []

    def worker(i):
        try:
            _synthetic_run(f"THREAD-{i}", records=500, machine_seconds=0.9 + i / 100)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(run_history_service.rows(limit=500)) == 20
    with open(run_history_service.export_csv(), newline="") as f:
        assert len(list(csv.DictReader(f))) == 20
    run_history_service._rows.clear()
    run_history_service._loaded = False
    assert len(run_history_service.rows(limit=500)) == 20, "every concurrent upsert must reach the table"
