from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import DashboardStats, EvalStatus
from app.services.store import config_store, run_store

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats() -> DashboardStats:
    configs = config_store.list()
    runs = run_store.list()
    succeeded = [r for r in runs if r.status == EvalStatus.succeeded]
    failed = [r for r in runs if r.status == EvalStatus.failed]
    avg_pass_rate = (
        round(sum(r.pass_rate for r in succeeded) / len(succeeded), 2) if succeeded else 0.0
    )
    return DashboardStats(
        config_count=len(configs),
        run_count=len(runs),
        succeeded_count=len(succeeded),
        failed_count=len(failed),
        avg_pass_rate=avg_pass_rate,
        recent_runs=runs[:8],
    )
