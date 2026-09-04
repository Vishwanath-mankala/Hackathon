"""
Unit & Integration Tests for the End-to-End Batch Pipeline:
Structural Gate, Agentic Anomalies, Human Escalation, GL Matching, Time Estimation, Publishing.
"""
import pytest
from fastapi.testclient import TestClient
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
