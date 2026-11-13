from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.models.schemas import EvalRunDetail, EvalRunRequest, EvalRunSummary
from app.services.promptfoo_runner import promptfoo_runner
from app.services.report_builder import build_report_view, results_to_csv
from app.services.store import config_store, run_store

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[EvalRunSummary])
def list_runs() -> list[EvalRunSummary]:
    return run_store.list()


@router.post("", response_model=EvalRunSummary)
async def create_run(payload: EvalRunRequest) -> EvalRunSummary:
    try:
        config = config_store.get(payload.config_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    summary = run_store.create(
        config_id=config.id,
        config_name=config.name,
        description=payload.description or config.description,
    )
    try:
        promptfoo_runner.start(
            run_id=summary.id,
            config_id=config.id,
            max_concurrency=payload.max_concurrency,
            cache=payload.cache,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return summary


@router.get("/{run_id}", response_model=EvalRunDetail)
def get_run(run_id: str) -> EvalRunDetail:
    try:
        summary = run_store.get(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run_dir = run_store.run_dir(run_id)
    stdout = ""
    stderr = ""
    if (run_dir / "stdout.log").exists():
        stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    if (run_dir / "stderr.log").exists():
        stderr = (run_dir / "stderr.log").read_text(encoding="utf-8")

    results = run_store.load_results(run_id)
    return EvalRunDetail(
        **summary.model_dump(),
        results=results,
        report_html_url=f"/api/runs/{run_id}/report.html" if run_store.html_path(run_id).exists() else None,
        report_json_url=f"/api/runs/{run_id}/report.json" if run_store.results_path(run_id).exists() else None,
        stdout=stdout,
        stderr=stderr,
    )


@router.get("/{run_id}/report")
def get_report_view(run_id: str) -> dict:
    try:
        run_store.get(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    results = run_store.load_results(run_id)
    return build_report_view(results)


@router.get("/{run_id}/report.json")
def download_json(run_id: str) -> Response:
    path = run_store.results_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="JSON report not found")
    return FileResponse(path, media_type="application/json", filename=f"evalkit-{run_id}.json")


@router.get("/{run_id}/report.html")
def download_html(run_id: str) -> Response:
    path = run_store.html_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="HTML report not found")
    # Inline display so "HTML" opens the official promptfoo report in-browser.
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename=f"evalkit-{run_id}.html",
        content_disposition_type="inline",
    )


@router.get("/{run_id}/report.csv")
def download_csv(run_id: str) -> Response:
    try:
        run_store.get(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    results = run_store.load_results(run_id)
    csv_text = results_to_csv(results)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="evalkit-{run_id}.csv"'},
    )
