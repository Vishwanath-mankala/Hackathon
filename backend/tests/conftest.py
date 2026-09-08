"""
Test isolation for the run-history knowledge base.

The pipeline singleton is built when `app.main` is imported, and its
constructor backfills the run history from whatever SLA artefacts are on disk.
Left alone, the suite would write dozens of 1–2 row test batches into the
developer's real `data/forecasts/run_history.csv` and drag the calibration
towards its clamp floor. So before any test module imports the app, point the
history and the SLA artefact directory at a scratch location.
"""
import tempfile
from pathlib import Path

import pytest

from app.config import settings
from app.services.run_history_service import run_history_service

_SCRATCH = Path(tempfile.mkdtemp(prefix="recon-tests-"))
settings.sla_metrics_dir = _SCRATCH / "sla_metrics"
settings.forecast_dir = _SCRATCH / "forecasts"
settings.sla_metrics_dir.mkdir(parents=True, exist_ok=True)
settings.forecast_dir.mkdir(parents=True, exist_ok=True)
run_history_service.configure(settings.forecast_dir)


@pytest.fixture(autouse=True)
def _fresh_history():
    """Every test starts with an empty history and uncalibrated estimator."""
    from app.services.time_estimator_service import time_estimator_service

    run_history_service.reset()
    time_estimator_service.reset_calibration()
    yield
