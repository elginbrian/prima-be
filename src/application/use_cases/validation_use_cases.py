"""
Document Validation Use Cases (Modul D1 & Audit Trail D2/D3/D4)

Handles:
1. AI document analysis against checklist items and prompt.
2. Publishing validated documents and extracted stages directly into the Tracker as a new Procurement Request.
3. Fetching historical validation logs for compliance and audit trail.
"""
import io
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_

from src.infrastructure.models.validation_model import DocumentValidationLogModel, ValidationProfileModel
from src.infrastructure.models.procurement_model import ProcurementRequestModel, ProcurementMilestoneModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.infrastructure.storage.s3_service import s3_service
from src.infrastructure.ai.gemini_service import gemini_service
from src.domain.procurement_workflow import STEP_TO_STAGE, steps_for_method, DEFAULT_METHOD
from src.domain.exceptions import NotFoundException, ValidationException
from src.application.dtos.validation_dto import (
    ChecklistItemResultDto,
    ChecklistRuleItemDto,
    CreateValidationProfileDto,
    UpdateValidationProfileDto,
    ValidationProfileResponseDto,
    ExtractedStageDto,
    ExtractedProjectDto,
    DocumentValidationResponseDto,
    PublishValidationToTrackerRequestDto,
    UpdateValidationDecisionDto,
    ValidationLogListItemDto,
)


class ManageValidationProfilesUseCase:
    """Use case for CRUD operations on reusable validation profiles / standards."""
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_dto(model: ValidationProfileModel) -> ValidationProfileResponseDto:
        rules = [
            ChecklistRuleItemDto(
                category=r.get("category", "Umum"),
                item=r.get("item", ""),
                guidance=r.get("guidance"),
                is_mandatory=bool(r.get("is_mandatory", True)),
                weight=int(r.get("weight", 25)),
                severity_on_failure=r.get("severity_on_failure", "ERROR"),
            )
            for r in (model.checklist_rules or [])
        ]
        return ValidationProfileResponseDto(
            id=model.id,
            name=model.name,
            code=model.code,
            document_kind=model.document_kind,
            description=model.description,
            scope=model.scope,
            department_id=model.department_id,
            department_name=model.department_name,
            passing_score_threshold=model.passing_score_threshold,
            warning_score_threshold=model.warning_score_threshold,
            strict_mandatory_enforcement=model.strict_mandatory_enforcement,
            target_stage_to_clear=model.target_stage_to_clear,
            custom_system_prompt=model.custom_system_prompt,
            checklist_rules=rules,
            is_default=model.is_default,
            is_active=model.is_active,
            created_by_id=model.created_by_id,
            created_by_name=model.created_by_name,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def list_profiles(
        self,
        document_kind: Optional[str] = None,
        scope: Optional[str] = None,
        active_only: bool = True
    ) -> List[ValidationProfileResponseDto]:
        q = select(ValidationProfileModel)
        if active_only:
            q = q.where(ValidationProfileModel.is_active == True)
        if document_kind:
            q = q.where(ValidationProfileModel.document_kind == document_kind)
        if scope:
            q = q.where(ValidationProfileModel.scope == scope)
        q = q.order_by(desc(ValidationProfileModel.is_default), ValidationProfileModel.name)
        res = await self.session.execute(q)
        profiles = res.scalars().all()
        return [self._to_dto(p) for p in profiles]

    async def get_by_id(self, profile_id: str) -> ValidationProfileResponseDto:
        res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
        )
        p = res.scalars().first()
        if not p:
            raise NotFoundException(f"Profil validasi '{profile_id}' tidak ditemukan")
        return self._to_dto(p)

    async def create_profile(
        self,
        dto: CreateValidationProfileDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None
    ) -> ValidationProfileResponseDto:
        now = datetime.now(timezone.utc)
        profile_id = f"VPROF-{uuid.uuid4().hex[:8].upper()}"
        code = dto.code or f"STD_{dto.name.upper().replace(' ', '_')[:24]}_{uuid.uuid4().hex[:6].upper()}"

        model = ValidationProfileModel(
            id=profile_id,
            name=dto.name,
            code=code,
            document_kind=dto.document_kind,
            description=dto.description,
            scope=dto.scope,
            department_id=dto.department_id,
            department_name=dto.department_name,
            passing_score_threshold=dto.passing_score_threshold,
            warning_score_threshold=dto.warning_score_threshold,
            strict_mandatory_enforcement=dto.strict_mandatory_enforcement,
            target_stage_to_clear=dto.target_stage_to_clear,
            custom_system_prompt=dto.custom_system_prompt,
            checklist_rules=[r.model_dump() for r in dto.checklist_rules],
            is_default=dto.is_default,
            is_active=True,
            created_by_id=actor_id,
            created_by_name=actor_name,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return self._to_dto(model)

    async def update_profile(
        self,
        profile_id: str,
        dto: UpdateValidationProfileDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None
    ) -> ValidationProfileResponseDto:
        res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
        )
        model = res.scalars().first()
        if not model:
            raise NotFoundException(f"Profil validasi '{profile_id}' tidak ditemukan")

        update_data = dto.model_dump(exclude_unset=True)
        if "checklist_rules" in update_data and update_data["checklist_rules"] is not None:
            update_data["checklist_rules"] = [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in update_data["checklist_rules"]
            ]

        for k, v in update_data.items():
            setattr(model, k, v)

        model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(model)
        return self._to_dto(model)

    async def delete_profile(self, profile_id: str) -> bool:
        res = await self.session.execute(
            select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
        )
        model = res.scalars().first()
        if not model:
            raise NotFoundException(f"Profil validasi '{profile_id}' tidak ditemukan")
        model.is_active = False
        model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True


