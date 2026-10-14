"""
Milestone Deliverable Gatekeeper (Modul D3)

Evaluates whether a procurement may advance to the next step by checking
operational status, mandatory document verification and performance guarantees.
Pure evaluation logic: reads from the session, never mutates state.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.procurement_workflow import PROCUREMENT_STEPS, step_index
from src.infrastructure.models.procurement_model import ProcurementRequestModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.guarantee_model import GuaranteeModel

# Steps with index >= these values require extra prerequisites
DOCUMENT_REQUIRED_FROM_STEP_INDEX = 4
GUARANTEE_REQUIRED_FROM_STEP_INDEX = 9
MIN_GUARANTEE_RATIO = 0.05


def _issue(category: str, title: str, description: str, severity: str) -> dict:
    return {"category": category, "title": title, "description": description, "severity": severity}


def _check_operational_status(m: ProcurementRequestModel, blockers: list) -> None:
    if m.operational_status == "On Hold":
        blockers.append(_issue(
            "HOLD",
            "Pengadaan Sedang On Hold",
            "Pengadaan berstatus 'On Hold'. Ubah status operasional ke 'On Going' terlebih dahulu untuk melanjutkan.",
            "ERROR",
        ))
    elif m.operational_status == "Batal":
        blockers.append(_issue(
            "HOLD",
            "Pengadaan Dibatalkan",
            "Pengadaan berstatus 'Batal' dan tidak dapat melanjutkan tahapan.",
            "ERROR",
        ))


def _check_documents(mandatory_docs: list, curr_idx: int, blockers: list, warnings: list) -> None:
    for doc in mandatory_docs:
        if doc.status == "Tindak Lanjut FPP":
            blockers.append(_issue(
                "DOCUMENT",
                f"Dokumen Wajib '{doc.name}' Ditolak / Perlu Revisi",
                f"Dokumen berstatus '{doc.status}' dan memiliki {len(doc.issues or [])} catatan review yang harus diperbaiki FPP.",
                "ERROR",
            ))
        elif doc.status != "Lulus Verifikasi":
            warnings.append(_issue(
                "DOCUMENT",
                f"Dokumen '{doc.name}' Belum Terverifikasi",
                f"Status dokumen saat ini: '{doc.status}'. Pastikan dokumen diverifikasi sebelum tahap evaluasi.",
                "WARNING",
            ))

    if curr_idx >= DOCUMENT_REQUIRED_FROM_STEP_INDEX and len(mandatory_docs) == 0:
        warnings.append(_issue(
            "DOCUMENT",
            "Dokumen Prasyarat Wajib Belum Diunggah",
            "Tahap ini mensyaratkan dokumen pengadaan (DP3 / Kerangka Acuan) yang sah.",
            "WARNING",
        ))


def _check_guarantees(m: ProcurementRequestModel, guarantees: list, blockers: list, warnings: list) -> None:
    perf_guars = [g for g in guarantees if "pelaksanaan" in (g.type or "").lower()]
    if not perf_guars:
        warnings.append(_issue(
            "GUARANTEE",
            "Jaminan Pelaksanaan Belum Didaftarkan",
            "Tahap penetapan pemenang kontrak mensyaratkan warkat Jaminan Pelaksanaan yang sah.",
            "WARNING",
        ))
        return

    min_value = m.amount * MIN_GUARANTEE_RATIO
    for pg in perf_guars:
        if pg.status == "Expired":
            blockers.append(_issue(
                "GUARANTEE",
                f"Jaminan Pelaksanaan {pg.reference_no} Sudah Expired",
                "Warkat jaminan telah melewati batas jatuh tempo. Wajib diperpanjang sebelum penunjukan pemenang.",
                "ERROR",
            ))
        elif pg.value < min_value:
            warnings.append(_issue(
                "GUARANTEE",
                f"Nilai Jaminan {pg.reference_no} Kurang dari 5%",
                f"Nilai jaminan (Rp {pg.value:,.0f}) di bawah 5% pagu kontrak (Rp {min_value:,.0f}).",
                "WARNING",
            ))


async def evaluate_gatekeeper(session: AsyncSession, m: ProcurementRequestModel) -> dict:
    """Run all gatekeeper checks for a procurement request and return the report."""
    blockers: list = []
    warnings: list = []

    _check_operational_status(m, blockers)

    docs = (await session.execute(
        select(DocumentModel).where(DocumentModel.request_id == m.id)
    )).scalars().all()
    mandatory_docs = [d for d in docs if d.type == "Wajib" or getattr(d, "document_kind", None) == "Wajib"]
    verified_mandatory = [d for d in mandatory_docs if d.status == "Lulus Verifikasi"]

    curr_idx = step_index(m.current_step, PROCUREMENT_STEPS)
    _check_documents(mandatory_docs, curr_idx, blockers, warnings)

    if curr_idx >= GUARANTEE_REQUIRED_FROM_STEP_INDEX:
        guarantees = (await session.execute(
            select(GuaranteeModel).where(GuaranteeModel.request_id == m.id)
        )).scalars().all()
        _check_guarantees(m, guarantees, blockers, warnings)

    return {
        "request_id": m.id,
        "current_stage": m.stage,
        "current_step": m.current_step,
        "is_ready_to_advance": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "mandatory_documents_total": len(mandatory_docs),
        "mandatory_documents_verified": len(verified_mandatory),
        "can_override": True,
    }
