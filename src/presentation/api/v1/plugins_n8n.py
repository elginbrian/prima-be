"""
PRIMA n8n Plugin Router (/api/v1/plugins/n8n)
Manages multi-webhook n8n configuration, event catalog, test triggers, and delivery logs.
"""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.response_wrapper import success_response
from src.infrastructure.database import get_db
from src.infrastructure.integrations import (
    N8N_EVENTS_CATALOG,
    n8n_webhook_service,
)
from src.presentation.auth_dependencies import (
    ROLE_MANAGER,
    ROLE_SUPER_ADMIN,
    get_current_user,
    require_roles,
)

router = APIRouter(prefix="/plugins/n8n", tags=["Plugins - n8n Automation"])


class N8nGlobalUpdateDto(BaseModel):
    enabled: bool = Field(default=True)


class WebhookEndpointCreateDto(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    url: str = Field(..., min_length=1)
    enabled: bool = Field(default=True)
    events: List[str] = Field(default_factory=lambda: ["*"])
    auth_type: str = Field(default="hmac_and_header")
    secret: Optional[str] = Field(default=None)
    custom_header_name: str = Field(default="X-N8N-Secret", max_length=80)
    include_presigned_urls: bool = Field(default=True)


class WebhookEndpointUpdateDto(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None)
    enabled: Optional[bool] = Field(default=None)
    events: Optional[List[str]] = Field(default=None)
    auth_type: Optional[str] = Field(default=None)
    secret: Optional[str] = Field(default=None)
    clear_secret: bool = Field(default=False)
    custom_header_name: Optional[str] = Field(default=None, max_length=80)
    include_presigned_urls: Optional[bool] = Field(default=None)


class WebhookAdHocTestDto(BaseModel):
    url: str = Field(..., min_length=1)
    auth_type: str = Field(default="hmac_and_header")
    secret: str = Field(default="")
    custom_header_name: str = Field(default="X-N8N-Secret")


def _build_overview_payload() -> dict:
    overview = n8n_webhook_service.get_masked_overview()
    return {
        **overview,
        "events_catalog": N8N_EVENTS_CATALOG,
        "inbound_endpoints": {
            "tools_execute_url": "/api/v1/integrations/tools/execute",
            "evaluate_sla_url": "/api/v1/deadlines/evaluate-sla",
            "evaluate_guarantees_url": "/api/v1/guarantees/evaluate-expiry",
            "token_generate_url": "/api/v1/integrations/token",
        },
    }


@router.get(
    "",
    summary="Get n8n plugin multi-webhook configuration, event catalog, and delivery logs",
    dependencies=[Depends(get_current_user)],
)
async def get_n8n_plugin_overview(db: AsyncSession = Depends(get_db)):
    await n8n_webhook_service.load_from_db(db)
    return success_response(
        data=_build_overview_payload(),
        message="Konfigurasi plugin n8n berhasil dimuat",
    )


@router.put(
    "",
    summary="Toggle global n8n plugin dispatch",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def update_n8n_global_settings(
    payload: N8nGlobalUpdateDto,
    db: AsyncSession = Depends(get_db),
):
    await n8n_webhook_service.load_from_db(db)
    await n8n_webhook_service.set_global_enabled(db, payload.enabled)
    return success_response(
        data=_build_overview_payload(),
        message="Status global plugin n8n berhasil diperbarui",
    )


@router.post(
    "/webhooks",
    status_code=201,
    summary="Create a new n8n webhook destination",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def create_n8n_webhook(
    payload: WebhookEndpointCreateDto,
    db: AsyncSession = Depends(get_db),
):
    await n8n_webhook_service.load_from_db(db)
    try:
        res = await n8n_webhook_service.create_webhook(
            db,
            name=payload.name,
            url=payload.url,
            description=payload.description,
            enabled=payload.enabled,
            events=payload.events,
            auth_type=payload.auth_type,
            secret=payload.secret,
            custom_header_name=payload.custom_header_name,
            include_presigned_urls=payload.include_presigned_urls,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return success_response(
        data={
            **_build_overview_payload(),
            "created_id": res["created_id"],
            "plain_secret_once": res["plain_secret_once"],
        },
        message=f"Webhook n8n '{payload.name}' berhasil ditambahkan",
        code=201,
    )


@router.put(
    "/webhooks/{webhook_id}",
    summary="Update an existing n8n webhook destination",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def update_n8n_webhook(
    webhook_id: str,
    payload: WebhookEndpointUpdateDto,
    db: AsyncSession = Depends(get_db),
):
    await n8n_webhook_service.load_from_db(db)
    try:
        await n8n_webhook_service.update_webhook(
            db,
            webhook_id,
            name=payload.name,
            url=payload.url,
            description=payload.description,
            enabled=payload.enabled,
            events=payload.events,
            auth_type=payload.auth_type,
            secret=payload.secret,
            clear_secret=payload.clear_secret,
            custom_header_name=payload.custom_header_name,
            include_presigned_urls=payload.include_presigned_urls,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return success_response(
        data=_build_overview_payload(),
        message="Konfigurasi webhook n8n berhasil diperbarui",
    )


@router.delete(
    "/webhooks/{webhook_id}",
    summary="Delete an n8n webhook destination",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def delete_n8n_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
):
    await n8n_webhook_service.load_from_db(db)
    try:
        await n8n_webhook_service.delete_webhook(db, webhook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return success_response(
        data=_build_overview_payload(),
        message="Webhook n8n berhasil dihapus",
    )


@router.post(
    "/webhooks/{webhook_id}/test",
    summary="Send a prima.webhook_test payload to a saved n8n webhook",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def test_saved_n8n_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
):
    await n8n_webhook_service.load_from_db(db)
    try:
        result = await n8n_webhook_service.test_webhook_by_id(db, webhook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return success_response(
        data={"delivery": result, "overview": _build_overview_payload()},
        message=(
            "Test webhook berhasil diterima n8n"
            if result.get("ok")
            else f"Test webhook gagal: {result.get('error') or result.get('status_code')}"
        ),
    )


@router.post(
    "/test-url",
    summary="Test an arbitrary n8n webhook URL before saving",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def test_adhoc_n8n_url(payload: WebhookAdHocTestDto):
    try:
        result = await n8n_webhook_service.test_ad_hoc_url(
            url=payload.url,
            auth_type=payload.auth_type,
            secret=payload.secret,
            custom_header_name=payload.custom_header_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return success_response(
        data={"delivery": result},
        message=(
            "Test URL webhook berhasil diterima n8n"
            if result.get("ok")
            else f"Test URL webhook gagal: {result.get('error') or result.get('status_code')}"
        ),
    )


@router.delete(
    "/logs",
    summary="Clear n8n webhook delivery logs",
    dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_MANAGER))],
)
async def clear_n8n_delivery_logs(db: AsyncSession = Depends(get_db)):
    await n8n_webhook_service.load_from_db(db)
    await n8n_webhook_service.clear_delivery_logs(db)
    return success_response(
        data=_build_overview_payload(),
        message="Riwayat pengiriman webhook berhasil dibersihkan",
    )
