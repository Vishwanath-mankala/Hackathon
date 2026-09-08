"""
Durable state and the sample-feed queue.

Covers the bug that motivated the database — "Pull next" re-ingesting the
first sample file after every reload — and the guarantees that come with it:
a second orchestrator built on the same database sees the same batches, the
GL cache minus what they consumed, a parked batch it can still resolve, and a
feed that continues where the last process left off.
"""
import csv
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.pipeline_orchestrator import pipeline_orchestrator, PipelineOrchestrator
from app.services.run_history_service import run_history_service
from app.services.feed_queue_service import feed_queue_service
from app.services import agentic_anomaly_service as agent_module

client = TestClient(app)

HEADER = "external_txn_id,account,currency,amount,debit_credit,booking_date,value_date,reference,narrative\n"
CLEAN_ROW = "TXN-{n},ACC#00001,USD,{amt}.00,DR,2023-04-10,2023-04-10,REF-{n},row {n}\n"
ZERO_ROW = "TXN-Z{n},ACC#00001,USD,0.00,CR,2023-04-11,2023-04-11,REF-Z{n},zero amount\n"


def _upload(rows: str, name: str = "stmt.csv", **form):
    files = {"file": (name, (HEADER + rows).encode("utf-8"), "text/csv")}
    res = client.post("/api/pipeline/ingest", files=files, data=form or None)
    assert res.status_code == 200, res.text
    return res.json()


def _clean_rows(n: int, start: int = 1) -> str:
    return "".join(CLEAN_ROW.format(n=i, amt=100 + i) for i in range(start, start + n))


@pytest.fixture
def sample_feed(tmp_path, monkeypatch):
    """Three small sample files plus a manifest, loaded into the queue."""
    feed_dir = tmp_path / "ingestion_batches"
    feed_dir.mkdir()
    manifest_rows = []
    for seq in (1, 2, 3):
        rows = _clean_rows(5, start=seq * 10)
        (feed_dir / f"ingest_batch_{seq:04d}.csv").write_text(HEADER + rows)
        total = sum(100 + i for i in range(seq * 10, seq * 10 + 5))
        manifest_rows.append({
            "sequence": seq, "file": f"ingest_batch_{seq:04d}.csv", "row_count": 5,
            "declared_record_count": 5, "declared_control_total": f"{total:.2f}",
            "min_booking_date": "2023-04-10", "max_booking_date": "2023-04-10",
        })
    manifest = feed_dir / "manifest.csv"
    with open(manifest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)

    monkeypatch.setattr(settings, "batches_dir", feed_dir)
    monkeypatch.setattr(settings, "manifest_path", manifest)
    pipeline_orchestrator.sync_feed_queue(reset=True)
    yield feed_dir, manifest
    pipeline_orchestrator.sync_feed_queue(reset=True)


# ---------------------------------------------------------------------------
# Restart survival
# ---------------------------------------------------------------------------
def test_state_survives_restart():
    res = _upload(_clean_rows(3))
    bid = res["batch_id"]
    original = pipeline_orchestrator.batches[bid]
    assert original.stage in ("RECONCILED", "PUBLISHED")
    full_cache = len(pipeline_orchestrator._recon_engine.cache) + original.matched_count

    o2 = PipelineOrchestrator()
    assert bid in o2.batches
    restored = o2.batches[bid]
    assert restored.stage == original.stage
    assert restored.gl_summary == original.gl_summary
    assert restored.time_estimate.calibration_source == original.time_estimate.calibration_source
    assert o2.batch_match_results[bid] == pipeline_orchestrator.batch_match_results[bid]
    assert bid in o2._reconciled_batches
    assert len(o2._recon_engine.cache) == full_cache - original.matched_count
    assert o2.batch_anomalies[bid] == pipeline_orchestrator.batch_anomalies[bid]
    # Publish events come back too.
    from app.services.publish_service import publish_service
    assert any(e.batch_id == bid for e in publish_service.get_events())


def test_parked_batch_survives_restart_with_queue_wait():
    res = _upload(_clean_rows(2) + ZERO_ROW.format(n=1))
    bid = res["batch_id"]
    assert res["stage"] == "ESCALATED_FOR_REVIEW"
    assert pipeline_orchestrator._frame_path(bid).exists(), "working frame must be pickled while parked"

    time.sleep(0.3)
    o2 = PipelineOrchestrator()
    assert o2._is_parked(bid)
    assert o2._clock_read(bid)[1] >= 0.3
    assert bid not in o2.batch_dfs, "frame is loaded lazily, not at startup"

    escalated = [a for a in o2.batch_anomalies[bid] if a.status == "ESCALATED"]
    assert escalated
    for item in escalated:
        o2.resolve_escalation(bid, item.id, "QUARANTINE", analyst_notes="after restart")

    batch = o2.batches[bid]
    assert batch.stage in ("RECONCILED", "PUBLISHED")
    assert batch.queue_wait_seconds >= 0.3
    assert not o2._frame_path(bid).exists()
    rows = [r for r in run_history_service.rows(500) if r["batch_id"] == bid]
    assert len(rows) == 1 and rows[0]["outcome"] == "ESCALATED_RESOLVED"

    # And a third process sees the resolved state, not the parked one.
    o3 = PipelineOrchestrator()
    assert o3.batches[bid].stage == batch.stage
    assert not o3._is_parked(bid)


