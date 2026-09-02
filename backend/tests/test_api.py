"""
Smoke tests for the Reconciliation & Feed Processing API.
"""
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure backend directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app

client = TestClient(app)


def test_health_and_root():
    # Test Root
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "endpoints" in res_root.json()

    # Test Health
    res_health = client.get("/health")
    assert res_health.status_code == 200
    data = res_health.json()
    assert data["status"] == "healthy"
    print("[PASS] Health & Root tests passed")


def test_feed_manifest_and_batches():
    # Test Batches list
    res_batches = client.get("/api/feed/batches")
    assert res_batches.status_code == 200
    data_batches = res_batches.json()
    assert "files" in data_batches
    print(f"[PASS] Batches list passed ({data_batches['count']} batches found)")

    # Test Manifest
    res_manifest = client.get("/api/feed/manifest")
    assert res_manifest.status_code == 200
    data_manifest = res_manifest.json()
    assert data_manifest["total_batches"] > 0
    print(f"[PASS] Manifest passed ({data_manifest['total_batches']} manifest records)")


def test_structural_gate():
    # Test Gate for single batch
    res_gate = client.post(
        "/api/gate/check-batch",
        json={"batch_filename": "ingest_batch_0001.csv"}
    )
    assert res_gate.status_code == 200
    data_gate = res_gate.json()
    assert "checks" in data_gate
    print(f"[PASS] Structural gate single check passed (passed={data_gate['passed']})")


def test_diagnostics():
    # Test Ambiguity diagnosis
    res_diag = client.post(
        "/api/diagnostics/ambiguity",
        json={}
    )
    assert res_diag.status_code == 200
    data_diag = res_diag.json()
    assert "total_ambiguous" in data_diag
    print(f"[PASS] Ambiguity diagnosis passed ({data_diag['total_ambiguous']} cases analyzed)")


def test_recon_queries():
    # Test querying matched records
    res_matches = client.get("/api/recon/matches?page=1&page_size=5")
    assert res_matches.status_code == 200
    data_matches = res_matches.json()
    assert "items" in data_matches
    print(f"[PASS] Matched transactions query passed ({data_matches['total']} total records)")


def test_chaos_and_recon():
    # Test chaos corruption on batch 65
    res_corrupt = client.post(
        "/api/diagnostics/corrupt-batch",
        json={"batch_filename": "ingest_batch_0065.csv", "mode": "truncate"}
    )
    assert res_corrupt.status_code == 200
    print("[PASS] Chaos corruption injected successfully")

    # Structural gate should detect failure
    res_gate_fail = client.post(
        "/api/gate/check-batch",
        json={"batch_filename": "ingest_batch_0065.csv"}
    )
    assert res_gate_fail.status_code == 200
    assert res_gate_fail.json()["passed"] is False
    print("[PASS] Structural gate caught the corrupted batch")

    # Restore batch
    res_restore = client.post(
        "/api/diagnostics/restore-batch",
        json={"batch_filename": "ingest_batch_0065.csv"}
    )
    assert res_restore.status_code == 200
    print("[PASS] Batch restored from backup")

    # Gate should pass now
    res_gate_ok = client.post(
        "/api/gate/check-batch",
        json={"batch_filename": "ingest_batch_0065.csv"}
    )
    assert res_gate_ok.status_code == 200
    assert res_gate_ok.json()["passed"] is True
    print("[PASS] Structural gate verified restored batch")

    # Test single-batch reconciliation run
    res_recon = client.post(
        "/api/recon/run",
        json={
            "single_batch": "ingest_batch_0001.csv",
            "config": {
                "date_tolerance_days": 3,
                "amount_abs_tolerance": 1.0,
                "direction_mode": "ignore"
            }
        }
    )
    assert res_recon.status_code == 200
    data_recon = res_recon.json()
    assert data_recon["total_matched"] > 0
    print(f"[PASS] Single batch recon run completed ({data_recon['total_matched']} matched)")


if __name__ == "__main__":
    test_health_and_root()
    test_feed_manifest_and_batches()
    test_structural_gate()
    test_diagnostics()
    test_recon_queries()
    test_chaos_and_recon()
    print("\nALL SMOKE TESTS COMPLETED SUCCESSFULLY!")
