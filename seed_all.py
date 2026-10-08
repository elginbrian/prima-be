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
        "system_settings"
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
            id="1",
            email_notifications=True,
            whatsapp_notifications=False,
            sla_warning_days=3,
            auto_escalation=True,
            auto_escalate_days=2,
            escalation_manager_id="USR-006",
            approval_threshold=500_000_000.0,
            department_reviewers={"DEPT-IT": "USR-001", "DEPT-OPS": "USR-002"},
            milestone_durations={"Rapat Pra-Tender": 3, "Evaluasi Dokumen": 7, "Persetujuan TOR": 2, "Pengumuman Tender": 14},
            ai_sensitivity="High",
            theme="Light"
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
                department_id="DEPT-IT", department_name="IT Infrastructure",
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
                department_id="DEPT-OPS", department_name="Operations",
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
                department_id="DEPT-IT", department_name="IT Infrastructure",
                is_urgent=True,
                stage_started_at=dt(-60)
            )
        ]
        session.add_all(reqs)
        await session.commit()

        print("Seeding Timelines (Milestones)...")
        # Timeline for Req1
        doc1_id = uid()
        doc2_id = uid()
        milestones = [
            ProcurementMilestoneModel(id=uid(), request_id=req1_id, step="Penerimaan FPP", status="Completed", notes="Diterima oleh Procurement", date=dt(-10), pic_id="USR-002", pic_name="Rina Gunawan"),
            ProcurementMilestoneModel(id=uid(), request_id=req1_id, step="Pembuatan TOR", status="Completed", notes="TOR sudah disubmit dan diverifikasi", date=dt(-7), pic_id="USR-001", pic_name="Budi Santoso"),
            ProcurementMilestoneModel(id=uid(), request_id=req1_id, step="Rapat Pra-Tender", status="In Progress", notes="Menunggu revisi RAB", date=dt(-1), pic_id="USR-001", pic_name="Budi Santoso"),
            
            # Timeline for Req2
            ProcurementMilestoneModel(id=uid(), request_id=req2_id, step="Pengumuman Tender", status="Completed", notes="Diumumkan di eProc", date=dt(-14), pic_id="USR-006", pic_name="Siti Aminah"),
            ProcurementMilestoneModel(id=uid(), request_id=req2_id, step="Pemasukan Penawaran", status="Completed", notes="3 Vendor memasukkan penawaran", date=dt(-3), pic_id="USR-001", pic_name="Budi Santoso"),
            ProcurementMilestoneModel(id=uid(), request_id=req2_id, step="Evaluasi Dokumen Penawaran", status="In Progress", notes="Sedang review teknis", date=dt(-1), pic_id="USR-001", pic_name="Budi Santoso"),
            
            # Timeline for Req3
            ProcurementMilestoneModel(id=uid(), request_id=req3_id, step="Penandatanganan Kontrak", status="Completed", notes="Kontrak #K-001 ditandatangani", date=dt(-55), pic_id="USR-002", pic_name="Rina Gunawan"),
            ProcurementMilestoneModel(id=uid(), request_id=req3_id, step="Serah Terima (BAST)", status="Completed", notes="Selesai 100% tanpa catatan mayor", date=dt(-2), pic_id="USR-006", pic_name="Siti Aminah")
        ]
        session.add_all(milestones)

        print("Seeding Documents (D2)...")
        docs = [
            DocumentModel(
                id=doc1_id, request_id=req1_id,
                name="TOR_Pompa_Sentrifugal.pdf",
                type="Term of Reference", document_kind="Dokumen Teknis",
                status="Lulus Verifikasi",
                upload_date=dt(-7),
                pic_id="USR-001", pic_name="Budi Santoso",
                issues=[],
                procurement_step="Pembuatan TOR",
                document_date=dt_str(-8), document_number="TOR/2026/001",
                file_url="https://example.com/doc1", mime_type="application/pdf"
            ),
            DocumentModel(
                id=doc2_id, request_id=req1_id,
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
            ),
            DocumentModel(
                id=uid(), request_id=req2_id,
                name="BA_Pemasukan_Penawaran.pdf",
                type="Berita Acara", document_kind="Dokumen Formal",
                status="Lulus Verifikasi",
                upload_date=dt(-3),
                pic_id="USR-006", pic_name="Siti Aminah",
                issues=[],
                procurement_step="Pemasukan Penawaran",
                document_date=dt_str(-3), document_number="BA/2026/045",
                file_url="https://example.com/doc3", mime_type="application/pdf"
            ),
            DocumentModel(
                id=uid(), request_id=req3_id,
                name="BAST_Blending_Biodiesel.pdf",
                type="Berita Acara", document_kind="Dokumen Formal",
                status="Tindak Lanjut FPP",
                upload_date=dt(-1),
                pic_id="USR-002", pic_name="Rina Gunawan",
                issues=["Tanda tangan FPP belum lengkap di halaman 3"],
                next_action="Lengkapi tanda tangan digital di halaman 3 lalu unggah ulang",
                procurement_step="Serah Terima (BAST)",
                document_date=dt_str(-1), document_number="BAST/2026/999",
                file_url="https://example.com/doc4", mime_type="application/pdf"
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
            ),
            GuaranteeModel(
                id=uid(), request_id=req3_id,
                type="Jaminan Pemeliharaan",
                issuer_type="Bank", issuer="Bank BRI",
                reference_no="BG/BRI/2026/102", beneficiary="Pertamina Patra Niaga",
                vendor_id="V002", vendor_name="PT Bangun Karya",
                value=300_000_000,
                issue_date=dt_str(-2), expiry_date=dt_str(180),
                status="Active"
            )
        ]
        session.add_all(guarantees)

        print("Seeding SLAs (D4) and Actions...")
        deadlines = [
            DeadlineModel(
                id=uid(), request_id=req1_id,
                task_name="Persetujuan TOR dan Anggaran oleh VP",
                pic_id="USR-001", pic_name="Budi Santoso",
                department_id="DEPT-IT", department_name="IT Infrastructure",
                target_date=dt_str(2),
                status="At Risk",
                urgency_level="High",
                milestone="Rapat Pra-Tender",
                next_action="Follow up secara langsung ke ruangan VP agar persetujuan segera turun"
            ),
            DeadlineModel(
                id=uid(), request_id=req2_id,
                task_name="Penyelesaian Evaluasi Teknis Vendor",
                pic_id="USR-002", pic_name="Rina Gunawan",
                department_id="DEPT-OPS", department_name="Operations",
                target_date=dt_str(-1),
                status="Overdue",
                urgency_level="Critical",
                milestone="Evaluasi Dokumen Penawaran",
                overdue_reason="Sistem eProc sempat down sehingga review tertunda 1 hari kerja",
                next_action="Koordinasi dengan tim teknis untuk memfinalisasi skoring sore ini"
            ),
            DeadlineModel(
                id=uid(), request_id=req3_id,
                task_name="Upload BAST yang sudah ditandatangani FPP",
                pic_id="USR-006", pic_name="Siti Aminah",
                department_id="DEPT-IT", department_name="IT Infrastructure",
                target_date=dt_str(7),
                status="On Track",
                urgency_level="Medium",
                milestone="Serah Terima (BAST)",
                next_action="Minta FPP untuk tanda tangan di halaman 3"
            )
        ]
        session.add_all(deadlines)

        print("Seeding Notifications...")
        notifs = [
            NotificationModel(
                id=uid(), request_id=req2_id,
                title="SLA Overdue: Evaluasi Teknis Vendor",
                description="Tenggat waktu untuk Penyelesaian Evaluasi Teknis Vendor telah terlewati.",
                is_read=False,
                type="deadline", category="Hari Ini"
            ),
            NotificationModel(
                id=uid(), request_id=req2_id,
                title="Jaminan Mendekati Kedaluwarsa",
                description="Jaminan Penawaran dari PT Sejahtera Bersama (BG/MDR/2026/001) akan kedaluwarsa dalam 5 hari.",
                is_read=False,
                type="alert", category="Hari Ini"
            ),
            NotificationModel(
                id=uid(), request_id=req1_id,
                title="SLA At Risk: Persetujuan TOR",
                description="Persetujuan TOR oleh VP Procurement sudah mendekati target (H-2). Mohon segera follow up.",
                is_read=False,
                type="deadline", category="Hari Ini"
            ),
            NotificationModel(
                id=uid(), request_id=req1_id,
                title="Catatan Procurement: RAB Pompa",
                description="Dokumen RAB_Pompa_Sentrifugal.xlsx mendapat catatan dan perlu direvisi.",
                is_read=True,
                type="document", category="Kemarin"
            ),
            NotificationModel(
                id=uid(), request_id=req3_id,
                title="Jaminan Pelaksanaan Telah Expired",
                description="SURETY/JAS/2026/099 dari PT Bangun Karya telah habis masa berlakunya. Segera tindak lanjuti.",
                is_read=True,
                type="alert", category="Lebih Lama"
            )
        ]
        session.add_all(notifs)

        await session.commit()
        print("Seeding completed successfully! System is fully primed for real-world testing.")

if __name__ == "__main__":
    asyncio.run(seed_data())