def test_interrupted_batch_is_marked_not_dropped():
    res = _upload(_clean_rows(2))
    bid = res["batch_id"]
    # Simulate a process dying mid-pipeline: persist a mid-pipeline stage.
    pipeline_orchestrator.batches[bid].stage = "GATE_PASSED"
    pipeline_orchestrator._checkpoint(bid)

    o2 = PipelineOrchestrator()
    assert o2.batches[bid].stage == "INTERRUPTED"
    assert "restarted" in (o2.batches[bid].failure_reason or "").lower()
    o3 = PipelineOrchestrator()
    assert o3.batches[bid].stage == "INTERRUPTED", "the mark itself must be persisted"


# ---------------------------------------------------------------------------
# Sample-feed queue
# ---------------------------------------------------------------------------
def test_feed_walks_in_order_across_restarts(sample_feed):
    b1, origin, remaining = pipeline_orchestrator.pull_next_sftp_drop()
    assert origin == "SAMPLE_FEED" and b1.filename == "ingest_batch_0001.csv" and remaining == 2
    assert b1.source == "SAMPLE_FEED"

    o2 = PipelineOrchestrator()
    b2, _, remaining = o2.pull_next_sftp_drop()
    assert b2.filename == "ingest_batch_0002.csv" and remaining == 1

    o3 = PipelineOrchestrator()
    b3, _, remaining = o3.pull_next_sftp_drop()
    assert b3.filename == "ingest_batch_0003.csv" and remaining == 0

    with pytest.raises(FileNotFoundError, match="exhausted"):
        o3.pull_next_sftp_drop()

    status = feed_queue_service.status()
    assert status["ingested"] == 3 and status["pending"] == 0 and status["next"] is None
    assert len({b1.batch_id, b2.batch_id, b3.batch_id}) == 3
    assert {r["batch_id"] for r in status["recent"]} == {b1.batch_id, b2.batch_id, b3.batch_id}

    # Both processes' batches are in the third one's registry.
    assert {b1.batch_id, b2.batch_id, b3.batch_id} <= set(o3.batches)


def test_feed_endpoint_reports_position_and_remaining(sample_feed):
    res = client.post("/api/pipeline/simulate-sftp")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["queue_remaining"] == 2
    assert "Feed batch 1 of 3" in body["message"]
    assert body["stage"] in ("RECONCILED", "PUBLISHED")

    q = client.get("/api/pipeline/feed/queue").json()
    assert q["pending"] == 2 and q["next"]["file"] == "ingest_batch_0002.csv"

    # Re-pulling an ingested file by name is a conflict, not a duplicate.
    again = client.post("/api/pipeline/simulate-sftp", params={"filename": "ingest_batch_0001.csv"})
    assert again.status_code == 409
    assert body["batch_id"] in again.json()["detail"]


def test_manifest_declared_values_reach_the_gate(sample_feed):
    feed_dir, manifest = sample_feed
    rows = list(csv.DictReader(open(manifest, newline="")))
    rows[0]["declared_record_count"] = "99"
    with open(manifest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    pipeline_orchestrator.sync_feed_queue(reset=True)

    batch, _, _ = pipeline_orchestrator.pull_next_sftp_drop()
    assert batch.stage == "GATE_QUARANTINED"
    assert batch.gate_details.declared_record_count == 99
    assert feed_queue_service.get("ingest_batch_0001.csv")["status"] == "INGESTED"


def test_failed_ingest_is_skipped_then_retryable(sample_feed):
    feed_dir, _ = sample_feed
    bad = feed_dir / "ingest_batch_0001.csv"
    bad.write_bytes(b"\xff\xfe\x00 not a csv \x00")
    # An unreadable file makes ingest_file raise before any batch exists.
    import pandas as pd
    original = pd.read_csv

    def broken_read_csv(path, *a, **k):
        if str(path).endswith("ingest_batch_0001.csv"):
            raise ValueError("unreadable sample")
        return original(path, *a, **k)

    import app.services.ingestion_service as ing
    ing.pd.read_csv = broken_read_csv
    try:
        with pytest.raises(Exception):
            pipeline_orchestrator.pull_next_sftp_drop()
        row = feed_queue_service.get("ingest_batch_0001.csv")
        assert row["status"] == "FAILED" and "unreadable" in (row["error"] or "")

        # A blind pull moves on to the next file rather than looping on the bad one.
        b2, _, _ = pipeline_orchestrator.pull_next_sftp_drop()
        assert b2.filename == "ingest_batch_0002.csv"
    finally:
        ing.pd.read_csv = original

    # Fixed on disk: an explicit pull retries the FAILED row.
    bad.write_text(HEADER + _clean_rows(5, start=10))
    b1, _, _ = pipeline_orchestrator.pull_next_sftp_drop(filename="ingest_batch_0001.csv")
    assert b1.filename == "ingest_batch_0001.csv"
    assert feed_queue_service.get("ingest_batch_0001.csv")["status"] == "INGESTED"


def test_reset_requeues_and_clears_but_keeps_history(sample_feed):
    pipeline_orchestrator.pull_next_sftp_drop()
    pipeline_orchestrator.pull_next_sftp_drop()
    history_before = run_history_service.stats()["total_runs_recorded"]
    assert history_before >= 2
    full_cache = len(pipeline_orchestrator._recon_engine.cache) + sum(
        b.matched_count for b in pipeline_orchestrator.batches.values()
    )

    res = client.post("/api/pipeline/feed/reset")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["batches_cleared"] == 2
    assert body["queue"]["pending"] == 3 and body["queue"]["ingested"] == 0
    assert body["run_history_rows_kept"] == history_before
    assert body["gl_cache_rows"] == full_cache

    assert client.get("/api/pipeline/overview").json()["total_batches"] == 0
    assert run_history_service.stats()["total_runs_recorded"] == history_before
    assert PipelineOrchestrator().batches == {}


def test_concurrent_pulls_are_serialised(sample_feed):
    results, errors = [], []

    def pull():
        try:
            results.append(pipeline_orchestrator.pull_next_sftp_drop()[0])
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=pull) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert {b.filename for b in results} == {"ingest_batch_0001.csv", "ingest_batch_0002.csv"}
    matched = [
        {m["external_txn_id"] for m in pipeline_orchestrator.batch_match_results[b.batch_id]["matched"]}
        for b in results
    ]
    assert not (matched[0] & matched[1]), "each batch must own only its own matches"


