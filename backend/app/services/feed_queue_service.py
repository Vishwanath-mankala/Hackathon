"""
Sample-feed queue — the source of "Pull next" for the demo.

The 65 statement batches under File-Gen Scripts/OutPut/ingestion_batches/ are
produced offline by split_recon_feed.py from the single source file and listed
in its manifest.csv. This service keeps that manifest in the database as a queue
with one status per file, so the position survives a restart (uvicorn --reload
used to reset an in-memory set and re-ingest ingest_batch_0001.csv every time).

States:
  PENDING   waiting to be pulled
  INGESTED  became a batch (gate quarantine counts — the file was consumed)
  FAILED    ingest_file raised before a batch existed; blind pulls skip it,
            an explicit filename= pull retries it
  MISSING   listed in the manifest but not on disk; flips back to PENDING when
            the file appears

Only the queue's status is authoritative; batch rows live in the batches table.
"""
import csv
import sqlite3
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app import db
from app.config import settings

logger = logging.getLogger(__name__)

COLUMNS = (
    "sequence", "file", "row_count", "declared_record_count", "declared_control_total",
    "min_booking_date", "max_booking_date", "status", "batch_id", "ingested_at", "error",
)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row(r: sqlite3.Row) -> Dict[str, Any]:
    return {c: r[c] for c in COLUMNS}


class FeedQueueService:
    # ------------------------------------------------------------------
    # Manifest sync
    # ------------------------------------------------------------------
    def sync_from_manifest(self, reset: bool = False) -> int:
        """
        Loads manifest rows not yet in the queue as PENDING (existing rows keep
        their status), then reconciles PENDING/MISSING against the files on
        disk. With reset=True the queue is rebuilt from scratch so a re-split
        with a different batch size is picked up. Returns the number of rows
        the queue now holds.
        """
        manifest = settings.manifest_path
        rows: List[Dict[str, Any]] = []
        if manifest.exists():
            try:
                with open(manifest, newline="", encoding="utf-8-sig") as f:
                    rows = [r for r in csv.DictReader(f) if (r.get("file") or "").strip()]
            except Exception as e:
                logger.error(f"Could not read feed manifest {manifest}: {e}")
        else:
            logger.info(f"No feed manifest at {manifest}; the sample-feed queue is empty.")

        with db.tx() as cx:
            if reset:
                cx.execute("DELETE FROM feed_queue")
            for r in rows:
                seq = _num(r.get("sequence"))
                if seq is None:
                    continue
                cx.execute(
                    """INSERT OR IGNORE INTO feed_queue
                       (sequence, file, row_count, declared_record_count, declared_control_total,
                        min_booking_date, max_booking_date, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                    (
                        int(seq), r["file"].strip(),
                        int(_num(r.get("row_count")) or 0),
                        int(_num(r.get("declared_record_count")) or 0) if _num(r.get("declared_record_count")) is not None else None,
                        _num(r.get("declared_control_total")),
                        r.get("min_booking_date") or None, r.get("max_booking_date") or None,
                    ),
                )
            for q in cx.execute("SELECT sequence, file, status FROM feed_queue").fetchall():
                present = (settings.batches_dir / q["file"]).exists()
                if q["status"] == "PENDING" and not present:
                    cx.execute("UPDATE feed_queue SET status='MISSING' WHERE sequence=?", (q["sequence"],))
                elif q["status"] == "MISSING" and present:
                    cx.execute("UPDATE feed_queue SET status='PENDING' WHERE sequence=?", (q["sequence"],))
            total = cx.execute("SELECT COUNT(*) FROM feed_queue").fetchone()[0]
        return int(total)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def next_pending(self) -> Optional[Dict[str, Any]]:
        with db.read() as cx:
            r = cx.execute(
                "SELECT * FROM feed_queue WHERE status='PENDING' ORDER BY sequence LIMIT 1"
            ).fetchone()
        return _row(r) if r else None

    def get(self, file: str) -> Optional[Dict[str, Any]]:
        with db.read() as cx:
            r = cx.execute("SELECT * FROM feed_queue WHERE file=?", (file,)).fetchone()
        return _row(r) if r else None

    def status(self) -> Dict[str, Any]:
        with db.read() as cx:
            counts = {s: 0 for s in ("PENDING", "INGESTED", "FAILED", "MISSING")}
            for r in cx.execute("SELECT status, COUNT(*) AS n FROM feed_queue GROUP BY status"):
                counts[r["status"]] = r["n"]
            nxt = cx.execute(
                "SELECT sequence, file, row_count FROM feed_queue WHERE status='PENDING' ORDER BY sequence LIMIT 1"
            ).fetchone()
            recent = cx.execute(
                "SELECT * FROM feed_queue WHERE status!='PENDING' ORDER BY ingested_at DESC, sequence DESC LIMIT 10"
            ).fetchall()
        return {
            "pending": counts["PENDING"],
            "ingested": counts["INGESTED"],
            "failed": counts["FAILED"],
            "missing": counts["MISSING"],
            "total": sum(counts.values()),
            "next": {"sequence": nxt["sequence"], "file": nxt["file"], "row_count": nxt["row_count"]} if nxt else None,
            "recent": [_row(r) for r in recent],
            "manifest": str(settings.manifest_path),
        }

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    @staticmethod
    def mark_ingested(cx: sqlite3.Connection, sequence: int, batch_id: str) -> None:
        """Called inside the same transaction as the batch's first checkpoint."""
        cx.execute(
            "UPDATE feed_queue SET status='INGESTED', batch_id=?, ingested_at=?, error=NULL WHERE sequence=?",
            (batch_id, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"), sequence),
        )

    def mark_failed(self, sequence: int, error: str) -> None:
        with db.tx() as cx:
            cx.execute(
                "UPDATE feed_queue SET status='FAILED', error=? WHERE sequence=?",
                (error[:500], sequence),
            )

    def requeue(self, sequence: int) -> None:
        with db.tx() as cx:
            cx.execute(
                "UPDATE feed_queue SET status='PENDING', batch_id=NULL, ingested_at=NULL, error=NULL WHERE sequence=?",
                (sequence,),
            )


feed_queue_service = FeedQueueService()
