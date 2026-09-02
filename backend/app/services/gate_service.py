"""
Structural Gate service adapter.
Wraps 'Rule Engine/structural_gate.py' without altering original functionality.
"""
import os
import sys
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
from fastapi import HTTPException

from app.config import settings
from app.models.gate import CheckDetail, GateResultSchema, GateSummaryResponse

RULE_ENGINE_DIR = str(settings.project_root / "Rule Engine")
if RULE_ENGINE_DIR not in sys.path:
    sys.path.insert(0, RULE_ENGINE_DIR)

import structural_gate  # type: ignore


class GateService:
    @staticmethod
    def check_batch(
        batch_filename: str,
        declared_record_count: Optional[int] = None,
        declared_control_total: Optional[float] = None,
        expected_encoding: str = "utf-8",
    ) -> GateResultSchema:
        batch_path = settings.batches_dir / batch_filename
        if not batch_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Batch file '{batch_filename}' not found in {settings.batches_dir}"
            )

        # Lookup from manifest if counts not explicitly provided
        if declared_record_count is None or declared_control_total is None:
            if settings.manifest_path.exists():
                manifest_df = pd.read_csv(settings.manifest_path, dtype=str, keep_default_na=False)
                rc, ct = structural_gate.declared_counts_from_manifest(manifest_df, batch_filename)
                if declared_record_count is None:
                    declared_record_count = rc
                if declared_control_total is None:
                    declared_control_total = ct

        result = structural_gate.run_gate(
            str(batch_path),
            declared_record_count=declared_record_count,
            declared_control_total=declared_control_total,
            expected_encoding=expected_encoding,
        )

        checks_dict: Dict[str, CheckDetail] = {
            name: CheckDetail(passed=ok, detail=msg)
            for name, (ok, msg) in result.checks.items()
        }

        return GateResultSchema(
            file=result.file,
            passed=result.passed,
            checks=checks_dict,
            reasons=result.reasons,
        )

    @staticmethod
    def check_all(
        batches_dir: Optional[str] = None,
        manifest_path: Optional[str] = None,
        quarantine_dir: Optional[str] = None,
    ) -> GateSummaryResponse:
        resolved_batches = Path(batches_dir) if batches_dir else settings.batches_dir
        resolved_manifest = Path(manifest_path) if manifest_path else settings.manifest_path
        resolved_quarantine = Path(quarantine_dir) if quarantine_dir else settings.quarantine_dir

        if not resolved_batches.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Batches directory not found: {resolved_batches}"
            )
        if not resolved_manifest.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Manifest file not found: {resolved_manifest}"
            )

        resolved_quarantine.mkdir(parents=True, exist_ok=True)

        results = structural_gate.run_all(
            str(resolved_batches),
            str(resolved_manifest),
            str(resolved_quarantine),
        )

        schema_results = []
        for r in results:
            checks_dict = {
                name: CheckDetail(passed=ok, detail=msg)
                for name, (ok, msg) in r.checks.items()
            }
            schema_results.append(
                GateResultSchema(
                    file=r.file,
                    passed=r.passed,
                    checks=checks_dict,
                    reasons=r.reasons,
                )
            )

        passed_count = sum(1 for r in schema_results if r.passed)
        failed_count = len(schema_results) - passed_count

        return GateSummaryResponse(
            total_batches=len(schema_results),
            passed_count=passed_count,
            failed_count=failed_count,
            quarantined_count=failed_count,
            quarantine_dir=str(resolved_quarantine),
            results=schema_results,
        )


gate_service = GateService()

