"""
PRIMA n8n Event Catalog, URL validation, and Payload Envelope Builders.
"""
from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

N8N_EVENTS_CATALOG: List[Dict[str, Any]] = [
    # ─── PENGADAAN ────────────────────────────────────────────────────────────
    {
        "event": "procurement.created",
        "category": "Pengadaan",
        "label": "Paket Pengadaan Baru Dibuat",
        "description": "Dipicu saat pekerjaan pengadaan baru dibuat di PRIMA (manual atau via AI/MCP).",
        "recommended_for": "Buat folder arsip Google Drive & baris baru Google Sheets",
    },
    {
        "event": "procurement.stage_changed",
        "category": "Pengadaan",
        "label": "Tahap / Step Pengadaan Berubah",
        "description": "Dipicu saat pekerjaan berpindah stage atau current_step.",
        "recommended_for": "Update kolom status & progres di Google Sheets",
    },
    {
        "event": "procurement.status_changed",
        "category": "Pengadaan",
        "label": "Status Operasional Berubah",
        "description": "Dipicu saat status operasional berubah antara On Going, On Hold, atau Batal.",
        "recommended_for": "Sinkronisasi status pekerjaan & alert manajerial",
    },
    {
        "event": "procurement.pic_assigned",
        "category": "Pengadaan",
        "label": "Serah Terima / Penggantian PIC",
        "description": "Dipicu saat PIC pekerjaan didelegasikan atau diganti ke personel lain.",
        "recommended_for": "Notifikasi ke PIC baru via WhatsApp / Email / Teams",
    },
    # ─── DOKUMEN & VALIDASI AI ────────────────────────────────────────────────
    {
        "event": "document.uploaded",
        "category": "Dokumen & Validasi",
        "label": "Dokumen Baru Ditambahkan",
        "description": "Dipicu saat metadata dokumen pengadaan baru disimpan di PRIMA.",
        "recommended_for": "Catat log dokumen masuk di Google Sheets",
    },
    {
        "event": "document.revised",
        "category": "Dokumen & Validasi",
        "label": "Revisi Dokumen Diunggah",
        "description": "Dipicu saat versi revisi baru (v2, v3, dst.) dari dokumen diunggah.",
        "recommended_for": "Notifikasi tim reviewer bahwa revisi siap diperiksa",
    },
    {
        "event": "document.status_changed",
        "category": "Dokumen & Validasi",
        "label": "Status Verifikasi Dokumen Diperbarui",
        "description": "Dipicu saat status dokumen diubah (mis. Lulus Verifikasi, Tindak Lanjut FPP).",
        "recommended_for": "Auto-archive PDF yang Lulus Verifikasi ke Google Drive",
    },
    {
        "event": "validation.completed",
        "category": "Dokumen & Validasi",
        "label": "Validasi Checklist AI Selesai",
        "description": "Dipicu ketika proses analisis dokumen AI selesai beserta skor & status kepatuhan.",
        "recommended_for": "Alert jika skor di bawah standar atau kirim ringkasan ke tim",
    },
    {
        "event": "validation.decision_updated",
        "category": "Dokumen & Validasi",
        "label": "Keputusan Reviewer Validasi Diubah",
        "description": "Dipicu saat reviewer memperbarui keputusan akhir pada log validasi dokumen.",
        "recommended_for": "Auto-archive ke Google Drive saat reviewer meluluskan dokumen",
    },
    {
        "event": "validation.published",
        "category": "Dokumen & Validasi",
        "label": "Hasil Validasi Dipublish ke Tracker",
        "description": "Dipicu saat dokumen tervalidasi diterbitkan menjadi paket aktif di Tracker.",
        "recommended_for": "Buat folder Drive + catat entri Tracker di Google Sheets",
    },
    # ─── SLA & DEADLINES ──────────────────────────────────────────────────────
    {
        "event": "deadline.created",
        "category": "SLA & Deadline",
        "label": "Deadline SLA Baru Dibuat",
        "description": "Dipicu saat target deadline SLA baru ditambahkan untuk pekerjaan.",
        "recommended_for": "Buat event jadwal & pengingat di Google Calendar",
    },
    {
        "event": "deadline.updated",
        "category": "SLA & Deadline",
        "label": "Deadline SLA Diperbarui",
        "description": "Dipicu saat tanggal target atau status deadline diubah.",
        "recommended_for": "Perbarui event yang sesuai di Google Calendar",
    },
    {
        "event": "sla.at_risk",
        "category": "SLA & Deadline",
        "label": "SLA Mendekati Batas (At Risk)",
        "description": "Dipicu saat evaluasi SLA mendeteksi sisa hari masuk ambang batas peringatan.",
        "recommended_for": "Kirim pengingat dini ke PIC via Email / WhatsApp",
    },
    {
        "event": "sla.overdue",
        "category": "SLA & Deadline",
        "label": "SLA Terlambat (Overdue)",
        "description": "Dipicu saat evaluasi SLA mendeteksi deadline melewati target_date.",
        "recommended_for": "Tandai overdue di Google Sheets & kirim alert tim",
    },
    {
        "event": "sla.escalated",
        "category": "SLA & Deadline",
        "label": "Eskalasi SLA ke Manajer",
        "description": "Dipicu saat eskalasi SLA terjadi (otomatis maupun manual).",
        "recommended_for": "Alert prioritas tinggi ke Procurement Manager & update Calendar",
    },
    {
        "event": "sla.recovery_plan_submitted",
        "category": "SLA & Deadline",
        "label": "Recovery Plan SLA Diajukan",
        "description": "Dipicu saat PIC mengirimkan rencana pemulihan dan tanggal target baru.",
        "recommended_for": "Catat target pemulihan di Google Calendar & Sheets",
    },
    # ─── JAMINAN BANK ─────────────────────────────────────────────────────────
    {
        "event": "guarantee.created",
        "category": "Jaminan Bank",
        "label": "Jaminan Bank Baru Dicatat",
        "description": "Dipicu saat jaminan (penawaran/pelaksanaan/pemeliharaan) baru disimpan.",
        "recommended_for": "Buat event jatuh tempo di Google Calendar & catat di Google Sheets",
    },
    {
        "event": "guarantee.amended",
        "category": "Jaminan Bank",
        "label": "Jaminan Diperpanjang / Diamandemen",
        "description": "Dipicu saat expiry_date atau nilai jaminan diperbarui/diamandemen.",
        "recommended_for": "Update tanggal jatuh tempo di Google Calendar & Sheets",
    },
    {
        "event": "guarantee.claimed_or_released",
        "category": "Jaminan Bank",
        "label": "Klaim atau Pengembalian Jaminan",
        "description": "Dipicu saat jaminan diajukan klaim atau dikembalikan (BAST).",
        "recommended_for": "Update status akhir jaminan di Google Sheets & arsip BAST",
    },
    {
        "event": "guarantee.expiring_soon",
        "category": "Jaminan Bank",
        "label": "Jaminan Akan Kedaluwarsa",
        "description": "Dipicu oleh evaluasi masa berlaku jaminan (manual atau jadwal n8n).",
        "recommended_for": "Kirim peringatan perpanjangan warkat ke PIC & vendor",
    },
]

