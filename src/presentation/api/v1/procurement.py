from fastapi import APIRouter
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/procurement", tags=["Procurement - D3"])


@router.get("")
async def get_all_requests():
    """Get all procurement requests (Modul D3 - Kanban)"""
    # TODO: inject use case
    return success_response(data=[], message="Procurement requests fetched")


@router.get("/{id}")
async def get_request_by_id(id: str):
    """Get a single procurement request by ID"""
    # TODO: inject use case
    return success_response(data=None, message=f"Request {id} fetched")


@router.post("")
async def create_request():
    """Create a new procurement request"""
    # TODO: inject use case
    return success_response(data=None, message="Procurement request created", code=201)


@router.patch("/{id}/stage")
async def move_request_stage(id: str):
    """Move procurement to next stage (Persiapan → Sourcing → ...)"""
    # TODO: inject use case
    return success_response(data=None, message=f"Request {id} stage updated")


@router.patch("/{id}/step")
async def move_request_step(id: str):
    """Move procurement to a specific step within current stage"""
    # TODO: inject use case
    return success_response(data=None, message=f"Request {id} step updated")


@router.patch("/{id}/operational-status")
async def update_operational_status(id: str):
    """Update operational status (On Going / On Hold / Batal)"""
    # TODO: inject use case
    return success_response(data=None, message=f"Request {id} operational status updated")
