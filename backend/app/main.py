from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from datetime import datetime, timezone

from app.api import configs, dashboard, graders, providers, runs
from app.core.config import settings
from app.models.schemas import EvalStatus
from app.services.seed import ensure_sample_configs
from app.services.store import run_store


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_sample_configs()
    # Mark interrupted in-flight runs after process restart / reload.
    for run in run_store.list():
        if run.status in {EvalStatus.pending, EvalStatus.running}:
            run.status = EvalStatus.failed
            run.finished_at = datetime.now(timezone.utc)
            run.error = run.error or "Run interrupted because the backend restarted."
            run_store.save(run)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(configs.router, prefix=settings.api_prefix)
app.include_router(graders.router, prefix=settings.api_prefix)
app.include_router(providers.router, prefix=settings.api_prefix)
app.include_router(runs.router, prefix=settings.api_prefix)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