# ---------------------------------------------------------------------------
# Run history in the database
# ---------------------------------------------------------------------------
def test_run_history_round_trips_through_the_table():
    res = _upload(_clean_rows(2))
    bid = res["batch_id"]
    before = run_history_service.get(bid)
    assert before and before["machine_seconds"] > 0

    run_history_service._rows.clear()
    run_history_service._loaded = False
    after = run_history_service.get(bid)
    assert after == before
    assert isinstance(after["machine_seconds"], float)


def test_legacy_csv_is_imported_once():
    from app.services.run_history_service import CSV_COLUMNS
    run_history_service.reset()
    path = run_history_service.path
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerow({"batch_id": "LEGACY-1", "completed_at": "2026-09-01 00:00:00 UTC", "outcome": "RECONCILED",
                    "provenance": "LIVE", "gate_passed": "true", "record_count": "500", "machine_seconds": "0.9",
                    "wall_seconds": "0.9", "estimate_final_sec": "0.8", "eligible_for_calibration": "true"})
    try:
        run_history_service._rows.clear()
        run_history_service._loaded = False
        assert run_history_service.get("LEGACY-1")["record_count"] == 500.0

        # Now in the table; a second cold load must not re-import or duplicate.
        run_history_service._rows.clear()
        run_history_service._loaded = False
        assert run_history_service.stats()["total_runs_recorded"] == 1
    finally:
        path.unlink(missing_ok=True)


def test_run_history_download_renders_csv():
    _upload(_clean_rows(2))
    res = client.get("/api/pipeline/run-history/file")
    assert res.status_code == 200
    assert b"batch_id" in res.content and b"machine_seconds" in res.content


# ---------------------------------------------------------------------------
# Daemon-thread checkpoint
# ---------------------------------------------------------------------------
def test_agent_submit_thread_checkpoint_does_not_deadlock(monkeypatch):
    bridge = agent_module.agentic_anomaly_service.agent_bridge
    monkeypatch.setattr(bridge, "is_enabled", lambda: True)
    monkeypatch.setattr(settings, "crewai_agent_anomaly_id", "424242")
    monkeypatch.setattr(
        bridge, "submit_batch_to_agent",
        lambda file_path, agent_id=None, extra_files=None: {
            "success": True, "job_id": 1, "agent_execution_id": "exec-thread", "message": "ok",
            "http_status": "OK", "submitted_at": "now", "target_file": Path(file_path).name,
            "bundled_files": [Path(file_path).name], "agent_id": agent_id,
        },
    )
    monkeypatch.setattr(bridge, "get_agent_execution_output", lambda eid: {"success": False, "message": "not yet"})

    res = _upload("TXN-1,ACC#00001,usd,100.00,D,10/04/2023,10/04/2023,REF-1,anomalous\n")
    bid = res["batch_id"]
    for t in threading.enumerate():
        if t.name.startswith("agent-STAGE_4_ANOMALY"):
            t.join(timeout=5)
            assert not t.is_alive(), "submit thread hung — checkpoint under the lock deadlocked"

    o2 = PipelineOrchestrator()
    assert o2.batches[bid].agent_executions["STAGE_4_ANOMALY"].status == "SUBMITTED"
