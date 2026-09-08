"""
Unit & Integration Tests for the End-to-End Batch Pipeline:
Structural Gate, Agentic Anomalies, Human Escalation, GL Matching, Time Estimation, Publishing.
"""
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.main import app

client = TestClient(app)


def test_pipeline_overview():
    """Verify overview returns telemetry and batch summary."""
    res = client.get("/api/pipeline/overview")
    assert res.status_code == 200
    data = res.json()
    assert "total_batches" in data
    assert "batches" in data
    assert isinstance(data["batches"], list)


def test_list_batches():
    """Verify listing batches with stage filters."""
    res = client.get("/api/pipeline/batches")
    assert res.status_code == 200
    batches = res.json()
    assert isinstance(batches, list)
    if batches:
        b0 = batches[0]
        assert "batch_id" in b0
        assert "stage" in b0
        assert "total_records" in b0


def test_ingest_valid_statement():
    """Verify end-to-end processing of a valid bank statement."""
    csv_content = (
        "external_txn_id,account,currency,amount,debit_credit,booking_date,value_date,reference,narrative\n"
        "TXN-001,ACC#00001,USD,1000.00,DR,2023-04-10,2023-04-10,INV-9901,Vendor settlement payment\n"
        "TXN-002,ACC#00001,USD,250.50,CR,2023-04-11,2023-04-11,DEP-1200,Client wire deposit\n"
    )

    files = {"file": ("valid_bank_stmt.csv", csv_content.encode("utf-8"), "text/csv")}
    data = {
        "source": "UPLOAD",
        "declared_record_count": 2,
        "declared_control_total": 1250.50
    }

    res = client.post("/api/pipeline/ingest", files=files, data=data)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["gate_passed"] is True
    assert res_data["quarantined"] is False
    assert res_data["record_count"] == 2
    batch_id = res_data["batch_id"]

    # Verify time estimate was created
    est_res = client.get(f"/api/pipeline/batches/{batch_id}/estimator")
    assert est_res.status_code == 200
    est = est_res.json()
    assert est["total_records"] == 2
    assert est["sla_status"] in ["ON_TRACK", "AT_RISK", "BREACHED"]


def test_structural_gate_quarantine_on_corrupt_count():
    """Verify that a trailer count mismatch causes immediate structural gate failure and quarantine."""
    csv_content = (
        "external_txn_id,account,currency,amount,debit_credit,booking_date,value_date,reference,narrative\n"
        "TXN-001,ACC#00001,USD,1000.00,DR,2023-04-10,2023-04-10,REF-1,Note\n"
    )

    # Declare 5 records when actual is 1
    files = {"file": ("tampered_count_stmt.csv", csv_content.encode("utf-8"), "text/csv")}
    data = {
        "source": "SFTP",
        "declared_record_count": 5,
        "declared_control_total": 1000.00
    }

    res = client.post("/api/pipeline/ingest", files=files, data=data)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["gate_passed"] is False
    assert res_data["quarantined"] is True
    assert res_data["stage"] == "GATE_QUARANTINED"

    batch_id = res_data["batch_id"]
    gate_res = client.get(f"/api/pipeline/batches/{batch_id}/gate")
    assert gate_res.status_code == 200
    gate = gate_res.json()
    assert gate["passed"] is False
    assert gate["quarantined"] is True
    assert len(gate["reasons"]) > 0


