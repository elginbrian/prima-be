"""
Unit tests for Document Validation Engine (Modul D1 & Audit Trail D2/D3/D4)
Tests use cases, DTOs, and Gemini AI validation logic without needing external DB.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

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
    ValidationLogListItemDto,
)
from src.infrastructure.ai.gemini_service import gemini_service
from src.application.use_cases.validation_use_cases import (
    AnalyzeDocumentChecklistUseCase,
    PublishValidationToTrackerUseCase,
    GetValidationLogsUseCase,
    ManageValidationProfilesUseCase,
)
from src.infrastructure.models.validation_model import DocumentValidationLogModel, ValidationProfileModel
from src.infrastructure.models.procurement_model import ProcurementRequestModel


def test_dtos_validation():
    eval_dto = ChecklistItemResultDto(
        item="Termin Pembayaran",
        status="Memenuhi",
        evidence_quote="Bab 4: Pembayaran dilakukan dalam 30 hari",
        explanation="Sesuai ketentuan standar",
        severity="SUCCESS"
    )
    assert eval_dto.status == "Memenuhi"
    assert eval_dto.severity == "SUCCESS"

    stage_dto = ExtractedStageDto(
        step="Penyusunan RKS",
        status="Done",
        auto_cleared=True,
        notes="Terverifikasi otomatis"
    )
    assert stage_dto.auto_cleared is True

    project_dto = ExtractedProjectDto(
        title="Pengadaan Genset 500kVA",
        estimated_amount=1200000000.0,
        suggested_method="Tender Terbuka",
        stages=[stage_dto]
    )
    assert project_dto.estimated_amount == 1200000000.0


def test_gemini_mock_validation_generation():
    checklists = [
        "Spesifikasi Genset 500kVA",
        "Garansi minimal 2 tahun",
        "Klausul denda keterlambatan 1 mil per hari"
    ]
    res = gemini_service._generate_mock_validation(
        checklist_items=checklists,
        custom_prompt="Periksa kelayakan teknis",
        document_name="KAK_Genset_2026.pdf"
    )
    assert "overall_score" in res
    assert res["overall_score"] >= 60
    assert len(res["checklist_evaluations"]) == 3
    assert len(res["extracted_project"]["stages"]) >= 5
    assert res["extracted_project"]["stages"][0]["auto_cleared"] is True


@pytest.mark.asyncio
async def test_analyze_document_checklist_use_case():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    use_case = AnalyzeDocumentChecklistUseCase(session)

    sample_bytes = b"%PDF mock document bytes"
    with patch("src.application.use_cases.validation_use_cases.s3_service.upload_file", return_value="mock/path/Dokumen_Pengadaan_Server.pdf"):
        with patch.object(
            gemini_service,
            "validate_document_checklist",
            new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = {
                "overall_score": 92.0,
                "compliance_status": "Lulus Verifikasi",
                "checklist_evaluations": [
                    {
                        "item": "Kapasitas RAM 64GB",
                        "status": "Memenuhi",
                        "evidence_quote": "RAM 64GB DDR5 tercantum di Bab 2",
                        "explanation": "Sesuai standar",
                        "severity": "SUCCESS"
                    },
                    {
                        "item": "Garansi 3 Tahun",
                        "status": "Memenuhi",
                        "evidence_quote": "Garansi 36 bulan vendor resmi",
                        "explanation": "Memenuhi ketentuan SLA",
                        "severity": "SUCCESS"
                    }
                ],
                "actionable_recommendations": ["Lanjutkan ke tahap tender"],
                "extracted_project": {
                    "title": "Pengadaan Server Baru",
                    "estimated_amount": 500000000.0,
                    "suggested_method": "Tender Terbuka",
                    "stages": [
                        {"step": "Penyusunan RKS", "status": "Done", "auto_cleared": True, "notes": "Selesai verifikasi"}
                    ]
                }
            }

            result = await use_case.execute(
                file_content=sample_bytes,
                filename="Dokumen_Pengadaan_Server.pdf",
                mime_type="application/pdf",
                checklist_items=["Kapasitas RAM 64GB", "Garansi 3 Tahun"],
                custom_prompt="Pastikan garansi vendor resmi",
                actor_id="USR-123",
                actor_name="Budi Procurement",
            )

    assert isinstance(result, DocumentValidationResponseDto)
    assert result.document_name == "Dokumen_Pengadaan_Server.pdf"
    assert len(result.checklist_evaluations) == 2
    assert session.add.called
    assert session.commit.called


@pytest.mark.asyncio
async def test_publish_validation_to_tracker_use_case():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    # Mock finding validation log in DB
    mock_val_log = DocumentValidationLogModel(
        id="VAL-TEST001",
        request_id=None,
        document_name="Spesifikasi_Teknis.pdf",
        document_file_url="documents/validations/test/Spesifikasi_Teknis.pdf",
        mime_type="application/pdf",
        checklist_snapshot=["Spesifikasi RAM"],
        validation_result={
            "overall_score": 90.0,
            "compliance_status": "Lulus Verifikasi",
            "extracted_project": {
                "title": "Pengadaan Server Baru",
                "estimated_amount": 800000000.0,
                "suggested_method": "Tender Terbuka",
                "stages": [
                    {"step": "Penyusunan RKS", "status": "Done", "auto_cleared": True},
                    {"step": "Rapat Pra-Tender", "status": "In Progress", "auto_cleared": False},
                    {"step": "Pengumuman", "status": "Pending", "auto_cleared": False},
                ]
            }
        },
        overall_score=90.0,
        compliance_status="Lulus Verifikasi",
        validated_by_id="USR-001",
        validated_by_name="Admin",
        created_at=datetime.now(timezone.utc),
    )

    scalar_result = MagicMock()
    scalar_result.scalars.return_value.first.return_value = mock_val_log
    session.execute.return_value = scalar_result

    use_case = PublishValidationToTrackerUseCase(session)
    payload = PublishValidationToTrackerRequestDto(
        validation_log_id="VAL-TEST001",
        title="Pengadaan Server Baru Data Center",
        amount=850000000.0,
    )

    res = await use_case.execute(payload, actor_id="USR-001", actor_name="Admin")
    assert res["success"] is True
    assert res["request_id"].startswith("REQ-")
    assert res["auto_cleared_stages_count"] == 1
    assert mock_val_log.request_id == res["request_id"]
    assert session.commit.called


@pytest.mark.asyncio
async def test_validation_profile_management_use_case():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    use_case = ManageValidationProfilesUseCase(session)

    # 1. Create Profile
    dto = CreateValidationProfileDto(
        name="Standar Evaluasi Jaminan Bank",
        document_kind="Jaminan Pelaksanaan",
        description="Standar Bank Garansi",
        passing_score_threshold=85.0,
        strict_mandatory_enforcement=True,
        target_stage_to_clear="Penyusunan RKS & Spesifikasi Teknis",
        checklist_rules=[
            ChecklistRuleItemDto(
                category="Legalitas",
                item="Penerbit Bank Himbara",
                guidance="Cek Bank Mandiri / BRI / BNI",
                is_mandatory=True,
                weight=50,
            ),
            ChecklistRuleItemDto(
                category="Klausul",
                item="Klausul Unconditional",
                guidance="Cek tanpa syarat",
                is_mandatory=True,
                weight=50,
            )
        ]
    )

    created = await use_case.create_profile(dto, actor_id="USR-001", actor_name="Admin")
    assert created.name == "Standar Evaluasi Jaminan Bank"
    assert created.passing_score_threshold == 85.0
    assert len(created.checklist_rules) == 2
    assert session.add.called
    assert session.commit.called


@pytest.mark.asyncio
async def test_analyze_document_with_profile_and_mandatory_enforcement():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    # Mock finding validation profile in DB
    mock_profile = ValidationProfileModel(
        id="VPROF-TEST01",
        name="Standar Jaminan Pelaksanaan",
        code="STD_JAM",
        document_kind="Jaminan Pelaksanaan",
        passing_score_threshold=80.0,
        warning_score_threshold=60.0,
        strict_mandatory_enforcement=True,
        target_stage_to_clear="Penyusunan RKS & Spesifikasi Teknis",
        checklist_rules=[
            {
                "category": "Legal",
                "item": "Penerbit Bank Himbara",
                "is_mandatory": True,
                "weight": 50,
            },
            {
                "category": "Klausul",
                "item": "Klausul Unconditional",
                "is_mandatory": True,
                "weight": 50,
            }
        ]
    )

    scalar_result = MagicMock()
    scalar_result.scalars.return_value.first.return_value = mock_profile
    session.execute.return_value = scalar_result

    use_case = AnalyzeDocumentChecklistUseCase(session)

    # Simulate scenario: high score (85), BUT 1 mandatory item failed ("Tidak Memenuhi")
    with patch("src.application.use_cases.validation_use_cases.s3_service.upload_file", return_value="mock/file.pdf"):
        with patch.object(gemini_service, "validate_document_checklist", new_callable=AsyncMock) as mock_val:
            mock_val.return_value = {
                "overall_score": 85.0,
                "checklist_evaluations": [
                    {
                        "item": "Penerbit Bank Himbara",
                        "status": "Memenuhi",
                        "severity": "SUCCESS",
                        "explanation": "Bank Mandiri"
                    },
                    {
                        "item": "Klausul Unconditional",
                        "status": "Tidak Memenuhi",
                        "severity": "ERROR",
                        "explanation": "Klausul bersyarat ditemukan"
                    }
                ],
                "extracted_project": {
                    "title": "Pengadaan Jaminan",
                    "stages": [
                        {"step": "Penyusunan RKS & Spesifikasi Teknis", "status": "Pending", "auto_cleared": False}
                    ]
                }
            }

            res = await use_case.execute(
                file_content=b"%PDF test",
                filename="Jaminan_Test.pdf",
                mime_type="application/pdf",
                profile_id="VPROF-TEST01",
            )

    # Even though overall_score was 85.0, mandatory item failed -> compliance_status MUST be "Perlu Perbaikan"
    assert res.overall_score == 85.0
    assert res.compliance_status == "Perlu Perbaikan"
    assert res.profile_id == "VPROF-TEST01"
    assert res.profile_name == "Standar Jaminan Pelaksanaan"
    assert res.checklist_evaluations[1].is_mandatory is True