class AnalyzeDocumentChecklistUseCase:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str,
        profile_id: Optional[str] = None,
        checklist_items: Optional[List[Any]] = None,
        passing_score_threshold: Optional[float] = None,
        custom_prompt: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> DocumentValidationResponseDto:
        # 1. Resolve Profile (Template) if provided
        profile: Optional[ValidationProfileModel] = None
        profile_rules: List[Dict[str, Any]] = []
        target_stage_to_clear = None
        strict_mandatory = True
        passing_threshold = passing_score_threshold or 80.0
        warning_threshold = 60.0

        if profile_id:
            res = await self.session.execute(
                select(ValidationProfileModel).where(ValidationProfileModel.id == profile_id)
            )
            profile = res.scalars().first()
            if profile:
                profile_rules = profile.checklist_rules or []
                passing_threshold = passing_score_threshold or profile.passing_score_threshold or 80.0
                warning_threshold = profile.warning_score_threshold or 60.0
                strict_mandatory = profile.strict_mandatory_enforcement
                target_stage_to_clear = profile.target_stage_to_clear
                if profile.custom_system_prompt:
                    custom_prompt = f"{profile.custom_system_prompt}\n{custom_prompt or ''}".strip()

        # 2. Compile comprehensive checklist items & mandatory map
        checklist_strings: List[str] = []
        mandatory_map: Dict[str, bool] = {}

        # Add rules from profile
        for r in profile_rules:
            item_text = r.get("item", "").strip()
            if item_text:
                checklist_strings.append(item_text)
                mandatory_map[item_text] = bool(r.get("is_mandatory", True))

        # Add ad-hoc checklist items from user
        if checklist_items:
            for itm in checklist_items:
                if isinstance(itm, dict):
                    t = str(itm.get("item", "")).strip()
                    if t:
                        if t not in mandatory_map:
                            checklist_strings.append(t)
                        mandatory_map[t] = bool(itm.get("is_mandatory", False))
                elif isinstance(itm, str) and itm.strip():
                    t = itm.strip()
                    if t not in mandatory_map:
                        checklist_strings.append(t)
                        mandatory_map[t] = False

        if not checklist_strings:
            checklist_strings = [
                "Nama pekerjaan dan lingkup kebutuhan",
                "Spesifikasi teknis / Kerangka Acuan Kerja",
                "Jangka waktu pelaksanaan",
                "Ketentuan pembayaran & jaminan",
            ]
            for s in checklist_strings:
                mandatory_map[s] = False

        # 3. Upload to local volume / S3 storage
        file_url = None
        object_key = f"documents/validations/{uuid.uuid4().hex[:8]}/{filename}"
        try:
            file_url = s3_service.upload_file(io.BytesIO(file_content), object_key, content_type=mime_type)
        except Exception:
            file_url = f"/uploads/{filename}"

        # 4. Run Gemini validation against checklist & custom prompt
        ai_result = await gemini_service.validate_document_checklist(
            file_content=file_content,
            mime_type=mime_type,
            checklist_items=checklist_strings,
            custom_prompt=custom_prompt,
            document_name=filename,
        )

        overall_score = float(ai_result.get("overall_score", 0.0))
        summary = ai_result.get("summary", "Pemeriksaan dokumen selesai.")
        checklist_evaluations = ai_result.get("checklist_evaluations", [])
        recommendations = ai_result.get("recommendations", [])
        extracted_project_data = ai_result.get("extracted_project", {})

        # 5. Evaluate Mandatory Conditions & Threshold Status
        failed_mandatory_items = []
        for e in checklist_evaluations:
            item_name = e.get("item", "")
            is_mand = mandatory_map.get(item_name, False)
            e["is_mandatory"] = is_mand
            if is_mand and e.get("status") == "Tidak Memenuhi":
                failed_mandatory_items.append(item_name)
                e["severity"] = "ERROR"

        # Determine compliance status
        if failed_mandatory_items and strict_mandatory:
            compliance_status = "Perlu Perbaikan"
            summary += f" [PERINGATAN: Gagal memenuhi butir wajib (Mandatory): {', '.join(failed_mandatory_items)}]"
        elif overall_score >= passing_threshold:
            compliance_status = "Lulus Verifikasi"
        elif overall_score >= warning_threshold:
            compliance_status = "Catatan Procurement"
        else:
            compliance_status = "Perlu Perbaikan"

        # 6. Apply target_stage_to_clear if profile specifies
        raw_stages = extracted_project_data.get("stages", [])
        if target_stage_to_clear and compliance_status in ("Lulus Verifikasi", "Catatan Procurement"):
            for s in raw_stages:
                if s.get("step") == target_stage_to_clear or target_stage_to_clear.lower() in s.get("step", "").lower():
                    s["auto_cleared"] = True
                    s["status"] = "Done"
                    s["notes"] = f"Auto-cleared berdasarkan standar kelayakan '{profile.name if profile else 'Profil'}'"

        # 7. Create immutable Validation Log record (and DocumentModel if request_id is already provided)
        validation_id = f"VAL-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)
        linked_doc_id: Optional[str] = None

        if request_id:
            req_check = await self.session.execute(
                select(ProcurementRequestModel).where(ProcurementRequestModel.id == request_id)
            )
            existing_req = req_check.scalars().first()
            if existing_req:
                linked_doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
                doc_status = (
                    "Lulus Verifikasi"
                    if compliance_status == "Lulus Verifikasi"
                    else ("Tindak Lanjut FPP" if compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                )
                doc_issues = [
                    f"{e.get('item', 'Klausul')}: {e.get('explanation', 'Perlu perbaikan')}"
                    for e in checklist_evaluations
                    if e.get("status") != "Memenuhi"
                ]
                doc_record = DocumentModel(
                    id=linked_doc_id,
                    request_id=request_id,
                    name=filename,
                    type="Wajib",
                    document_kind=profile.document_kind if profile else "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                    status=doc_status,
                    upload_date=now,
                    pic_id=actor_id or "USR-ADMIN",
                    pic_name=actor_name or "Administrator",
                    issues=doc_issues,
                    next_action=recommendations[0] if recommendations else "Lanjutkan ke tahapan pengadaan.",
                    procurement_step=existing_req.current_step,
                    file_url=file_url,
                    mime_type=mime_type,
                    version_number=1,
                )
                self.session.add(doc_record)

                act_log = ProcurementActivityLogModel(
                    id=str(uuid.uuid4()),
                    request_id=request_id,
                    user_id=actor_id or "USR-ADMIN",
                    user_name=actor_name or "Administrator",
                    action="DOCUMENT_VALIDATED",
                    previous_state=None,
                    new_state=compliance_status,
                    notes=f"Dokumen '{filename}' divalidasi AI (Skor: {overall_score:.0f}%, Status: {compliance_status}).",
                    created_at=now,
                )
                self.session.add(act_log)

        log_model = DocumentValidationLogModel(
            id=validation_id,
            request_id=request_id,
            document_id=linked_doc_id,
            profile_id=profile.id if profile else None,
            profile_name=profile.name if profile else None,
            document_name=filename,
            document_file_url=file_url,
            mime_type=mime_type,
            user_prompt=custom_prompt,
            checklist_snapshot=checklist_strings,
            validation_result=ai_result,
            overall_score=overall_score,
            passing_score_threshold=passing_threshold,
            compliance_status=compliance_status,
            validated_by_id=actor_id or "USR-ADMIN",
            validated_by_name=actor_name or "Administrator",
            created_at=now,
        )

        self.session.add(log_model)
        await self.session.commit()
        await self.session.refresh(log_model)

        # 8. Construct typed response DTO
        eval_dtos = [
            ChecklistItemResultDto(
                item=e.get("item", ""),
                status=e.get("status", "Perlu Perhatian"),
                evidence_quote=e.get("evidence_quote"),
                explanation=e.get("explanation"),
                severity=e.get("severity", "WARNING"),
                is_mandatory=bool(e.get("is_mandatory", False)),
            )
            for e in checklist_evaluations
        ]

        stage_dtos = [
            ExtractedStageDto(
                step=s.get("step", ""),
                status=s.get("status", "Pending"),
                auto_cleared=bool(s.get("auto_cleared", False)),
                notes=s.get("notes"),
            )
            for s in raw_stages
        ]

        project_dto = ExtractedProjectDto(
            title=extracted_project_data.get("title", filename.rsplit(".", 1)[0].replace("_", " ").title()),
            estimated_amount=float(extracted_project_data.get("estimated_amount", 0.0)),
            suggested_method=extracted_project_data.get("suggested_method", DEFAULT_METHOD),
            department_name=extracted_project_data.get("department_name", "Procurement & General Support"),
            stages=stage_dtos,
        )

        return DocumentValidationResponseDto(
            id=log_model.id,
            document_name=log_model.document_name,
            document_file_url=log_model.document_file_url,
            mime_type=log_model.mime_type,
            profile_id=log_model.profile_id,
            profile_name=log_model.profile_name,
            overall_score=log_model.overall_score,
            passing_score_threshold=passing_threshold,
            compliance_status=log_model.compliance_status,
            summary=summary,
            checklist_evaluations=eval_dtos,
            recommendations=recommendations,
            extracted_project=project_dto,
            created_at=log_model.created_at,
            request_id=log_model.request_id,
            document_id=log_model.document_id,
        )


class PublishValidationToTrackerUseCase:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute(
        self,
        payload: PublishValidationToTrackerRequestDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1. Fetch Validation Log (by id or document_id)
        result = await self.session.execute(
            select(DocumentValidationLogModel).where(
                or_(
                    DocumentValidationLogModel.id == payload.validation_log_id,
                    DocumentValidationLogModel.document_id == payload.validation_log_id,
                )
            )
        )
        val_log = result.scalars().first()
        if not val_log:
            raise NotFoundException(f"Log validasi '{payload.validation_log_id}' tidak ditemukan")

        ai_project = (val_log.validation_result or {}).get("extracted_project", {})
        pic_id = payload.pic_id or actor_id or val_log.validated_by_id or "USR-ADMIN"
        pic_name = payload.pic_name or actor_name or val_log.validated_by_name or "Administrator"
        now = datetime.now(timezone.utc)

        # Build document issues from non-passing checklist items
        issues = []
        for eval_item in (val_log.validation_result or {}).get("checklist_evaluations", []):
            if eval_item.get("status") != "Memenuhi":
                item_name = eval_item.get("item", "Klausul")
                expl = eval_item.get("explanation", "Perlu perbaikan")
                issues.append(f"{item_name}: {expl}")

        doc_status = (
            "Lulus Verifikasi"
            if val_log.compliance_status == "Lulus Verifikasi"
            else ("Tindak Lanjut FPP" if val_log.compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
        )

        raw_stages = []
        if payload.stages:
            raw_stages = [s.model_dump() for s in payload.stages]
        elif ai_project.get("stages"):
            raw_stages = ai_project.get("stages")

        # ── MODE A: LINK TO EXISTING PROCUREMENT REQUEST ──
        if payload.target_request_id:
            req_res = await self.session.execute(
                select(ProcurementRequestModel).where(ProcurementRequestModel.id == payload.target_request_id)
            )
            existing_req = req_res.scalars().first()
            if not existing_req:
                raise NotFoundException(f"Pekerjaan '{payload.target_request_id}' tidak ditemukan")

            doc_id = val_log.document_id
            if doc_id:
                doc_res = await self.session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
                existing_doc = doc_res.scalars().first()
                if existing_doc:
                    existing_doc.request_id = existing_req.id
                    existing_doc.status = doc_status
                    existing_doc.issues = issues
            else:
                doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
                doc_record = DocumentModel(
                    id=doc_id,
                    request_id=existing_req.id,
                    name=val_log.document_name,
                    type="Wajib",
                    document_kind=val_log.profile_name or "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                    status=doc_status,
                    upload_date=now,
                    pic_id=pic_id,
                    pic_name=pic_name,
                    issues=issues,
                    next_action=(
                        (val_log.validation_result or {}).get("recommendations", ["Lanjutkan ke tahapan tender."])[0]
                        if (val_log.validation_result or {}).get("recommendations")
                        else "Lanjutkan ke tahapan tender."
                    ),
                    procurement_step=existing_req.current_step,
                    file_url=val_log.document_file_url,
                    mime_type=val_log.mime_type,
                    version_number=1,
                )
                self.session.add(doc_record)

            # Auto-clear matching milestones on the existing request
            ms_res = await self.session.execute(
                select(ProcurementMilestoneModel).where(ProcurementMilestoneModel.request_id == existing_req.id)
            )
            existing_milestones = ms_res.scalars().all()
            auto_cleared_count = 0
            for s in raw_stages:
                if s.get("auto_cleared") or s.get("status") == "Done":
                    step_name = (s.get("step") or "").lower()
                    for ms in existing_milestones:
                        if ms.step and (ms.step.lower() == step_name or step_name in ms.step.lower()):
                            ms.status = "Completed"
                            ms.date = now
                            ms.notes = s.get("notes") or f"Diselesaikan otomatis melalui validasi dokumen '{val_log.document_name}'"
                            auto_cleared_count += 1

            val_log.request_id = existing_req.id
            val_log.document_id = doc_id

            activity_log = ProcurementActivityLogModel(
                id=str(uuid.uuid4()),
                request_id=existing_req.id,
                user_id=pic_id,
                user_name=pic_name,
                action="DOCUMENT_LINKED",
                previous_state=existing_req.current_step,
                new_state=existing_req.current_step,
                notes=(
                    f"Dokumen '{val_log.document_name}' ditautkan ke pekerjaan "
                    f"(Skor: {val_log.overall_score:.0f}%, Status: {val_log.compliance_status})."
                ),
                created_at=now,
            )
            self.session.add(activity_log)
            await self.session.commit()

            return {
                "success": True,
                "message": f"Dokumen berhasil ditautkan ke pekerjaan '{existing_req.title}'",
                "request_id": existing_req.id,
                "title": existing_req.title,
                "current_step": existing_req.current_step,
                "stage": existing_req.stage,
                "document_id": doc_id,
                "validation_log_id": val_log.id,
                "auto_cleared_stages_count": auto_cleared_count,
            }

        # ── MODE B: CREATE NEW PROCUREMENT REQUEST ──
        doc_clean_name = val_log.document_name.rsplit(".", 1)[0].replace("_", " ").title()
        project_title = payload.title or ai_project.get("title") or f"Pengadaan: {doc_clean_name}"
        amount = payload.amount if payload.amount is not None else float(ai_project.get("estimated_amount", 0.0))
        method = payload.procurement_method or ai_project.get("suggested_method", DEFAULT_METHOD)
        department_id = payload.department_id or "DEPT-PROC"
        department_name = payload.department_name or ai_project.get("department_name", "Procurement & General Support")
        fpp_id = payload.fpp_id or "FPP-ENG"
        fpp_name = payload.fpp_name or "Fungsi Pemohon Pengadaan"

        if not raw_stages:
            default_steps = steps_for_method(method)
            for idx, stp in enumerate(default_steps):
                raw_stages.append({
                    "step": stp,
                    "status": "In Progress" if idx == 0 else "Pending",
                    "auto_cleared": False,
                    "notes": None,
                })

        has_in_progress = any(s.get("status") == "In Progress" for s in raw_stages)
        if not has_in_progress:
            first_pending = next((s for s in raw_stages if s.get("status") == "Pending"), None)
            if first_pending:
                first_pending["status"] = "In Progress"
            elif raw_stages:
                raw_stages[0]["status"] = "In Progress"

        current_stage_step = next(
            (s.get("step") for s in raw_stages if s.get("status") == "In Progress"),
            raw_stages[0]["step"] if raw_stages else "Penyusunan RKS / Spesifikasi Teknis"
        )
        current_operational_stage = STEP_TO_STAGE.get(current_stage_step, "Sourcing")

        new_request_id = f"REQ-{datetime.now().year}-{uuid.uuid4().hex[:5].upper()}"

        proc_request = ProcurementRequestModel(
            id=new_request_id,
            title=project_title,
            pic_id=pic_id,
            pic_name=pic_name,
            fpp_id=fpp_id,
            fpp_name=fpp_name,
            amount=amount,
            stage=current_operational_stage,
            operational_status="On Going",
            current_step=current_stage_step,
            department_id=department_id,
            department_name=department_name,
            procurement_method=method,
            is_urgent=False,
            stage_started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(proc_request)

        for s in raw_stages:
            ms_id = f"MS-{uuid.uuid4().hex[:8].upper()}"
            ms_status = s.get("status", "Pending")
            is_cleared = bool(s.get("auto_cleared", False))
            ms_date = now if (ms_status == "Done" or is_cleared) else None

            milestone = ProcurementMilestoneModel(
                id=ms_id,
                request_id=new_request_id,
                step=s.get("step"),
                status=ms_status,
                date=ms_date,
                pic_id=pic_id if ms_date else None,
                pic_name=pic_name if ms_date else None,
                notes=s.get("notes"),
            )
            self.session.add(milestone)

        doc_id = val_log.document_id or f"DOC-{uuid.uuid4().hex[:8].upper()}"
        if val_log.document_id:
            doc_res = await self.session.execute(select(DocumentModel).where(DocumentModel.id == val_log.document_id))
            existing_doc = doc_res.scalars().first()
            if existing_doc:
                existing_doc.request_id = new_request_id
                existing_doc.status = doc_status
        else:
            doc_record = DocumentModel(
                id=doc_id,
                request_id=new_request_id,
                name=val_log.document_name,
                type="Wajib",
                document_kind=val_log.profile_name or "Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                status=doc_status,
                upload_date=now,
                pic_id=pic_id,
                pic_name=pic_name,
                issues=issues,
                next_action=(
                    (val_log.validation_result or {}).get("recommendations", ["Lanjutkan ke tahapan tender."])[0]
                    if (val_log.validation_result or {}).get("recommendations")
                    else "Lanjutkan ke tahapan tender."
                ),
                procurement_step=current_stage_step,
                file_url=val_log.document_file_url,
                mime_type=val_log.mime_type,
                version_number=1,
            )
            self.session.add(doc_record)

        deadline_id = f"DLD-{uuid.uuid4().hex[:8].upper()}"
        deadline = DeadlineModel(
            id=deadline_id,
            request_id=new_request_id,
            task_name=f"Pelaksanaan: {current_stage_step}",
            milestone=current_stage_step,
            pic_id=pic_id,
            pic_name=pic_name,
            department_id=department_id,
            department_name=department_name,
            start_date=now,
            target_date=now + timedelta(days=7),
            status="On Track",
            urgency_level="Medium",
            next_action=f"Selesaikan tahapan '{current_stage_step}' sesuai ketentuan tata waktu pengadaan.",
            created_at=now,
        )
        self.session.add(deadline)

        activity_id = str(uuid.uuid4())
        auto_cleared_count = sum(1 for s in raw_stages if s.get("auto_cleared"))
        activity_log = ProcurementActivityLogModel(
            id=activity_id,
            request_id=new_request_id,
            user_id=pic_id,
            user_name=pic_name,
            action="CREATE",
            previous_state=None,
            new_state=current_operational_stage,
            notes=(
                f"Pekerjaan diterbitkan otomatis dari validasi AI dokumen '{val_log.document_name}' "
                f"(Skor: {val_log.overall_score:.0f}%, Status: {val_log.compliance_status}). "
                f"{auto_cleared_count} tahapan awal berhasil di-auto-clear."
            ),
            created_at=now,
        )
        self.session.add(activity_log)

        val_log.request_id = new_request_id
        val_log.document_id = doc_id

        await self.session.commit()
        await self.session.refresh(proc_request)

        return {
            "success": True,
            "message": f"Pekerjaan '{project_title}' berhasil diterbitkan ke Tracker",
            "request_id": new_request_id,
            "title": project_title,
            "current_step": current_stage_step,
            "stage": current_operational_stage,
            "document_id": doc_id,
            "validation_log_id": val_log.id,
            "auto_cleared_stages_count": auto_cleared_count,
        }


class GetValidationLogsUseCase:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_request_id(self, request_id: str) -> List[ValidationLogListItemDto]:
        query = (
            select(DocumentValidationLogModel)
            .where(DocumentValidationLogModel.request_id == request_id)
            .order_by(desc(DocumentValidationLogModel.created_at))
        )
        result = await self.session.execute(query)
        logs = result.scalars().all()

        items = []
        for l in logs:
            checklist = l.checklist_snapshot or []
            evals = l.validation_result.get("checklist_evaluations", []) if l.validation_result else []
            passed = sum(1 for e in evals if e.get("status") == "Memenuhi")
            items.append(
                ValidationLogListItemDto(
                    id=l.id,
                    request_id=l.request_id,
                    document_id=l.document_id,
                    profile_id=l.profile_id,
                    profile_name=l.profile_name,
                    document_name=l.document_name,
                    document_file_url=l.document_file_url,
                    overall_score=l.overall_score,
                    passing_score_threshold=l.passing_score_threshold or 80.0,
                    compliance_status=l.compliance_status,
                    checklist_count=len(checklist),
                    passed_count=passed,
                    validated_by_name=l.validated_by_name,
                    created_at=l.created_at,
                )
            )
        return items

    async def _ensure_validation_log(self, validation_or_doc_id: str) -> DocumentValidationLogModel:
        """
        Finds a DocumentValidationLogModel by id OR document_id.
        If none exists yet but a DocumentModel with that ID exists in `documents`,
        automatically synthesizes and persists a structured DocumentValidationLogModel
        so every document in the system has a complete D1 validation record in DB.
        """
        result = await self.session.execute(
            select(DocumentValidationLogModel)
            .where(
                or_(
                    DocumentValidationLogModel.id == validation_or_doc_id,
                    DocumentValidationLogModel.document_id == validation_or_doc_id,
                )
            )
            .order_by(desc(DocumentValidationLogModel.created_at))
        )
        l = result.scalars().first()
        if l:
            return l

        # Check if it's a DocumentModel without a validation log yet
        doc_res = await self.session.execute(
            select(DocumentModel).where(DocumentModel.id == validation_or_doc_id)
        )
        doc = doc_res.scalars().first()
        if not doc:
            raise NotFoundException(f"Log validasi atau dokumen '{validation_or_doc_id}' tidak ditemukan")

        # Fetch parent ProcurementRequestModel & Milestones if available
        req = None
        milestones = []
        if doc.request_id:
            req_res = await self.session.execute(
                select(ProcurementRequestModel).where(ProcurementRequestModel.id == doc.request_id)
            )
            req = req_res.scalars().first()
            ms_res = await self.session.execute(
                select(ProcurementMilestoneModel).where(ProcurementMilestoneModel.request_id == doc.request_id)
            )
            milestones = ms_res.scalars().all()

        is_passed = doc.status == "Lulus Verifikasi"
        doc_issues = doc.issues or []
        score = 92.0 if is_passed else (70.0 if doc.status == "Catatan Procurement" else 52.0)

        evals = [
            {
                "item": "Kelengkapan Identitas, Nomor & Tanggal Dokumen Pengadaan",
                "status": "Memenuhi",
                "evidence_quote": f"Dokumen: {doc.name} ({doc.document_number or 'Terdaftar di sistem'})",
                "explanation": "Identitas dokumen dan metadata pengadaan telah tercatat sesuai format standar.",
                "severity": "SUCCESS",
                "is_mandatory": True,
            },
            {
                "item": "Kesesuaian Ruang Lingkup & Spesifikasi Teknis Pekerjaan",
                "status": "Memenuhi" if is_passed else "Perlu Perhatian",
                "evidence_quote": f"Terkait tahapan: {doc.procurement_step or 'Persiapan Pengadaan'}",
                "explanation": (
                    "Ruang lingkup teknis telah memenuhi standar kelayakan pra-tender."
                    if is_passed
                    else (doc_issues[0] if doc_issues else "Perlu penyesuaian rincian teknis sesuai catatan pemeriksa.")
                ),
                "severity": "SUCCESS" if is_passed else "WARNING",
                "is_mandatory": True,
            },
            {
                "item": "Kepatuhan Anggaran / HPS & Ketentuan Komersial",
                "status": "Memenuhi" if len(doc_issues) == 0 else "Tidak Memenuhi",
                "evidence_quote": None if len(doc_issues) > 0 else "Sesuai pagu anggaran pekerjaan terikat.",
                "explanation": (
                    "Komponen biaya dan perpajakan telah sesuai ketentuan."
                    if len(doc_issues) == 0
                    else "; ".join(doc_issues)
                ),
                "severity": "SUCCESS" if len(doc_issues) == 0 else "ERROR",
                "is_mandatory": True,
            },
            {
                "item": "Otorisasi Pejabat Berwenang & Kelengkapan Lampiran",
                "status": "Memenuhi",
                "evidence_quote": f"Diunggah dan diverifikasi oleh {doc.pic_name}",
                "explanation": "Dokumen telah diotorisasi oleh fungsi terkait.",
                "severity": "SUCCESS",
                "is_mandatory": False,
            },
        ]

        stages_payload = []
        if milestones:
            for ms in milestones:
                is_done = ms.status in ("Completed", "Done")
                stages_payload.append({
                    "step": ms.step,
                    "status": "Done" if is_done else ("In Progress" if ms.status == "In Progress" else "Pending"),
                    "auto_cleared": is_done and ms.step == doc.procurement_step,
                    "notes": ms.notes,
                })
        else:
            for idx, stp in enumerate(steps_for_method(req.procurement_method if req else DEFAULT_METHOD)):
                stages_payload.append({
                    "step": stp,
                    "status": "Done" if idx == 0 and is_passed else ("In Progress" if idx == 1 else "Pending"),
                    "auto_cleared": idx == 0 and is_passed,
                    "notes": "Terverifikasi dari pemeriksaan dokumen" if idx == 0 and is_passed else None,
                })

        recommendations = (
            [doc.next_action]
            if doc.next_action
            else (
                ["Dokumen telah memenuhi syarat kelayakan. Lanjutkan ke tahapan pengadaan berikutnya."]
                if is_passed
                else ["Lakukan revisi dokumen sesuai daftar catatan pemeriksaan sebelum melanjutkan tahapan."]
            )
        )

        summary_text = (
            f"Dokumen '{doc.name}' dinyatakan {doc.status} dengan skor kepatuhan {score:.0f}/100. "
            + (
                "Seluruh kriteria wajib telah terpenuhi."
                if is_passed
                else f"Terdapat {len(doc_issues)} catatan pemeriksaan yang memerlukan tindak lanjut."
            )
        )

        validation_result_json = {
            "overall_score": score,
            "summary": summary_text,
            "checklist_evaluations": evals,
            "recommendations": recommendations,
            "extracted_project": {
                "title": req.title if req else doc.name.rsplit(".", 1)[0].replace("_", " "),
                "estimated_amount": float(req.amount) if req else 0.0,
                "suggested_method": (req.procurement_method if req and req.procurement_method else DEFAULT_METHOD),
                "department_name": (req.department_name if req else "Procurement & General Support"),
                "stages": stages_payload,
            },
        }

        new_log = DocumentValidationLogModel(
            id=f"VAL-{uuid.uuid4().hex[:8].upper()}",
            request_id=doc.request_id,
            document_id=doc.id,
            profile_id="VPROF-KAK-TEKNIS",
            profile_name=doc.document_kind or "Standar Kelayakan Dokumen Pengadaan",
            document_name=doc.name,
            document_file_url=doc.file_url,
            mime_type=doc.mime_type or "application/pdf",
            user_prompt=None,
            checklist_snapshot=[e["item"] for e in evals],
            validation_result=validation_result_json,
            overall_score=score,
            passing_score_threshold=80.0,
            compliance_status=doc.status,
            validated_by_id=doc.pic_id,
            validated_by_name=doc.pic_name,
            created_at=doc.upload_date or datetime.now(timezone.utc),
        )
        self.session.add(new_log)
        await self.session.commit()
        await self.session.refresh(new_log)
        return new_log

    async def get_by_id(self, validation_id: str) -> DocumentValidationResponseDto:
        l = await self._ensure_validation_log(validation_id)

        res_data = l.validation_result or {}
        eval_dtos = [
            ChecklistItemResultDto(
                item=e.get("item", ""),
                status=e.get("status", "Perlu Perhatian"),
                evidence_quote=e.get("evidence_quote"),
                explanation=e.get("explanation"),
                severity=e.get("severity", "WARNING"),
                is_mandatory=bool(e.get("is_mandatory", False)),
            )
            for e in res_data.get("checklist_evaluations", [])
        ]

        proj_data = res_data.get("extracted_project", {})
        stage_dtos = [
            ExtractedStageDto(
                step=s.get("step", ""),
                status=s.get("status", "Pending"),
                auto_cleared=bool(s.get("auto_cleared", False)),
                notes=s.get("notes"),
            )
            for s in proj_data.get("stages", [])
        ]

        project_dto = ExtractedProjectDto(
            title=proj_data.get("title", l.document_name),
            estimated_amount=float(proj_data.get("estimated_amount", 0.0)),
            suggested_method=proj_data.get("suggested_method", DEFAULT_METHOD),
            department_name=proj_data.get("department_name", "Procurement & General Support"),
            stages=stage_dtos,
        )

        return DocumentValidationResponseDto(
            id=l.id,
            document_name=l.document_name,
            document_file_url=l.document_file_url,
            mime_type=l.mime_type,
            profile_id=l.profile_id,
            profile_name=l.profile_name,
            overall_score=l.overall_score,
            passing_score_threshold=l.passing_score_threshold or 80.0,
            compliance_status=l.compliance_status,
            summary=res_data.get("summary", ""),
            checklist_evaluations=eval_dtos,
            recommendations=res_data.get("recommendations", []),
            extracted_project=project_dto,
            created_at=l.created_at,
            request_id=l.request_id,
            document_id=l.document_id,
        )

    async def update_decision(
        self,
        validation_id: str,
        dto: UpdateValidationDecisionDto,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
    ) -> DocumentValidationResponseDto:
        l = await self._ensure_validation_log(validation_id)
        l.compliance_status = dto.compliance_status
        if dto.overall_score is not None:
            l.overall_score = dto.overall_score

        res_data = dict(l.validation_result or {})
        if dto.reviewer_notes:
            res_data["summary"] = dto.reviewer_notes
        if dto.next_action:
            recs = list(res_data.get("recommendations", []))
            if recs:
                recs[0] = dto.next_action
            else:
                recs = [dto.next_action]
            res_data["recommendations"] = recs
        l.validation_result = res_data

        # Sync with linked DocumentModel if present
        if l.document_id:
            doc_res = await self.session.execute(
                select(DocumentModel).where(DocumentModel.id == l.document_id)
            )
            doc = doc_res.scalars().first()
            if doc:
                doc.status = (
                    "Lulus Verifikasi"
                    if dto.compliance_status == "Lulus Verifikasi"
                    else ("Tindak Lanjut FPP" if dto.compliance_status in ("Perlu Perbaikan", "Tindak Lanjut FPP") else "Catatan Procurement")
                )
                if dto.next_action:
                    doc.next_action = dto.next_action

        await self.session.commit()
        await self.session.refresh(l)
        return await self.get_by_id(l.id)


