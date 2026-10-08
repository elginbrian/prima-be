"""
seed_all.py — Seeder untuk Semua Modul
Termasuk Requests, Milestones, Documents (D2), Guarantees (D3), Deadlines (D4), Notifications, Settings

Jalankan dari root prima-be:
    python seed_all.py
"""
import asyncio
import uuid
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models.procurement_model import ProcurementRequestModel, ProcurementMilestoneModel
from src.infrastructure.models.document_model import DocumentModel
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.notification_model import NotificationModel
from src.infrastructure.models.settings_model import SettingsModel

def uid() -> str:
    return str(uuid.uuid4())

def dt(days_offset: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days_offset)

def dt_str(days_offset: int = 0) -> str:
    return (datetime.now() + timedelta(days=days_offset)).strftime("%Y-%m-%d")

async def clear_database(session: AsyncSession):
    tables = [
        "notifications",
        "documents",
        "guarantees",
        "deadlines",
        "procurement_milestones",
        "procurement_requests",
        "settings"
    ]
    for table in tables:
        await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    await session.commit()

async def seed_data():
    async with AsyncSessionLocal() as session:
        print("Clearing database...")
        await clear_database(session)

        print("Seeding Settings...")
        settings = SettingsModel(
            id=uid(),
            key="SLA_CONFIG",
            value={"default_sla_days": 14}
        )
        session.add(settings)

        print("Seeding Procurement Requests...")
        req1_id = uid()
        req2_id = uid()
        req3_id = uid()

        reqs = [
            ProcurementRequestModel(
                id=req1_id,
                title="Pengadaan Pompa Sentrifugal Unit RU-IV Cilacap",
                pic_id="USR-001", pic_name="Budi Santoso",
                fpp_id="USR-002", fpp_name="Rina Gunawan",
                amount=4_800_000_000,
                stage="Persiapan",
                operational_status="On Going",
                current_step="Rapat Pra-Tender",
                department_id="D001", department_name="Procurement",
                is_urgent=True,
                stage_started_at=dt(-5)
            ),
            ProcurementRequestModel(
                id=req2_id,
                title="Sewa Kendaraan Operasional Pemasaran Regional JBB",
                pic_id="USR-001", pic_name="Budi Santoso",
                fpp_id="USR-006", fpp_name="Siti Aminah",
                amount=1_250_000_000,
                stage="Tender",
                operational_status="On Going",
                current_step="Evaluasi Dokumen Penawaran",
                department_id="D002", department_name="General Affairs",
                is_urgent=False,
                stage_started_at=dt(-2)
            ),
            ProcurementRequestModel(
                id=req3_id,
                title="Pembangunan Fasilitas Blending Biodiesel FT Boyolali",
                pic_id="USR-002", pic_name="Rina Gunawan",
                fpp_id="USR-006", fpp_name="Siti Aminah",
                amount=15_500_000_000,
                stage="Selesai",
                operational_status="Selesai",
                current_step="Serah Terima (BAST)",
                department_id="D003", department_name="Engineering",
                is_urgent=True,
                stage_started_at=dt(-60)
            )
        ]
        session.add_all(reqs)
        await session.commit()

        print("Seeding Milestones...")
        milestones = [
            ProcurementMilestoneModel(id=uid(), request_id=req1_id, step="Rapat Pra-Tender", status="In Progress", notes="Agenda: review TOR"),
            ProcurementMilestoneModel(id=uid(), request_id=req2_id, step="Evaluasi Dokumen Penawaran", status="In Progress", notes="Sedang review teknis"),
            ProcurementMilestoneModel(id=uid(), request_id=req3_id, step="Serah Terima (BAST)", status="Completed", notes="Selesai 100%")
        ]
        session.add_all(milestones)

        print("Seeding Documents (D2)...")
        docs = [
            DocumentModel(
                id=uid(), request_id=req1_id,
                name="TOR_Pompa_Sentrifugal.pdf",
                type="Term of Reference", document_kind="Dokumen Teknis",
                status="Lulus Verifikasi",
                upload_date=dt(-4),
                pic_id="USR-001", pic_name="Budi Santoso",
                issues=[],
                procurement_step="Rapat Pra-Tender",
                document_date=dt_str(-5), document_number="TOR/2026/001",
                file_url="https://example.com/doc1", mime_type="application/pdf"
            ),
            DocumentModel(
                id=uid(), request_id=req1_id,
                name="RAB_Pompa_Sentrifugal.xlsx",
                type="Rencana Anggaran Biaya", document_kind="Dokumen Komersial",
                status="Catatan Procurement",
                upload_date=dt(-2),
                pic_id="USR-001", pic_name="Budi Santoso",
                issues=["Harga satuan pompa tidak sesuai HPS terbaru", "Pajak belum dimasukkan"],
                next_action="Revisi RAB dengan memasukkan komponen PPN 11%",
                procurement_step="Rapat Pra-Tender",
                document_date=dt_str(-3), document_number="RAB/2026/001",
                file_url="https://example.com/doc2", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        ]
        session.add_all(docs)

        print("Seeding Guarantees (D3)...")
        guarantees = [
            GuaranteeModel(
                id=uid(), request_id=req2_id,
                type="Jaminan Penawaran",
                issuer_type="Bank", issuer="Bank Mandiri",
                reference_no="BG/MDR/2026/001", beneficiary="Pertamina Patra Niaga",
                vendor_id="V001", vendor_name="PT Sejahtera Bersama",
                value=50_000_000,
                issue_date=dt_str(-10), expiry_date=dt_str(5),
                status="Mendekati Expiry"
            ),
            GuaranteeModel(
                id=uid(), request_id=req3_id,
                type="Jaminan Pelaksanaan",
                issuer_type="Asuransi", issuer="Asuransi Jasindo",
                reference_no="SURETY/JAS/2026/099", beneficiary="Pertamina Patra Niaga",
                vendor_id="V002", vendor_name="PT Bangun Karya",
                value=775_000_000,
                issue_date=dt_str(-60), expiry_date=dt_str(-2),
                status="Expired"
            )
        ]
        session.add_all(guarantees)

        print("Seeding Deadlines (D4)...")
        deadlines = [
            DeadlineModel(
                id=uid(), request_id=req1_id,
                task_name="Persetujuan TOR oleh VP Procurement",
                pic_id="USR-001", pic_name="Budi Santoso",
                department_id="DEPT-IT", department_name="IT Infrastructure",
                target_date=dt_str(2),
                status="At Risk",
                urgency_level="High",
                milestone="Rapat Pra-Tender",
                next_action="Follow up via telepon ke ruangan VP"
            ),
            DeadlineModel(
                id=uid(), request_id=req2_id,
                task_name="Penyelesaian Evaluasi Teknis",
                pic_id="USR-002", pic_name="Rina Gunawan",
                department_id="DEPT-OPS", department_name="Operations",
                target_date=dt_str(-1),
                status="Overdue",
                urgency_level="Critical",
                milestone="Evaluasi Dokumen Penawaran",
                overdue_reason="Tim teknis sedang dinas ke lapangan"
            )
        ]
        session.add_all(deadlines)

        print("Seeding Notifications...")
        notifs = [
            NotificationModel(
                id=uid(), request_id=req2_id,
                title="Jaminan Mendekati Kedaluwarsa",
                description="Jaminan Penawaran dari PT Sejahtera Bersama akan kedaluwarsa dalam 5 hari.",
                is_read=False,
                type="alert", category="Hari Ini"
            ),
            NotificationModel(
                id=uid(), request_id=req1_id,
                title="Tenggat Waktu Kritis",
                description="Persetujuan TOR oleh VP Procurement sudah mendekati target (H-2).",
                is_read=False,
                type="deadline", category="Hari Ini"
            ),
            NotificationModel(
                id=uid(), request_id=req1_id,
                title="Dokumen Perlu Revisi",
                description="RAB Pompa Sentrifugal mendapat catatan dari Procurement.",
                is_read=True,
                type="document", category="Kemarin"
            )
        ]
        session.add_all(notifs)

        await session.commit()
        print("Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed_data())
