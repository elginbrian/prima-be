"""
seed_d3.py — Seeder untuk Modul D3 (Procurement Requests & Milestones)

Jalankan dari root prima-be:
    python seed_d3.py

Data mencerminkan pengadaan barang/jasa Pertamina Patra Niaga dengan
berbagai tahap, status, dan urgensi.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models.procurement_model import (
    ProcurementRequestModel,
    ProcurementMilestoneModel,
)

# ─── Helper ───────────────────────────────────────────────────────────────────

def uid() -> str:
    return str(uuid.uuid4())

def dt(days_ago: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


# ─── Seed Data ────────────────────────────────────────────────────────────────

REQUESTS = [
    # 1 — Tahap Persiapan (Rapat Pra-Tender), On Going, Urgent
    {
        "id": uid(),
        "title": "Pengadaan Pompa Sentrifugal Unit RU-IV Cilacap",
        "pic_id": "U001", "pic_name": "Eka Budi Santoso",
        "fpp_id": "U002", "fpp_name": "Dewi Rahayu",
        "amount": 4_800_000_000,
        "stage": "Persiapan",
        "operational_status": "On Going",
        "current_step": "Rapat Pra-Tender",
        "department_id": "D001", "department_name": "Procurement",
        "is_urgent": True,
        "stage_started_at": dt(5),
        "milestones": [
            {"step": "Rapat Pra-Tender", "status": "In Progress", "notes": "Agenda: review TOR & anggaran awal"},
        ],
    },

    # 2 — Tahap Sourcing (Pengumuman Pengadaan), On Going
    {
        "id": uid(),
        "title": "Jasa Pemeliharaan Sistem Instrumentasi Kilang Balikpapan",
        "pic_id": "U003", "pic_name": "Firmansyah Putra",
        "fpp_id": "U004", "fpp_name": "Siti Aisyah",
        "amount": 12_500_000_000,
        "stage": "Sourcing",
        "operational_status": "On Going",
        "current_step": "Pengumuman Pengadaan",
        "department_id": "D002", "department_name": "Engineering",
        "is_urgent": False,
        "stage_started_at": dt(18),
        "milestones": [
            {"step": "Rapat Pra-Tender",        "status": "Done",        "date": dt(25), "notes": "TOR disetujui VP Supply"},
            {"step": "Pengumuman Pengadaan",     "status": "In Progress", "date": dt(18), "notes": "Tayang di LPSE & portal Pertamina"},
        ],
    },

    # 3 — Tahap Sourcing (Prebid Meeting), On Going, Urgent
    {
        "id": uid(),
        "title": "Pengadaan Katalis Reforming Unit Pertamina Plaju",
        "pic_id": "U005", "pic_name": "Raden Mas Hendri",
        "fpp_id": "U006", "fpp_name": "Yuliana Sari",
        "amount": 32_000_000_000,
        "stage": "Sourcing",
        "operational_status": "On Going",
        "current_step": "Prebid Meeting",
        "department_id": "D003", "department_name": "Refinery Operations",
        "is_urgent": True,
        "stage_started_at": dt(30),
        "milestones": [
            {"step": "Rapat Pra-Tender",        "status": "Done",        "date": dt(40), "notes": "Budget Rp 32M disetujui"},
            {"step": "Pengumuman Pengadaan",     "status": "Done",        "date": dt(30), "notes": "10 vendor terundang"},
            {"step": "Prebid Meeting",           "status": "In Progress", "date": dt(5),  "notes": "8 vendor hadir, 3 pertanyaan teknis"},
        ],
    },

    # 4 — Tahap Evaluasi (Evaluasi Dokumen Penawaran), On Going
    {
        "id": uid(),
        "title": "Pengadaan Suku Cadang Turbin Gas PLTGU Muara Karang",
        "pic_id": "U001", "pic_name": "Eka Budi Santoso",
        "fpp_id": "U007", "fpp_name": "Bambang Widodo",
        "amount": 8_750_000_000,
        "stage": "Evaluasi",
        "operational_status": "On Going",
        "current_step": "Evaluasi Dokumen Penawaran",
        "department_id": "D004", "department_name": "Asset Management",
        "is_urgent": False,
        "stage_started_at": dt(45),
        "milestones": [
            {"step": "Rapat Pra-Tender",              "status": "Done",        "date": dt(60)},
            {"step": "Pengumuman Pengadaan",           "status": "Done",        "date": dt(50)},
            {"step": "Prebid Meeting",                 "status": "Done",        "date": dt(42)},
            {"step": "Pemasukan Dokumen Penawaran",    "status": "Done",        "date": dt(35), "notes": "5 penawaran masuk"},
            {"step": "Pembukaan Penawaran",            "status": "Done",        "date": dt(30), "notes": "Harga terendah: Rp 7,2M (PT Maju Jaya)"},
            {"step": "Evaluasi Dokumen Penawaran",     "status": "In Progress", "date": dt(7),  "notes": "Evaluasi teknis 60% selesai"},
        ],
    },

    # 5 — Tahap Evaluasi, On Hold
    {
        "id": uid(),
        "title": "Jasa Cleaning Tangki Storage Terminal BBM Surabaya",
        "pic_id": "U008", "pic_name": "Ahmad Fauzi",
        "fpp_id": "U009", "fpp_name": "Nurul Hidayat",
        "amount": 2_200_000_000,
        "stage": "Evaluasi",
        "operational_status": "On Hold",
        "operational_status_reason": "Menunggu persetujuan revisi spesifikasi teknis dari tim HSE.",
        "current_step": "Sosialisasi e-Auction",
        "department_id": "D005", "department_name": "Terminal & Distribution",
        "is_urgent": False,
        "stage_started_at": dt(55),
        "milestones": [
            {"step": "Rapat Pra-Tender",              "status": "Done",    "date": dt(70)},
            {"step": "Pengumuman Pengadaan",           "status": "Done",    "date": dt(60)},
            {"step": "Prebid Meeting",                 "status": "Done",    "date": dt(52)},
            {"step": "Pemasukan Dokumen Penawaran",    "status": "Done",    "date": dt(45)},
            {"step": "Pembukaan Penawaran",            "status": "Done",    "date": dt(40)},
            {"step": "Evaluasi Dokumen Penawaran",     "status": "Done",    "date": dt(35)},
            {"step": "Sosialisasi e-Auction",          "status": "In Progress", "notes": "Ditunda karena revisi spek HSE"},
        ],
    },

    # 6 — Tahap Contracting (Negosiasi e-Auction), On Going
    {
        "id": uid(),
        "title": "Pengadaan Chemical Treatment Water Injection PT Pertamina EP",
        "pic_id": "U010", "pic_name": "Dian Pramono",
        "fpp_id": "U011", "fpp_name": "Retno Wulandari",
        "amount": 6_300_000_000,
        "stage": "Contracting",
        "operational_status": "On Going",
        "current_step": "Negosiasi e-Auction",
        "department_id": "D001", "department_name": "Procurement",
        "is_urgent": False,
        "stage_started_at": dt(80),
        "milestones": [
            {"step": "Rapat Pra-Tender",              "status": "Done", "date": dt(95)},
            {"step": "Pengumuman Pengadaan",           "status": "Done", "date": dt(88)},
            {"step": "Prebid Meeting",                 "status": "Done", "date": dt(80)},
            {"step": "Pemasukan Dokumen Penawaran",    "status": "Done", "date": dt(72)},
            {"step": "Pembukaan Penawaran",            "status": "Done", "date": dt(65)},
            {"step": "Evaluasi Dokumen Penawaran",     "status": "Done", "date": dt(58)},
            {"step": "Sosialisasi e-Auction",          "status": "Done", "date": dt(50)},
            {"step": "Negosiasi e-Auction",            "status": "In Progress", "date": dt(3), "notes": "Putaran ke-2, selisih 3% dari floor price"},
        ],
    },

    # 7 — Tahap Contracting (Laporan Hasil Pemilihan), On Going, Urgent
    {
        "id": uid(),
        "title": "Jasa Inspeksi Pipa Bawah Laut Blok Mahakam",
        "pic_id": "U003", "pic_name": "Firmansyah Putra",
        "fpp_id": "U012", "fpp_name": "Agus Setiawan",
        "amount": 55_000_000_000,
        "stage": "Contracting",
        "operational_status": "On Going",
        "current_step": "Laporan Hasil Pemilihan",
        "department_id": "D006", "department_name": "Upstream Operations",
        "is_urgent": True,
        "stage_started_at": dt(100),
        "milestones": [
            {"step": "Rapat Pra-Tender",              "status": "Done", "date": dt(120)},
            {"step": "Pengumuman Pengadaan",           "status": "Done", "date": dt(110)},
            {"step": "Prebid Meeting",                 "status": "Done", "date": dt(100)},
            {"step": "Pemasukan Dokumen Penawaran",    "status": "Done", "date": dt(90)},
            {"step": "Pembukaan Penawaran",            "status": "Done", "date": dt(82)},
            {"step": "Evaluasi Dokumen Penawaran",     "status": "Done", "date": dt(72)},
            {"step": "Sosialisasi e-Auction",          "status": "Done", "date": dt(62)},
            {"step": "Negosiasi e-Auction",            "status": "Done", "date": dt(55)},
            {"step": "Laporan Hasil Pemilihan",        "status": "In Progress", "date": dt(2), "notes": "Draft LHP sedang review legal"},
        ],
    },

    # 8 — Selesai (Penunjukan Pemenang)
    {
        "id": uid(),
        "title": "Pengadaan Alat Pelindung Diri (APD) Standar MIGAS 2026",
        "pic_id": "U008", "pic_name": "Ahmad Fauzi",
        "fpp_id": "U002", "fpp_name": "Dewi Rahayu",
        "amount": 985_000_000,
        "stage": "Selesai",
        "operational_status": "On Going",
        "current_step": "Penunjukan Pemenang",
        "department_id": "D007", "department_name": "HSE",
        "is_urgent": False,
        "stage_started_at": dt(150),
        "milestones": [
            {"step": "Rapat Pra-Tender",              "status": "Done", "date": dt(165)},
            {"step": "Pengumuman Pengadaan",           "status": "Done", "date": dt(155)},
            {"step": "Prebid Meeting",                 "status": "Done", "date": dt(148)},
            {"step": "Pemasukan Dokumen Penawaran",    "status": "Done", "date": dt(140)},
            {"step": "Pembukaan Penawaran",            "status": "Done", "date": dt(133)},
            {"step": "Evaluasi Dokumen Penawaran",     "status": "Done", "date": dt(125)},
            {"step": "Sosialisasi e-Auction",          "status": "Skipped", "notes": "Nilai < 5M, negosiasi manual"},
            {"step": "Negosiasi Manual",               "status": "Done", "date": dt(118), "notes": "Harga final Rp 940M"},
            {"step": "Laporan Hasil Pemilihan",        "status": "Done", "date": dt(110)},
            {"step": "Pengumuman Pemenang",            "status": "Done", "date": dt(105), "notes": "PT Safety Prima Indonesia"},
            {"step": "Penunjukan Pemenang",            "status": "Done", "date": dt(100), "notes": "SPK No. 1234/PRC/2026 diterbitkan"},
        ],
    },

    # 9 — Batal
    {
        "id": uid(),
        "title": "Pengadaan Sistem SCADA Terpusat Depot Plumpang",
        "pic_id": "U005", "pic_name": "Raden Mas Hendri",
        "fpp_id": "U013", "fpp_name": "Lia Permatasari",
        "amount": 18_000_000_000,
        "stage": "Sourcing",
        "operational_status": "Batal",
        "operational_status_reason": "Proyek dialihkan ke program digitalisasi pusat PHE.",
        "current_step": "Pengumuman Pengadaan",
        "department_id": "D008", "department_name": "ICT",
        "is_urgent": False,
        "stage_started_at": dt(90),
        "milestones": [
            {"step": "Rapat Pra-Tender",        "status": "Done",    "date": dt(100)},
            {"step": "Pengumuman Pengadaan",     "status": "Done",    "date": dt(90)},
            {"step": "Prebid Meeting",           "status": "Skipped", "notes": "Dibatalkan sebelum Prebid"},
        ],
    },

    # 10 — Tahap Persiapan, On Going
    {
        "id": uid(),
        "title": "Jasa Konsultansi Feasibility Study Terminal LNG Bontang Ekspansi",
        "pic_id": "U010", "pic_name": "Dian Pramono",
        "fpp_id": "U014", "fpp_name": "Hendra Kusuma",
        "amount": 3_400_000_000,
        "stage": "Persiapan",
        "operational_status": "On Going",
        "current_step": "Rapat Pra-Tender",
        "department_id": "D009", "department_name": "Business Development",
        "is_urgent": False,
        "stage_started_at": dt(2),
        "milestones": [
            {"step": "Rapat Pra-Tender", "status": "In Progress", "notes": "Kick-off meeting dengan konsultan independen"},
        ],
    },
]


# ─── Main Seeder ──────────────────────────────────────────────────────────────

from sqlalchemy import select

async def seed():
    print("Seeding D3 Procurement data...")

    async with AsyncSessionLocal() as session:  # type: AsyncSession
        # Check if already seeded
        result = await session.execute(select(ProcurementRequestModel).limit(1))
        if result.scalars().first():
            print("Data already exists. Skipping seed.")
            return

        for req_data in REQUESTS:
            milestones_data = req_data.pop("milestones", [])

            req = ProcurementRequestModel(**req_data)
            session.add(req)

            for m in milestones_data:
                milestone = ProcurementMilestoneModel(
                    id=uid(),
                    request_id=req.id,
                    step=m["step"],
                    status=m["status"],
                    date=m.get("date"),
                    pic_id=m.get("pic_id"),
                    pic_name=m.get("pic_name"),
                    notes=m.get("notes"),
                )
                session.add(milestone)

        await session.commit()

    print(f"Done! {len(REQUESTS)} procurement requests seeded with milestones.")


if __name__ == "__main__":
    asyncio.run(seed())
