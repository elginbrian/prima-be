"""
seed_all.py — Seeder untuk Semua Modul
Termasuk Requests, Milestones, Documents (D2), Guarantees (D3), Deadlines (D4), Notifications, Settings

Jalankan dari root prima-be:
    python seed_all.py
"""
import asyncio
import uuid
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
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from src.infrastructure.models.validation_model import ValidationProfileModel, DocumentValidationLogModel
from src.infrastructure.security.jwt import hash_password

def uid() -> str:
    return str(uuid.uuid4())

def dt(days_offset: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days_offset)

def dt_str(days_offset: int = 0) -> str:
    return (datetime.now() + timedelta(days=days_offset)).strftime("%Y-%m-%d")

async def clear_database(session: AsyncSession):
    tables = [
        "document_validation_logs",
        "validation_profiles",
        "procurement_activity_logs",
        "notifications",
        "documents",
        "guarantees",
        "deadlines",
        "procurement_milestones",
        "procurement_requests",
        "system_settings",
        "users"
    ]
    for table in tables:
        await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    await session.commit()

async def seed_data():
    async with AsyncSessionLocal() as session:
        print("Clearing database...")
        await clear_database(session)

        print("Seeding Users...")
        users = [
            UserModel(
                id="USR-001", name="Budi Santoso", email="budi.santoso@pertamina.com",
                phone="+6281234567890", role="Procurement Officer", status="Active",
                department_id="DEPT-IT", department_name="IT Infrastructure",
                created_at=dt(-200), last_login=dt(-10),
                hashed_password=hash_password("password123")
            ),
            UserModel(
                id="USR-002", name="Rina Gunawan", email="rina.g@pertamina.com",
                phone="+6281298765432", role="Procurement Manager", status="Active",
                department_id="DEPT-OPS", department_name="Operations",
                created_at=dt(-250),
                hashed_password=hash_password("password123")
            ),
            UserModel(
                id="USR-006", name="Siti Aminah", email="siti.aminah@pertamina.com",
                phone="+6287776665554", role="Super Admin", status="Active",
                department_id="DEPT-IT", department_name="IT Infrastructure",
                created_at=dt(-300),
                hashed_password=hash_password("password123")
            ),
            UserModel(
                id="USR-ADMIN", name="Administrator", email="admin@prima.id",
                phone="+628111222333", role="Super Admin", status="Active",
                department_id="DEPT-IT", department_name="IT Infrastructure",
                created_at=dt(-300),
                hashed_password=hash_password("admin123")
            )
        ]
        session.add_all(users)

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
                operational_status="On Going",
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

        print("Seeding SLAs (D4) and Actions per Milestone...")
        deadlines = [
            # SLA for Req 1
            DeadlineModel(id=uid(), request_id=req1_id, task_name="Verifikasi Awal FPP", pic_id="USR-002", pic_name="Rina Gunawan", department_id="DEPT-OPS", department_name="Operations", target_date=dt(-9), status="Selesai", urgency_level="Low", milestone="Penerimaan FPP"),
            DeadlineModel(id=uid(), request_id=req1_id, task_name="Pembuatan Draft TOR", pic_id="USR-001", pic_name="Budi Santoso", department_id="DEPT-IT", department_name="IT Infrastructure", target_date=dt(-6), status="Selesai", urgency_level="Medium", milestone="Pembuatan TOR"),
            DeadlineModel(id=uid(), request_id=req1_id, task_name="Persetujuan TOR dan Anggaran oleh VP", pic_id="USR-001", pic_name="Budi Santoso", department_id="DEPT-IT", department_name="IT Infrastructure", target_date=dt(2), status="At Risk", urgency_level="High", milestone="Rapat Pra-Tender", next_action="Follow up secara langsung ke ruangan VP agar persetujuan segera turun"),
            
            # SLA for Req 2
            DeadlineModel(id=uid(), request_id=req2_id, task_name="Masa Sanggah Pengumuman", pic_id="USR-006", pic_name="Siti Aminah", department_id="DEPT-IT", department_name="IT Infrastructure", target_date=dt(-10), status="Selesai", urgency_level="Low", milestone="Pengumuman Tender"),
            DeadlineModel(id=uid(), request_id=req2_id, task_name="Penutupan Pemasukan Penawaran", pic_id="USR-001", pic_name="Budi Santoso", department_id="DEPT-IT", department_name="IT Infrastructure", target_date=dt(-2), status="Selesai", urgency_level="Medium", milestone="Pemasukan Penawaran"),
            DeadlineModel(id=uid(), request_id=req2_id, task_name="Penyelesaian Evaluasi Teknis Vendor", pic_id="USR-002", pic_name="Rina Gunawan", department_id="DEPT-OPS", department_name="Operations", target_date=dt(-1), status="Overdue", urgency_level="Critical", milestone="Evaluasi Dokumen Penawaran", overdue_reason="Sistem eProc sempat down sehingga review tertunda 1 hari kerja", next_action="Koordinasi dengan tim teknis untuk memfinalisasi skoring sore ini"),
            
            # SLA for Req 3
            DeadlineModel(id=uid(), request_id=req3_id, task_name="Penyusunan Draft Kontrak", pic_id="USR-002", pic_name="Rina Gunawan", department_id="DEPT-OPS", department_name="Operations", target_date=dt(-58), status="Selesai", urgency_level="High", milestone="Penandatanganan Kontrak"),
            DeadlineModel(id=uid(), request_id=req3_id, task_name="Upload BAST yang sudah ditandatangani FPP", pic_id="USR-006", pic_name="Siti Aminah", department_id="DEPT-IT", department_name="IT Infrastructure", target_date=dt(7), status="On Track", urgency_level="Medium", milestone="Serah Terima (BAST)", next_action="Minta FPP untuk tanda tangan di halaman 3")
        ]
        session.add_all(deadlines)

        print("Seeding Guarantees (D3)... Tiap procurement punya jaminan!")
        guarantees = [
            # Guarantee for Req 1 (Even though in Persiapan, let's say they required an early commitment letter)
            GuaranteeModel(
                id=uid(), request_id=req1_id,
                type="Surat Dukungan Bank",
                issuer_type="Bank", issuer="Bank BCA",
                reference_no="SDB/BCA/2026/012", beneficiary="Pertamina Patra Niaga",
                vendor_id="V003", vendor_name="PT Teknologi Sentrifugal",
                value=200_000_000,
                issue_date=dt(-5), expiry_date=dt(60),
                pic_id="USR-001", pic_name="Budi Santoso",
                status="Active"
            ),
            # Guarantee for Req 2
            GuaranteeModel(
                id=uid(), request_id=req2_id,
                type="Jaminan Penawaran",
                issuer_type="Bank", issuer="Bank Mandiri",
                reference_no="BG/MDR/2026/001", beneficiary="Pertamina Patra Niaga",
                vendor_id="V001", vendor_name="PT Sejahtera Bersama",
                value=50_000_000,
                issue_date=dt(-10), expiry_date=dt(5),
                pic_id="USR-006", pic_name="Siti Aminah",
                status="Mendekati Expiry"
            ),
            # Guarantees for Req 3
            GuaranteeModel(
                id=uid(), request_id=req3_id,
                type="Jaminan Pelaksanaan",
                issuer_type="Asuransi", issuer="Asuransi Jasindo",
                reference_no="SURETY/JAS/2026/099", beneficiary="Pertamina Patra Niaga",
                vendor_id="V002", vendor_name="PT Bangun Karya",
                value=775_000_000,
                issue_date=dt(-60), expiry_date=dt(-2),
                pic_id="USR-002", pic_name="Rina Gunawan",
                status="Expired"
            ),
            GuaranteeModel(
                id=uid(), request_id=req3_id,
                type="Jaminan Pemeliharaan",
                issuer_type="Bank", issuer="Bank BRI",
                reference_no="BG/BRI/2026/102", beneficiary="Pertamina Patra Niaga",
                vendor_id="V002", vendor_name="PT Bangun Karya",
                value=300_000_000,
                issue_date=dt(-2), expiry_date=dt(180),
                pic_id="USR-002", pic_name="Rina Gunawan",
                status="Active"
            )
        ]
        session.add_all(guarantees)

        print("Seeding Documents (D2)...")
        doc1_id = uid()
        doc2_id = uid()
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
            )
        ]
        session.add_all(docs)

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

        print("Seeding Activity Logs (D3 Audit Trail)...")
        activity_logs = [
            ProcurementActivityLogModel(
                id=uid(), request_id=req1_id,
                user_id="USR-001", user_name="Budi Santoso",
                action="CREATE",
                previous_state=None, new_state="Persiapan",
                notes="Pengadaan baru dibuat dengan nilai Rp 1.250.000.000",
                created_at=dt(-10)
            ),
            ProcurementActivityLogModel(
                id=uid(), request_id=req1_id,
                user_id="USR-001", user_name="Budi Santoso",
                action="MOVE_STEP",
                previous_state="Rapat Pra-Tender", new_state="Pengumuman Pengadaan",
                notes="Langkah dipindahkan ke Pengumuman Pengadaan",
                created_at=dt(-5)
            ),
            ProcurementActivityLogModel(
                id=uid(), request_id=req2_id,
                user_id="USR-002", user_name="Rina Gunawan",
                action="CREATE",
                previous_state=None, new_state="Persiapan",
                notes="Pengadaan baru dibuat dengan nilai Rp 850.000.000",
                created_at=dt(-14)
            ),
            ProcurementActivityLogModel(
                id=uid(), request_id=req2_id,
                user_id="USR-002", user_name="Rina Gunawan",
                action="UPDATE_STATUS",
                previous_state="On Going", new_state="On Hold",
                notes="Menunggu revisi alokasi pagu anggaran dari Divisi Keuangan. SLA dijeda otomatis.",
                created_at=dt(-2)
            ),
            ProcurementActivityLogModel(
                id=uid(), request_id=req3_id,
                user_id="USR-003", user_name="Ahmad Hidayat",
                action="CREATE",
                previous_state=None, new_state="Persiapan",
                notes="Pengadaan baru dibuat dengan nilai Rp 3.200.000.000",
                created_at=dt(-30)
            ),
            ProcurementActivityLogModel(
                id=uid(), request_id=req3_id,
                user_id="USR-003", user_name="Ahmad Hidayat",
                action="MOVE_STAGE",
                previous_state="Evaluasi", new_state="Contracting",
                notes="Negosiasi selesai, beralih ke penyusunan kontrak",
                created_at=dt(-1)
            ),
        ]
        session.add_all(activity_logs)

        print("Seeding Validation Profiles (Pustaka Standar Kelayakan Dokumen)...")
        profiles = [
            ValidationProfileModel(
                id="VPROF-JAM-PELAKSANAAN",
                name="Standar Jaminan Pelaksanaan Bank Garansi",
                code="STD_JAMINAN_PELAKSANAAN",
                document_kind="Jaminan Pelaksanaan",
                description="Standar verifikasi dan kepatuhan instrumen Bank Garansi Pelaksanaan sesuai pedoman pengadaan PT Pertamina Patra Niaga.",
                scope="GLOBAL",
                passing_score_threshold=80.0,
                warning_score_threshold=60.0,
                strict_mandatory_enforcement=True,
                target_stage_to_clear="Penyusunan RKS & Spesifikasi Teknis",
                custom_system_prompt="Pastikan verifikasi bank penjamin, klausul wanprestasi tanpa syarat, dan kesesuaian nilai nominal terhadap pagu kontrak.",
                checklist_rules=[
                    {
                        "category": "Legalitas & Penerbit",
                        "item": "Penerbit jaminan adalah Bank BUMN / Himbara resmi (Mandiri, BRI, BNI, BTN, BSI)",
                        "guidance": "Periksa nama instansi penerbit. Wajib Bank BUMN atau Bank berperingkat baik.",
                        "is_mandatory": True,
                        "weight": 25,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Legalitas & Klausul",
                        "item": "Mencantumkan klausul klaim tanpa syarat (Unconditional & Irrevocable)",
                        "guidance": "Harus memuat frasa bahwa penjamin akan membayar ganti rugi tanpa syarat atas tuntutan pertama.",
                        "is_mandatory": True,
                        "weight": 30,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Finansial & Nilai",
                        "item": "Nilai nominal jaminan minimal 5% dari nilai kontrak pengadaan",
                        "guidance": "Cek kesesuaian angka dan huruf nilai penjaminan dalam mata uang IDR/USD.",
                        "is_mandatory": True,
                        "weight": 25,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Masa Berlaku",
                        "item": "Masa berlaku jaminan minimal sama dengan jangka waktu kontrak ditambah 14 hari",
                        "guidance": "Cek tanggal mulai dan jatuh tempo jaminan.",
                        "is_mandatory": True,
                        "weight": 20,
                        "severity_on_failure": "WARNING"
                    }
                ],
                is_default=True,
                is_active=True,
                created_by_id="USR-001",
                created_by_name="Budi Santoso",
                created_at=dt(-30),
                updated_at=dt(-30),
            ),
            ValidationProfileModel(
                id="VPROF-KAK-TEKNIS",
                name="Standar Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                code="STD_KAK_TEKNIS",
                document_kind="Kerangka Acuan Kerja",
                description="Standar kelayakan Kerangka Acuan Kerja dan spesifikasi teknis barang/jasa sebelum pengumuman tender.",
                scope="GLOBAL",
                passing_score_threshold=75.0,
                warning_score_threshold=60.0,
                strict_mandatory_enforcement=True,
                target_stage_to_clear="Penyusunan RKS & Spesifikasi Teknis",
                custom_system_prompt="Pastikan KAK memiliki ruang lingkup yang terukur, estimasi jadwal, dan tidak diskriminatif.",
                checklist_rules=[
                    {
                        "category": "Ruang Lingkup",
                        "item": "Uraian ruang lingkup kebutuhan, deliverable pekerjaan, dan spesifikasi teknis jelas",
                        "guidance": "Periksa bab lingkup kerja dan rincian keluaran pekerjaan.",
                        "is_mandatory": True,
                        "weight": 30,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Objektivitas Spesifikasi",
                        "item": "Spesifikasi tidak mengunci pada merek dagang tertentu kecuali suku cadang OEM",
                        "guidance": "Pastikan spesifikasi teknis bersifat terbuka dan kompetitif.",
                        "is_mandatory": True,
                        "weight": 25,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Jadwal & Waktu",
                        "item": "Jadwal pelaksanaan pekerjaan dan tahapan milestone realistis",
                        "guidance": "Cek tabel timeline atau durasi hari kalender pemenuhan.",
                        "is_mandatory": True,
                        "weight": 25,
                        "severity_on_failure": "WARNING"
                    },
                    {
                        "category": "Aspek HSSE & Garansi",
                        "item": "Memuat klausul kepatuhan aspek K3LL/HSSE dan ketentuan garansi purna jual",
                        "guidance": "Periksa komitmen keselamatan kerja dan masa garansi minimal 1 tahun.",
                        "is_mandatory": False,
                        "weight": 20,
                        "severity_on_failure": "WARNING"
                    }
                ],
                is_default=True,
                is_active=True,
                created_by_id="USR-001",
                created_by_name="Budi Santoso",
                created_at=dt(-30),
                updated_at=dt(-30),
            ),
            ValidationProfileModel(
                id="VPROF-PENAWARAN-VENDOR",
                name="Standar Evaluasi Dokumen Penawaran Teknis & Harga",
                code="STD_PENAWARAN_VENDOR",
                document_kind="Dokumen Penawaran",
                description="Standar verifikasi kelengkapan administrasi dan penawaran harga penyedia barang/jasa.",
                scope="GLOBAL",
                passing_score_threshold=80.0,
                warning_score_threshold=60.0,
                strict_mandatory_enforcement=True,
                target_stage_to_clear="Pemasukan Dokumen Penawaran",
                custom_system_prompt="Verifikasi tanda tangan direksi, meterai, rincian harga satuan, dan pakta integritas.",
                checklist_rules=[
                    {
                        "category": "Administrasi & Legalitas",
                        "item": "Surat penawaran bertanggal, bermeterai, dan ditandatangani pejabat berwenang",
                        "guidance": "Periksa keabsahan tanda tangan direktur dan cap perusahaan.",
                        "is_mandatory": True,
                        "weight": 30,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Finansial & Pajak",
                        "item": "Rincian harga satuan lengkap dan mencantumkan perhitungan PPN 11%",
                        "guidance": "Pastikan harga satuan tidak kosong dan breakdown pajak jelas.",
                        "is_mandatory": True,
                        "weight": 35,
                        "severity_on_failure": "ERROR"
                    },
                    {
                        "category": "Masa Berlaku Penawaran",
                        "item": "Masa berlaku penawaran harga minimal 60 hari kalender",
                        "guidance": "Cek pernyataan masa laku harga pada surat penawaran.",
                        "is_mandatory": True,
                        "weight": 20,
                        "severity_on_failure": "WARNING"
                    },
                    {
                        "category": "Pakta Integritas",
                        "item": "Melampirkan lembar Pakta Integritas bebas benturan kepentingan",
                        "guidance": "Periksa lampiran pakta integritas resmi.",
                        "is_mandatory": False,
                        "weight": 15,
                        "severity_on_failure": "WARNING"
                    }
                ],
                is_default=True,
                is_active=True,
                created_by_id="USR-001",
                created_by_name="Budi Santoso",
                created_at=dt(-30),
                updated_at=dt(-30),
            )
        ]
        session.add_all(profiles)
        await session.flush()

        print("Seeding Document Validation Logs (D1 Audit Trail)...")
        validation_logs = [
            DocumentValidationLogModel(
                id="VAL-TOR-001",
                request_id=req1_id,
                document_id=doc1_id,
                profile_id="VPROF-KAK-TEKNIS",
                profile_name="Standar Kerangka Acuan Kerja (KAK) & Spesifikasi Teknis",
                document_name="TOR_Pompa_Sentrifugal.pdf",
                document_file_url="https://example.com/doc1",
                mime_type="application/pdf",
                user_prompt="Pastikan standar API 610 untuk pompa sentrifugal kilang RU-IV Cilacap terpenuhi.",
                checklist_snapshot=[
                    "Uraian ruang lingkup kebutuhan, deliverable pekerjaan, dan spesifikasi teknis jelas",
                    "Spesifikasi tidak mengunci pada merek dagang tertentu kecuali suku cadang OEM",
                    "Jadwal pelaksanaan pekerjaan dan tahapan milestone realistis",
                    "Memuat klausul kepatuhan aspek K3LL/HSSE dan ketentuan garansi purna jual",
                ],
                validation_result={
                    "overall_score": 95.0,
                    "summary": "Dokumen TOR_Pompa_Sentrifugal.pdf telah memenuhi seluruh syarat kelayakan teknis dan aspek HSSE sesuai standar PT Pertamina Patra Niaga (Skor 95/100).",
                    "checklist_evaluations": [
                        {
                            "item": "Uraian ruang lingkup kebutuhan, deliverable pekerjaan, dan spesifikasi teknis jelas",
                            "status": "Memenuhi",
                            "evidence_quote": "Bab II Lingkup Pekerjaan: Pengadaan 2 unit Heavy Duty Centrifugal Pump sesuai standar API 610 tipe OH2 lengkap dengan instalasi dan commissioning di Unit RU-IV Cilacap.",
                            "explanation": "Ruang lingkup teknis, kapasitas aliran, dan standar rekayasa API 610 diuraikan secara lengkap.",
                            "severity": "SUCCESS",
                            "is_mandatory": True,
                        },
                        {
                            "item": "Spesifikasi tidak mengunci pada merek dagang tertentu kecuali suku cadang OEM",
                            "status": "Memenuhi",
                            "evidence_quote": "Bab III Spesifikasi Material: Menggunakan parameter performa minimum tanpa penyebutan merek tunggal.",
                            "explanation": "Spesifikasi bersifat terbuka dan mendukung kompetisi sehat.",
                            "severity": "SUCCESS",
                            "is_mandatory": True,
                        },
                        {
                            "item": "Jadwal pelaksanaan pekerjaan dan tahapan milestone realistis",
                            "status": "Memenuhi",
                            "evidence_quote": "Bab V Jadwal Pelaksanaan: Total waktu pengiriman dan instalasi 120 hari kalender sejak SPK.",
                            "explanation": "Timeline tahapan fabrikasi, FAT, delivery, dan BAST terukur dengan jelas.",
                            "severity": "SUCCESS",
                            "is_mandatory": True,
                        },
                        {
                            "item": "Memuat klausul kepatuhan aspek K3LL/HSSE dan ketentuan garansi purna jual",
                            "status": "Memenuhi",
                            "evidence_quote": "Bab VI Ketentuan CSMS & Garansi: Penyedia wajib memenuhi kualifikasi CSMS Risiko Tinggi dan garansi performa 12 bulan.",
                            "explanation": "Klausul K3LL dan garansi purna jual sudah tercantum.",
                            "severity": "SUCCESS",
                            "is_mandatory": False,
                        },
                    ],
                    "recommendations": [
                        "Dokumen TOR sudah sangat lengkap dan layak diteruskan ke tahapan Rapat Pra-Tender.",
                        "Pastikan lampiran datasheet teknis pompa disertakan saat undangan aanwijzing.",
                    ],
                    "extracted_project": {
                        "title": "Pengadaan Pompa Sentrifugal Unit RU-IV Cilacap",
                        "estimated_amount": 4_800_000_000,
                        "suggested_method": "Tender Terbuka",
                        "department_name": "IT Infrastructure",
                        "stages": [
                            {"step": "Penerimaan FPP", "status": "Done", "auto_cleared": True, "notes": "Diterima oleh Procurement"},
                            {"step": "Pembuatan TOR", "status": "Done", "auto_cleared": True, "notes": "Auto-cleared melalui validasi AI TOR (95/100)"},
                            {"step": "Rapat Pra-Tender", "status": "In Progress", "auto_cleared": False, "notes": "Menunggu finalisasi RAB"},
                            {"step": "Pengumuman Pengadaan", "status": "Pending", "auto_cleared": False, "notes": None},
                        ],
                    },
                },
                overall_score=95.0,
                passing_score_threshold=75.0,
                compliance_status="Lulus Verifikasi",
                validated_by_id="USR-001",
                validated_by_name="Budi Santoso",
                created_at=dt(-7),
            ),
            DocumentValidationLogModel(
                id="VAL-RAB-002",
                request_id=req1_id,
                document_id=doc2_id,
                profile_id="VPROF-PENAWARAN-VENDOR",
                profile_name="Standar Evaluasi Dokumen Penawaran Teknis & Harga",
                document_name="RAB_Pompa_Sentrifugal.xlsx",
                document_file_url="https://example.com/doc2",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                user_prompt="Periksa rincian harga satuan pompa dan komponen PPN 11%.",
                checklist_snapshot=[
                    "Rincian harga satuan lengkap dan mencantumkan perhitungan PPN 11%",
                    "Harga satuan mengacu pada referensi HPS dan e-Catalog terbaru",
                    "Otorisasi penyusun RAB dan persetujuan fungsi pemohon",
                ],
                validation_result={
                    "overall_score": 68.0,
                    "summary": "Dokumen RAB_Pompa_Sentrifugal.xlsx berstatus Catatan Procurement (Skor 68/100). Ditemukan selisih referensi harga satuan HPS dan komponen PPN 11% yang belum dirinci.",
                    "checklist_evaluations": [
                        {
                            "item": "Rincian harga satuan lengkap dan mencantumkan perhitungan PPN 11%",
                            "status": "Perlu Perhatian",
                            "evidence_quote": "Sheet Rekapitulasi Baris 24: Total Harga Belum Termasuk Pajak",
                            "explanation": "Baris rekapitulasi akhir belum menambahkan perhitungan PPN 11% secara eksplisit.",
                            "severity": "WARNING",
                            "is_mandatory": True,
                        },
                        {
                            "item": "Harga satuan mengacu pada referensi HPS dan e-Catalog terbaru",
                            "status": "Perlu Perhatian",
                            "evidence_quote": "Item 1.2 Mechanical Seal Assembly: Rp 185.000.000",
                            "explanation": "Harga satuan pompa dan mechanical seal masih mengacu pada kontrak tahun 2024, perlu pembaruan HPS 2026.",
                            "severity": "WARNING",
                            "is_mandatory": True,
                        },
                        {
                            "item": "Otorisasi penyusun RAB dan persetujuan fungsi pemohon",
                            "status": "Memenuhi",
                            "evidence_quote": "Disusun oleh Lead Engineer RU-IV Cilacap",
                            "explanation": "Telah memuat nama dan jabatan penyusun dari fungsi teknis.",
                            "severity": "SUCCESS",
                            "is_mandatory": False,
                        },
                    ],
                    "recommendations": [
                        "Revisi RAB dengan memasukkan baris perhitungan PPN 11% pada rekapitulasi total.",
                        "Lampirkan kuotasi pembanding terbaru untuk pembaruan harga satuan HPS.",
                    ],
                    "extracted_project": {
                        "title": "Pengadaan Pompa Sentrifugal Unit RU-IV Cilacap",
                        "estimated_amount": 4_800_000_000,
                        "suggested_method": "Tender Terbuka",
                        "department_name": "IT Infrastructure",
                        "stages": [
                            {"step": "Penerimaan FPP", "status": "Done", "auto_cleared": True, "notes": "Diterima oleh Procurement"},
                            {"step": "Pembuatan TOR", "status": "Done", "auto_cleared": True, "notes": "TOR sudah diverifikasi"},
                            {"step": "Rapat Pra-Tender", "status": "In Progress", "auto_cleared": False, "notes": "Menunggu revisi RAB"},
                        ],
                    },
                },
                overall_score=68.0,
                passing_score_threshold=80.0,
                compliance_status="Catatan Procurement",
                validated_by_id="USR-001",
                validated_by_name="Budi Santoso",
                created_at=dt(-2),
            ),
        ]
        session.add_all(validation_logs)

        await session.commit()
        print("Seeding completed successfully! System is fully primed for real-world testing.")

if __name__ == "__main__":
    asyncio.run(seed_data())