def test_agentic_anomaly_detection_and_auto_remediation():
    """Verify detection of safe auto-remediable anomalies and escalated human items."""
    csv_content = (
        "external_txn_id,account,currency,amount,debit_credit,booking_date,value_date,reference,narrative\n"
        "TXN-101,ACC#00001,usd,500.00,D,15/04/2023,15/04/2023,REF-AUTO,Auto-remediable line\n"
        "TXN-102,ACC#99999,USD,0.00,CR,2023-04-15,2023-04-15,REF-ESC,Zero amount line\n"
    )

    files = {"file": ("anomalous_batch.csv", csv_content.encode("utf-8"), "text/csv")}
    data = {
        "source": "UPLOAD",
        "declared_record_count": 2,
        "declared_control_total": 500.00
    }

    res = client.post("/api/pipeline/ingest", files=files, data=data)
    assert res.status_code == 200
    batch_id = res.json()["batch_id"]

    # Check anomalies list
    ano_res = client.get(f"/api/pipeline/batches/{batch_id}/anomalies")
    assert ano_res.status_code == 200
    anomalies = ano_res.json()
    assert len(anomalies) > 0

    # Verify auto-remediation occurred
    auto_remeds = [a for a in anomalies if a["status"] == "AUTO_REMEDIATED"]
    assert len(auto_remeds) > 0

    # Verify escalation occurred
    escalated = [a for a in anomalies if a["status"] == "ESCALATED"]
    assert len(escalated) > 0

    # Resolve escalation as human analyst
    target = escalated[0]
    resolve_res = client.post(
        f"/api/pipeline/batches/{batch_id}/anomalies/{target['id']}/resolve",
        json={"action": "QUARANTINE", "analyst_notes": "Line quarantined due to zero value"}
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["quarantined_rows_count"] >= 1


def test_publish_batch_results():
    """Verify publishing batch results to downstream message bus."""
    # List existing batches
    res = client.get("/api/pipeline/batches")
    batches = res.json()
    if batches:
        batch_id = batches[0]["batch_id"]
        pub_res = client.post(f"/api/pipeline/batches/{batch_id}/publish")
        assert pub_res.status_code == 200
        event = pub_res.json()
        assert event["batch_id"] == batch_id
        assert event["delivered"] is True

        # Check published events stream
        stream_res = client.get("/api/pipeline/publish/events")
        assert stream_res.status_code == 200
        events = stream_res.json()
        assert any(e["batch_id"] == batch_id for e in events)


def test_file_downloads_and_agent_integration():
    """Verify batch file download, anomaly candidate CSV generation, and agent status endpoints."""
    csv_content = (
        "external_txn_id,account,currency,amount,debit_credit,booking_date,value_date,reference,narrative\n"
        "TXN-201,ACC#00001,usd,150.00,D,10/05/2023,10/05/2023,REF-201,Timing and Semantic line\n"
        "TXN-202,UNKNOWN_ACC,USD,250.00,CR,2023-05-10,2023-05-10,REF-202,Referential line\n"
    )
    files = {"file": ("integration_test_batch.csv", csv_content.encode("utf-8"), "text/csv")}
    res = client.post("/api/pipeline/ingest", files=files)
    assert res.status_code == 200
    batch_id = res.json()["batch_id"]

    # 1. Download original batch file
    file_res = client.get(f"/api/pipeline/batches/{batch_id}/file")
    assert file_res.status_code == 200
    assert "text/csv" in file_res.headers.get("content-type", "")

    # 2. Download anomaly candidate file generated by Stage 3 rule engine
    ano_file_res = client.get(f"/api/pipeline/batches/{batch_id}/anomalies/file")
    assert ano_file_res.status_code == 200
    assert "text/csv" in ano_file_res.headers.get("content-type", "")
    assert b"error_type" in ano_file_res.content

    # 3. Stage 6/7 artefacts are exported for the downstream agents
    for kind in ("statement", "anomaly_candidates", "sla_metrics"):
        art_res = client.get(f"/api/pipeline/batches/{batch_id}/artifacts/{kind}")
        assert art_res.status_code == 200, f"artefact '{kind}' was not produced"
        assert "text/csv" in art_res.headers.get("content-type", "")

    # 4. Agent status reports the automatic per-stage dispatch log
    status_res = client.get(f"/api/pipeline/batches/{batch_id}/agent/status")
    assert status_res.status_code == 200
    status_json = status_res.json()
    assert status_json["artifacts"]["anomaly_candidates"] is True

    executions = status_json["executions"]
    # Stage 4 fires automatically off the candidates file the rule engine wrote.
    assert "STAGE_4_ANOMALY" in executions
    stage_4 = executions["STAGE_4_ANOMALY"]
    assert stage_4["trigger"] == "AUTOMATIC"
    # The agent ID comes from the environment; there is no built-in default.
    configured_id = settings.crewai_agent_anomaly_id
    assert stage_4["agent_id"] == (str(configured_id) if configured_id else None)
    # SUBMITTED/SUBMITTING when the platform is reachable and an ID is set,
    # SKIPPED when the stage has no agent ID configured.
    assert stage_4["status"] in {"SUBMITTING", "SUBMITTED", "FAILED", "SKIPPED"}
    if not configured_id:
        assert stage_4["status"] == "SKIPPED"
        assert "CREWAI_AGENT_ANOMALY_ID" in (stage_4["message"] or "")

    # 5. Global agent health
    global_agent = client.get("/api/pipeline/agent/status")
    assert global_agent.status_code == 200

    # 6. Manual re-dispatch of a stage's agent
    classify_res = client.post(
        f"/api/pipeline/batches/{batch_id}/agent/classify",
        params={"stage_key": "STAGE_4_ANOMALY"},
    )

    if not configured_id:
        # Without an agent ID this is a configuration problem, not a server
        # fault, and the response has to name the variable to set.
        assert classify_res.status_code == 400
        assert "CREWAI_AGENT_ANOMALY_ID" in classify_res.json()["detail"]
        res_json = {}
    else:
        assert classify_res.status_code == 200
        res_json = classify_res.json()
        assert res_json["trigger"] == "MANUAL"
        assert res_json["stage"] == "STAGE_4_ANOMALY"

    # 7. Poll the platform for outputs on every in-flight execution
    output_res = client.get(f"/api/pipeline/batches/{batch_id}/agent/output")
    assert output_res.status_code == 200
    assert "STAGE_4_ANOMALY" in output_res.json()

    exec_id = res_json.get("agent_execution_id")
    if exec_id:
        single_exec = client.get(f"/api/pipeline/agent/execution/{exec_id}")
        assert single_exec.status_code == 200
        assert single_exec.json().get("executionId") == exec_id






def test_analyst_signoff_audit_trail():
    """
    Stage 6 ambiguous ties need a human decision. Verify the sign-off is
    validated, persisted, and append-only (a revision supersedes rather than
    overwrites).
    """
    from app.services.pipeline_orchestrator import pipeline_orchestrator

    def find_tie():
        for batch in pipeline_orchestrator.batches.values():
            ties = (pipeline_orchestrator.batch_match_results.get(batch.batch_id) or {}).get("ambiguous") or []
            if ties:
                return batch.batch_id, ties[0]
        return None

    # Nothing is seeded at startup, so pull real statements through the pipeline
    # until one produces an ambiguous tie to sign off on.
    target = find_tie()
    for _ in range(5):
        if target:
            break
        res = client.post("/api/pipeline/simulate-sftp")
        if res.status_code != 200:
            break
        target = find_tie()

    if target is None:
        pytest.skip("No batch produced an ambiguous tie to sign off on.")

    batch_id, tie = target
    row_key = str(tie["ingest_external_txn_id"])
    candidates = [str(c) for c in tie["candidate_internal_txn_ids"]]

    def sign(payload, dataset="ambiguous"):
        return client.post(f"/api/pipeline/batches/{batch_id}/recon/{dataset}/signoff", json=payload)

    # A GL entry that never competed for this line must be rejected — settling
    # against it would hide two errors instead of surfacing one.
    bad = sign({
        "row_key": row_key,
        "action": "SELECT_ALTERNATIVE",
        "chosen_internal_txn_id": "NOT-A-CANDIDATE-999",
    })
    assert bad.status_code == 400
    assert "not a candidate" in bad.json()["detail"].lower()

    # SELECT_ALTERNATIVE without a target is rejected.
    assert sign({"row_key": row_key, "action": "SELECT_ALTERNATIVE"}).status_code == 400

    # An attestation action is not valid for an ambiguous tie.
    assert sign({"row_key": row_key, "action": "ATTEST_REVIEWED"}).status_code == 400

    # An unknown tie is a 404.
    assert sign({"row_key": "NO-SUCH-TXN", "action": "LEAVE_UNSETTLED"}).status_code == 404

    # Confirming the engine's provisional pick.
    first = sign({
        "row_key": row_key,
        "action": "CONFIRM_PROVISIONAL",
        "analyst": "test.analyst",
        "analyst_notes": "reference tokens agree",
    })
    assert first.status_code == 200
    first_json = first.json()
    assert first_json["chosen_internal_txn_id"] == str(tie["chosen_internal_txn_id"])
    assert first_json["supersedes"] is None

    # Revising the call supersedes it; the original record survives.
    second = sign({
        "row_key": row_key,
        "action": "SELECT_ALTERNATIVE",
        "chosen_internal_txn_id": candidates[-1],
        "analyst": "test.analyst",
        "analyst_notes": "narrative matches the later candidate",
    })
    assert second.status_code == 200
    assert second.json()["supersedes"] == first_json["signoff_id"]
    assert second.json()["chosen_internal_txn_id"] == candidates[-1]

    trail = client.get(f"/api/pipeline/batches/{batch_id}/signoffs").json()
    trail_for_row = [s for s in trail if s["row_key"] == row_key]
    assert len(trail_for_row) >= 2, "the superseded decision must still be in the trail"

    effective = client.get(
        f"/api/pipeline/batches/{batch_id}/signoffs",
        params={"effective_only": True},
    ).json()
    standing = [s for s in effective if s["row_key"] == row_key]
    assert len(standing) == 1
    assert standing[0]["signoff_id"] == second.json()["signoff_id"]

    # The trail is downloadable as CSV evidence.
    csv_res = client.get(f"/api/pipeline/batches/{batch_id}/signoffs/file")
    assert csv_res.status_code == 200
    assert b"signoff_id" in csv_res.content
