from fastapi import APIRouter
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/guarantees", tags=["Guarantees - D2"])


@router.get("")
async def get_guarantees():
    """Get all guarantees (Modul D2 - Monitoring Jaminan)"""
    return success_response(data=[], message="Guarantees fetched")


@router.get("/{id}")
async def get_guarantee_by_id(id: str):
    return success_response(data=None, message=f"Guarantee {id} fetched")


@router.post("")
async def add_guarantee():
    """Add a new guarantee"""
    return success_response(data=None, message="Guarantee added", code=201)


@router.patch("/{id}")
async def update_guarantee(id: str):
    """Update guarantee details (e.g. extend expiry)"""
    return success_response(data=None, message=f"Guarantee {id} updated")
