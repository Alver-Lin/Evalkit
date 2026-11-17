from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import GraderCreate, GraderMeta, GraderUpdate
from app.services.store import grader_store

router = APIRouter(prefix="/graders", tags=["graders"])


@router.get("", response_model=list[GraderMeta])
def list_graders() -> list[GraderMeta]:
    return grader_store.list()


@router.post("", response_model=GraderMeta)
def create_grader(payload: GraderCreate) -> GraderMeta:
    try:
        return grader_store.create(
            kind=payload.kind,
            name=payload.name,
            description=payload.description,
            provider_id=payload.provider_id,
            api_key=payload.api_key,
            api_host=payload.api_host,
            organization=payload.organization,
            enable_thinking=payload.enable_thinking,
            max_tokens=payload.max_tokens,
            http_method=payload.http_method,
            timeout_sec=payload.timeout_sec,
            headers=payload.headers,
            transform_response=payload.transform_response,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{grader_id}", response_model=GraderMeta)
def get_grader(grader_id: str) -> GraderMeta:
    try:
        return grader_store.get(grader_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{grader_id}", response_model=GraderMeta)
def update_grader(grader_id: str, payload: GraderUpdate) -> GraderMeta:
    try:
        return grader_store.update(
            grader_id,
            kind=payload.kind,
            name=payload.name,
            description=payload.description,
            provider_id=payload.provider_id,
            api_key=payload.api_key,
            api_host=payload.api_host,
            organization=payload.organization,
            enable_thinking=payload.enable_thinking,
            max_tokens=payload.max_tokens,
            http_method=payload.http_method,
            timeout_sec=payload.timeout_sec,
            headers=payload.headers,
            transform_response=payload.transform_response,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{grader_id}")
def delete_grader(grader_id: str) -> dict[str, str]:
    try:
        grader_store.delete(grader_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}
