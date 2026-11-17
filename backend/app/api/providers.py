from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ProviderProbeRequest, ProviderProbeResponse
from app.services.provider_probe import probe_provider

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("/probe", response_model=ProviderProbeResponse)
async def probe(payload: ProviderProbeRequest) -> ProviderProbeResponse:
    return await probe_provider(payload)
