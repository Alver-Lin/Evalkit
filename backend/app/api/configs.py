from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import ConfigCreate, ConfigMeta, ConfigUpdate
from app.services.store import config_store

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("", response_model=list[ConfigMeta])
def list_configs() -> list[ConfigMeta]:
    return config_store.list()


@router.post("", response_model=ConfigMeta)
def create_config(payload: ConfigCreate) -> ConfigMeta:
    try:
        return config_store.create(payload.name, payload.description, payload.yaml_content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{config_id}", response_model=ConfigMeta)
def get_config(config_id: str) -> ConfigMeta:
    try:
        return config_store.get(config_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{config_id}", response_model=ConfigMeta)
def update_config(config_id: str, payload: ConfigUpdate) -> ConfigMeta:
    try:
        return config_store.update(
            config_id,
            name=payload.name,
            description=payload.description,
            yaml_content=payload.yaml_content,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{config_id}")
def delete_config(config_id: str) -> dict[str, str]:
    try:
        config_store.delete(config_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}
