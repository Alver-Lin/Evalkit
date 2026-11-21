from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    AiExtractRequest,
    AiExtractResponse,
    ProviderProbeRequest,
    ProviderProbeResponse,
)
from app.services.ai_extract import generate_ai_extract_script
from app.services.provider_probe import probe_provider
from app.services.store import grader_store

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("/probe", response_model=ProviderProbeResponse)
async def probe(payload: ProviderProbeRequest) -> ProviderProbeResponse:
    return await probe_provider(payload)


@router.post("/ai-extract", response_model=AiExtractResponse)
async def ai_extract(payload: AiExtractRequest) -> AiExtractResponse:
    try:
        grader = grader_store.get(payload.grader_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await generate_ai_extract_script(payload, grader)
