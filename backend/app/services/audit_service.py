"""
Analyst Sign-off & Audit Trail Service.

Stage 6 leaves two things a machine must not decide alone: ambiguous ties, where
several GL rows match one bank line equally well, and reconciling items an analyst
has to attest they have reviewed. This service records those human decisions as an
append-only audit trail.

Append-only is the point. A sign-off is evidence that a named person made a call at
a moment in time; correcting it adds a new record that supersedes the old one, it
never edits or deletes what was written before. The trail is flushed to
`data/batch_results/{batch_id}_signoffs.csv` on every write so it survives a restart
and can be handed to an auditor as-is.
"""
import csv
import uuid
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.models.pipeline_models import AuditSignoff
from app.config import settings

logger = logging.getLogger(__name__)

# Actions valid for an ambiguous multi-candidate tie.
AMBIGUOUS_ACTIONS = {"CONFIRM_PROVISIONAL", "SELECT_ALTERNATIVE", "LEAVE_UNSETTLED"}

# Actions valid for any other reconciliation line the analyst is attesting to.
ATTESTATION_ACTIONS = {"ATTEST_REVIEWED", "FLAG_FOR_INVESTIGATION"}

CSV_COLUMNS = [
    "signoff_id",
    "batch_id",
    "dataset",
    "row_key",
    "action",
    "chosen_internal_txn_id",
    "analyst",
    "analyst_notes",
    "signed_at",
]


class AuditService:
    def __init__(self):
        self._by_batch: Dict[str, List[AuditSignoff]] = {}
        self._loaded: set = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def valid_actions(dataset: str) -> set:
        return AMBIGUOUS_ACTIONS if dataset == "ambiguous" else ATTESTATION_ACTIONS

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _path(self, batch_id: str) -> Path:
        return settings.batch_results_dir / f"{batch_id}_signoffs.csv"

    def _load(self, batch_id: str):
        """Reads any trail already on disk. Runs once per batch per process."""
        if batch_id in self._loaded:
            return
        self._loaded.add(batch_id)

        path = self._path(batch_id)
        if not path.exists():
            return

        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self._by_batch[batch_id] = [
                AuditSignoff(
                    signoff_id=r.get("signoff_id", ""),
                    batch_id=r.get("batch_id", batch_id),
                    dataset=r.get("dataset", ""),
                    row_key=r.get("row_key", ""),
                    action=r.get("action", ""),
                    chosen_internal_txn_id=r.get("chosen_internal_txn_id") or None,
                    analyst=r.get("analyst", ""),
                    analyst_notes=r.get("analyst_notes") or None,
                    signed_at=r.get("signed_at", ""),
                )
                for r in rows
            ]
            logger.info(f"Loaded {len(self._by_batch[batch_id])} sign-offs for {batch_id}.")
        except Exception as e:
            logger.error(f"Could not read sign-off trail for {batch_id}: {e}")

    def _flush(self, batch_id: str):
        """Rewrites the whole trail. The in-memory list is append-only, so this
        never loses a record — it just keeps the file consistent with memory."""
        path = self._path(batch_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                for s in self._by_batch.get(batch_id, []):
                    writer.writerow({
                        "signoff_id": s.signoff_id,
                        "batch_id": s.batch_id,
                        "dataset": s.dataset,
                        "row_key": s.row_key,
                        "action": s.action,
                        "chosen_internal_txn_id": s.chosen_internal_txn_id or "",
                        "analyst": s.analyst,
                        "analyst_notes": s.analyst_notes or "",
                        "signed_at": s.signed_at,
                    })
        except Exception as e:
            logger.error(f"Could not persist sign-off trail for {batch_id}: {e}")

    def signoff_file(self, batch_id: str) -> Optional[Path]:
        path = self._path(batch_id)
        return path if path.exists() else None

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def list_for_batch(self, batch_id: str) -> List[AuditSignoff]:
        """Full history, oldest first — including superseded decisions."""
        with self._lock:
            self._load(batch_id)
            return list(self._by_batch.get(batch_id, []))

    def effective_for_batch(self, batch_id: str) -> Dict[str, AuditSignoff]:
        """
        The decision that currently stands for each row, keyed
        "{dataset}::{row_key}". A later sign-off supersedes an earlier one.
        """
        effective: Dict[str, AuditSignoff] = {}
        for s in self.list_for_batch(batch_id):
            effective[f"{s.dataset}::{s.row_key}"] = s
        return effective

    def history_for_row(self, batch_id: str, dataset: str, row_key: str) -> List[AuditSignoff]:
        return [
            s for s in self.list_for_batch(batch_id)
            if s.dataset == dataset and s.row_key == row_key
        ]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def record(
        self,
        batch_id: str,
        dataset: str,
        row_key: str,
        action: str,
        analyst: str,
        chosen_internal_txn_id: Optional[str] = None,
        analyst_notes: Optional[str] = None,
    ) -> Tuple[AuditSignoff, Optional[AuditSignoff]]:
        """
        Appends a sign-off. Returns (new record, superseded record or None).
        Never mutates an existing record.
        """
        with self._lock:
            self._load(batch_id)

            previous = None
            for s in reversed(self._by_batch.get(batch_id, [])):
                if s.dataset == dataset and s.row_key == row_key:
                    previous = s
                    break

            record = AuditSignoff(
                signoff_id=f"SGN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
                batch_id=batch_id,
                dataset=dataset,
                row_key=row_key,
                action=action,
                chosen_internal_txn_id=chosen_internal_txn_id,
                analyst=analyst,
                analyst_notes=analyst_notes,
                signed_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                supersedes=previous.signoff_id if previous else None,
            )

            self._by_batch.setdefault(batch_id, []).append(record)
            self._flush(batch_id)
            return record, previous


audit_service = AuditService()
