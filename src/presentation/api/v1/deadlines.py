from fastapi import APIRouter
from src.application.dtos.response_wrapper import success_response

router = APIRouter(prefix="/deadlines", tags=["Deadlines - D4 SLA"])


@router.get("")
async def get_deadlines():
    """Get all deadlines/SLA (Modul D4)"""
    return success_response(data=[], message="Deadlines fetched")


@router.get("/{id}")
async def get_deadline_by_id(id: str):
    return success_response(data=None, message=f"Deadline {id} fetched")


@router.post("")
async def add_deadline():
    """Add a new SLA deadline"""
    return success_response(data=None, message="Deadline added", code=201)


@router.patch("/{id}")
async def update_deadline(id: str):
    """Update deadline details or status (On Track / At Risk / Overdue / Selesai)"""
    return success_response(data=None, message=f"Deadline {id} updated")