ALL_N8N_EVENT_KEYS: List[str] = [item["event"] for item in N8N_EVENTS_CATALOG]

_BLOCKED_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def validate_webhook_url(raw_url: str) -> str:
    """Validates webhook destination URL and blocks dangerous metadata endpoints."""
    url = (raw_url or "").strip()
    if not url:
        raise ValueError("URL webhook n8n wajib diisi.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL webhook harus diawali http:// atau https://.")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL webhook tidak valid (hostname tidak ditemukan).")
    hostname = parsed.hostname.lower()
    if hostname in _BLOCKED_METADATA_HOSTS:
        raise ValueError("Host tujuan tidak diizinkan untuk keamanan infrastruktur.")
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if ip_obj.is_link_local or ip_obj.is_multicast:
            raise ValueError("Alamat IP link-local/multicast tidak diizinkan.")
    except ValueError as exc:
        # Not an IP literal -> hostname string is fine unless it was an explicit security rejection above
        if "tidak diizinkan" in str(exc):
            raise
    return url


def build_event_envelope(
    event_name: str,
    data: Dict[str, Any],
    *,
    actor: Optional[Dict[str, Optional[str]]] = None,
    links: Optional[Dict[str, Optional[str]]] = None,
    delivery_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Constructs a consistent JSON webhook payload envelope for n8n workflows."""
    return {
        "event_id": delivery_id or f"evt_{uuid4().hex[:16]}",
        "event": event_name,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source": "prima",
        "actor": actor or {"id": None, "name": "PRIMA System"},
        "data": data,
        "links": links or {},
    }


def serialize_procurement_payload(entity: Any, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extracts a clean serializable dict from a ProcurementRequest domain entity."""
    payload: Dict[str, Any] = {
        "id": getattr(entity, "id", None),
        "title": getattr(entity, "title", None),
        "stage": getattr(entity, "stage", None),
        "current_step": getattr(entity, "current_step", None),
        "operational_status": getattr(entity, "operational_status", None),
        "procurement_method": getattr(entity, "procurement_method", None),
        "amount": getattr(entity, "amount", None),
        "is_urgent": getattr(entity, "is_urgent", False),
        "pic_id": getattr(getattr(entity, "pic", None), "id", None),
        "pic_name": getattr(getattr(entity, "pic", None), "name", None),
        "fpp_id": getattr(getattr(entity, "fpp", None), "id", None),
        "fpp_name": getattr(getattr(entity, "fpp", None), "name", None),
        "department_id": getattr(getattr(entity, "department", None), "id", None),
        "department_name": getattr(getattr(entity, "department", None), "name", None),
    }
    if extra:
        payload.update(extra)
    return payload
