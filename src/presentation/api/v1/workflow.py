"""
Workflow Stages Router — /api/v1/workflow (Admin Configurable Stages)

Allows admins to view, create, update, reorder, and deactivate procurement workflow stages
per procurement method. Also consumed by all forms/dropdowns across FE & AI extraction.
"""
from typing import Optional
from fastapi import APIRouter, Depends

from src.application.dtos.response_wrapper import success_response
from src.application.dtos.validation_dto import (
    WorkflowStageCreateDto,
    WorkflowStageUpdateDto,
    WorkflowStageReorderDto,
)
from src.application.use_cases.validation_use_cases import ManageWorkflowStagesUseCase
from src.infrastructure.models.user_model import UserModel
from src.presentation.auth_dependencies import get_current_user
from src.presentation.dependencies import get_workflow_stages_uc

router = APIRouter(prefix="/workflow", tags=["Workflow Stages - Admin"])


@router.get("/stages", response_model=dict, summary="List configurable workflow stages")
async def list_workflow_stages(
    procurement_method: Optional[str] = None,
    active_only: bool = True,
    uc: ManageWorkflowStagesUseCase = Depends(get_workflow_stages_uc),
):
    stages = await uc.list_stages(procurement_method=procurement_method, active_only=active_only)
    methods = sorted({s.procurement_method for s in stages}) if stages else []
    return success_response(
        data=[s.model_dump(mode="json") for s in stages],
        message=f"Ditemukan {len(stages)} tahapan pekerjaan pada {len(methods)} metode",
    )


@router.post("/stages", response_model=dict, status_code=201, summary="Create a new workflow stage")
async def create_workflow_stage(
    payload: WorkflowStageCreateDto,
    user: UserModel = Depends(get_current_user),
    uc: ManageWorkflowStagesUseCase = Depends(get_workflow_stages_uc),
):
    created = await uc.create_stage(payload)
    return success_response(
        data=created.model_dump(mode="json"),
        message=f"Tahapan '{created.step_name}' berhasil ditambahkan",
        code=201,
    )


@router.put("/stages/reorder", response_model=dict, summary="Reorder workflow stages within a method")
async def reorder_workflow_stages(
    payload: WorkflowStageReorderDto,
    user: UserModel = Depends(get_current_user),
    uc: ManageWorkflowStagesUseCase = Depends(get_workflow_stages_uc),
):
    updated = await uc.reorder_stages(payload)
    return success_response(
        data=[s.model_dump(mode="json") for s in updated],
        message="Urutan tahapan pekerjaan berhasil diperbarui",
    )


@router.put("/stages/{id}", response_model=dict, summary="Update a workflow stage")
async def update_workflow_stage(
    id: str,
    payload: WorkflowStageUpdateDto,
    user: UserModel = Depends(get_current_user),
    uc: ManageWorkflowStagesUseCase = Depends(get_workflow_stages_uc),
):
    updated = await uc.update_stage(id, payload)
    return success_response(
        data=updated.model_dump(mode="json"),
        message=f"Tahapan '{updated.step_name}' berhasil diperbarui",
    )


@router.delete("/stages/{id}", response_model=dict, summary="Delete/deactivate a workflow stage")
async def delete_workflow_stage(
    id: str,
    user: UserModel = Depends(get_current_user),
    uc: ManageWorkflowStagesUseCase = Depends(get_workflow_stages_uc),
):
    await uc.delete_stage(id)
    return success_response(message="Tahapan pekerjaan berhasil dihapus")
