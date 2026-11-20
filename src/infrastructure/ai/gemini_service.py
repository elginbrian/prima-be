import asyncio
import base64
import csv
import io
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore
    _GENAI_AVAILABLE = False

try:
    import pypdf
    _PYPDF_AVAILABLE = True
except ImportError:
    pypdf = None
    _PYPDF_AVAILABLE = False

try:
    import docx  # python-docx
    _DOCX_AVAILABLE = True
except ImportError:
    docx = None
    _DOCX_AVAILABLE = False

try:
    import openpyxl
    _OPENPYXL_AVAILABLE = True
except ImportError:
    openpyxl = None
    _OPENPYXL_AVAILABLE = False

from src.domain.exceptions import DomainException, ErrorCode
from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

# 3-Tier AI Model Chains with automatic step-down failover & Gemma 4 31B last-resort fallback
AI_TIER_LABELS: Dict[str, str] = {
    "cekatan": "Cekatan (Flash Lite)",
    "cermat": "Cermat (Flash)",
    "cerdas": "Cerdas (Gemini 4)",
    "gemma": "Gemma 4 31B (Cadangan)",
    "custom": "Custom (Model Eksternal)",
    "external": "Custom (Model Eksternal)",
    "mcp_takeover": "Custom (External Agent Takeover)",
}

_CEKATAN_CHAIN: List[Tuple[str, str]] = [
    ("gemini-3.5-flash-lite", "cekatan"),
    ("gemini-3.1-flash-lite", "cekatan"),
    ("gemini-flash-lite-latest", "cekatan"),
    ("gemma-4-31b-it", "gemma"),
]

_CERMAT_CHAIN: List[Tuple[str, str]] = [
    ("gemini-3.8-flash", "cermat"),
    ("gemini-3.7-flash", "cermat"),
    ("gemini-3.6-flash", "cermat"),
] + _CEKATAN_CHAIN

_CERDAS_CHAIN: List[Tuple[str, str]] = [
    ("gemini-4-hydrogen", "cerdas"),
] + _CERMAT_CHAIN

_TIER_CHAINS: Dict[str, List[Tuple[str, str]]] = {
    "cekatan": _CEKATAN_CHAIN,
    "cermat": _CERMAT_CHAIN,
    "cerdas": _CERDAS_CHAIN,
}

# ── PROMPTS ─────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
Anda adalah spesialis OCR & Ekstraksi Dokumen Pengadaan di PT Pertamina Patra Niaga (Sistem PRIMA).
Analisis dokumen ini secara teliti (dapat berupa Bank Garansi, Surety Bond / Asuransi, Surat Penawaran, atau Kontrak / SPK).
Ekstrak field berikut dan kembalikan TEPAT dalam bentuk raw JSON object (tanpa blok Markdown ```json):
- type: String (pilih yang paling sesuai: "Jaminan Pelaksanaan", "Jaminan Masa Pemeliharaan", "Jaminan Penawaran", "Jaminan Uang Muka", "Kontrak", atau "Surat Penawaran")
- vendor_name: String (Nama penyedia / principal / vendor / kontraktor secara lengkap termasuk PT/CV)
- issuer: String (Nama bank penerbit, perusahaan asuransi penjamin, atau pihak penerbit dokumen)
- issuer_type: String ("Bank" jika bank, "Asuransi" jika perusahaan asuransi/penjaminan, atau "Lainnya")
- beneficiary: String (Pihak penerima jaminan / pemberi kerja, umumnya PT Pertamina Patra Niaga atau entitas Pertamina terkait)
- reference_no: String (Nomor jaminan / No. Bond / Nomor Kontrak / Nomor Surat Penawaran secara presisi)
- value: Number (Nilai nominal jaminan/kontrak/penawaran dalam angka numerik murni IDR tanpa titik/koma pemisah ribuan; periksa angka dan terbilang untuk memastikan akurasi)
- issue_date: ISO-8601 Date String (Tanggal terbit / efektif, contoh "2026-01-01T00:00:00Z")
- expiry_date: ISO-8601 Date String (Tanggal jatuh tempo / berakhir masa berlaku, contoh "2026-12-31T00:00:00Z")
- duration_text: String (Opsional: jangka waktu pelaksanaan atau masa berlaku sebagaimana tertulis di dokumen, mis. "12 bulan" atau "180 hari kalender", null jika tidak tertera)
- project_title: String (Opsional: nama paket pekerjaan / proyek yang tercantum pada dokumen, null jika tidak tertera)

Aturan penting:
1. Periksa seluruh halaman termasuk stempel, tabel, header, dan footer.
2. Konversi penulisan tanggal Indonesia (mis. "15 Maret 2026") ke format ISO-8601 ("2026-03-15T00:00:00Z").
3. Jika sebuah field benar-benar tidak ditemukan di dokumen, isi dengan null. Jangan mengarang nilai.
"""

EXTRACT_CRITERIA_PROMPT = """
Anda adalah Senior Procurement Auditor & Governance Specialist di PT Pertamina Patra Niaga (Sistem PRIMA).
Tugas Anda adalah mengekstrak seluruh daftar KRITERIA / CHECKLIST KELAYAKAN DOKUMEN dari berkas yang diunggah pengguna (dapat berupa PDF, DOCX, Excel/CSV, tabel evaluasi, KAK, RKS, atau matriks penilaian).

NAMA BERKAS SUMBER:
{filename}

INSTRUKSI EKSTRAKSI:
1. Identifikasi setiap butir persyaratan, kriteria evaluasi, atau item checklist yang terdapat di dalam dokumen secara lengkap dan terstruktur.
2. Untuk setiap kriteria, ekstrak:
   - category: Kelompok kategori singkat ("Legalitas", "Administrasi", "Teknis", "Jadwal & Waktu", "Finansial & Harga", "HSSE / K3LL", "Jaminan", atau "Umum").
   - item: Kalimat persyaratan kriteria yang jelas, spesifik, dan dapat diverifikasi oleh AI terhadap dokumen target.
   - guidance: Parameter pembanding spesifik, angka target, atau acuan (mis. "Maksimal 12 bulan kalender", "Minimal 5% dari nilai kontrak", "Wajib mencantumkan PPN 11%"). Isi null jika tidak ada rincian tambahan.
   - is_mandatory: true jika butir bersifat wajib/gugur/mandatory, false jika opsional/penilaian tambahan.
   - weight: Angka persentase bobot (0-100). Jika dokumen sumber mencantumkan bobot eksplisit, gunakan angka tersebut; jika tidak, bagi rata secara proporsional sehingga total bobot semua kriteria = 100.
   - severity_on_failure: "ERROR" jika is_mandatory=true, "WARNING" jika opsional.
3. Berikan juga saran metadata template:
   - suggested_name: Nama template standar yang representatif (mis. "Standar Evaluasi Surat Penawaran Konstruksi").
   - suggested_document_kind: Salah satu dari "Kerangka Acuan Kerja", "Rencana Anggaran Biaya", "Jaminan Pelaksanaan", "Jaminan Penawaran", "Dokumen Penawaran", "Kontrak & Perjanjian", "Berita Acara", "Umum".
   - suggested_system_prompt: 1-2 kalimat instruksi ringkas untuk auditor AI saat menggunakan daftar kriteria ini.

Kembalikan TEPAT dalam bentuk raw JSON object (tanpa blok markdown ```json):
{
  "suggested_name": "...",
  "suggested_document_kind": "Dokumen Penawaran",
  "suggested_system_prompt": "...",
  "checklist_rules": [
    {
      "category": "Jadwal & Waktu",
      "item": "Jangka waktu pelaksanaan pekerjaan sesuai atau lebih cepat dari target KAK (maksimal 12 bulan)",
      "guidance": "Bandingkan durasi penawaran dengan target 12 bulan; lebih cepat atau sama = memenuhi penuh, lebih lambat = tidak memenuhi/perlu perhatian.",
      "is_mandatory": true,
      "weight": 20,
      "severity_on_failure": "ERROR"
    }
  ]
}
"""

DOCUMENT_CHECKLIST_PROMPT_TEMPLATE = """
Anda adalah AI Procurement Auditor & Specialist Senior di PT Pertamina Patra Niaga (Sistem PRIMA).
Tugas Anda adalah memeriksa, memvalidasi, dan menilai dokumen pengadaan yang diunggah secara sangat teliti, objektif, terukur, dan berbasis bukti berdasarkan daftar kriteria berbobot serta instruksi berikut:

DAFTAR KRITERIA & BOBOT YANG HARUS DIPERIKSA:
{checklist_bullets}

INSTRUKSI KHUSUS / PROMPT PENGGUNA:
{custom_prompt}

NAMA DOKUMEN:
{document_name}

REFERENSI TAHAPAN PEKERJAAN PENGADAAN ORGANISASI:
{workflow_stages_ref}

ATURAN EVALUASI MENDALAM & KOMPARATIF (WAJIB DIPATUHI):
1. Validasi Checklist Mendalam & Terukur (per butir sesuai urutan input):
   Untuk SETIAP butir kriteria pada daftar di atas, kembalikan tepat 1 objek evaluasi:
   - item: Nama butir kriteria PERSIS seperti pada daftar input.
   - status: "Memenuhi" | "Perlu Perhatian" | "Tidak Memenuhi"
   - fulfillment_ratio: Angka desimal 0.0 sampai 1.0 yang mengukur tingkat pemenuhan butir ini secara objektif:
     * 1.0 = Memenuhi sepenuhnya (termasuk kasus yang LEBIH BAIK dari syarat minimum, misal jadwal penawaran 12 bulan vs batas KAK 13 bulan, atau nilai jaminan >= 5%).
     * 0.5 s/d 0.85 = Memenuhi sebagian / Perlu Perhatian (misal ketentuan tercantum tetapi ada deviasi minor, format/tanggal perlu klarifikasi, atau jadwal sedikit melampaui target tanpa justifikasi lengkap).
     * 0.0 s/d 0.35 = Tidak Memenuhi (bertentangan dengan syarat wajib, melampaui batas waktu/anggaran secara signifikan, atau tidak ditemukan sama sekali).
   - comparison_detail: Ringkasan perbandingan faktual antara syarat/target kriteria vs temuan di dokumen (contoh: "Target KAK: maks. 13 bulan | Temuan Dokumen: 12 bulan (lebih cepat 1 bulan -> Memenuhi)" atau "Syarat: Bank BUMN | Temuan: PT Asuransi Tugu Pratama Indonesia Tbk -> Tidak sesuai"). Isi null jika tidak bersifat komparatif.
   - evidence_quote: Kutipan kalimat, angka, pasal, atau baris tabel PERSIS dari isi dokumen sebagai bukti audit (berikan null jika benar-benar tidak ditemukan di dokumen).
   - explanation: Analisis profesional yang rinci, terukur, menyebutkan angka/tanggal/pasal spesifik dari dokumen, alasan penetapan status & fulfillment_ratio, serta dampak risikonya bagi pengadaan.
   - severity: "SUCCESS" jika Memenuhi, "WARNING" jika Perlu Perhatian, "ERROR" jika Tidak Memenuhi.

2. Penilaian & Status Dokumen:
   - overall_score: Perkiraan skor kepatuhan berbobot skala 0-100 berdasarkan bobot (%) dan fulfillment_ratio tiap kriteria.
   - compliance_status:
     * "Lulus Verifikasi" jika skor memenuhi ambang batas dan tidak ada kriteria Wajib (Mandatory) yang gagal.
     * "Catatan Procurement" jika ada catatan minor / Perlu Perhatian.
     * "Perlu Perbaikan" jika skor rendah atau ada kriteria Wajib yang Tidak Memenuhi.

3. Ringkasan Eksekutif & Rekomendasi Konkret:
   - summary: Rangkuman eksekutif 2-4 kalimat yang tajam, faktual, menyebutkan identitas proyek/pihak/nilai penting dari dokumen, serta temuan utama.
   - recommendations: 2 sampai 4 tindakan korektif/tindak lanjut yang spesifik dan langsung dapat dieksekusi tim Procurement / FPP.

4. Ekstraksi Informasi Pekerjaan & Tahapan (Workflow Extraction — bekerja baik DENGAN maupun TANPA template):
   - title: Nama pekerjaan pengadaan yang tertera di dalam dokumen (atau judul representatif berdasarkan isi dokumen).
   - estimated_amount: Perkiraan nilai pagu anggaran / HPS / nilai kontrak / nilai penawaran dalam IDR (angka numerik murni, 0 jika tidak ditemukan).
   - suggested_method: "Tender Terbuka" | "Pemilihan Langsung" | "Penunjukan Langsung"
   - department_name: Unit/Fungsi pemohon yang terdeteksi di dokumen (misal "Fungsi Pemeliharaan & Aset", "Fungsi Operasi", dsb.).
   - stages: Susun urutan tahapan pekerjaan pengadaan yang sesuai untuk dokumen ini (5 - 10 tahapan), mengacu pada REFERENSI TAHAPAN PEKERJAAN ORGANISASI bila relevan, atau membentuk urutan tahapan baru yang akurat secara otomatis dari isi dokumen jika tidak ada template.
     PENTING (Auto-Clear): Jika dokumen ini membuktikan bahwa tahap awal tertentu (misal Penyusunan RKS/KAK, Pembuatan TOR, atau Pemasukan Penawaran) telah terpenuhi, tandai tahap tersebut dengan:
       - status: "Done"
       - auto_cleared: true
       - notes: "Otomatis terpenuhi (auto-cleared) oleh dokumen yang divalidasi."
     Tahap aktif berikutnya tandai:
       - status: "In Progress"
       - auto_cleared: false
       - notes: "Tahap aktif berikutnya."
     Tahap-tahap selanjutnya tandai:
       - status: "Pending"
       - auto_cleared: false

Kembalikan respon TEPAT dalam bentuk raw JSON object (tanpa teks pengantar dan tanpa blok markdown ```json):
{
  "overall_score": 85.0,
  "compliance_status": "Lulus Verifikasi",
  "summary": "...",
  "checklist_evaluations": [
    {
      "item": "...",
      "status": "Memenuhi",
      "fulfillment_ratio": 1.0,
      "comparison_detail": "...",
      "evidence_quote": "...",
      "explanation": "...",
      "severity": "SUCCESS"
    }
  ],
  "recommendations": [
    "..."
  ],
  "extracted_project": {
    "title": "...",
    "estimated_amount": 1500000000,
    "suggested_method": "Tender Terbuka",
    "department_name": "Fungsi Pemohon",
    "stages": [
      {
        "step": "Penyusunan RKS & Spesifikasi Teknis",
        "status": "Done",
        "auto_cleared": true,
        "notes": "Otomatis selesai (auto-cleared) dari hasil validasi kelengkapan dokumen teknis."
      }
    ]
  }
}
"""

_GUARANTEE_KEYS = (
    "type",
    "vendor_name",
    "issuer",
    "issuer_type",
    "beneficiary",
    "reference_no",
    "value",
    "issue_date",
    "expiry_date",
    "duration_text",
    "project_title",
)

_ISSUER_TYPES = {"Bank", "Asuransi", "Lainnya"}


class AIExtractionError(DomainException):
    """Raised when the AI provider is unavailable or returns unusable output."""

    def __init__(self, message: str):
        super().__init__(message, ErrorCode.INTERNAL_ERROR)


class GeminiService:
    def __init__(self):
        self.api_key = (settings.gemini_api_key or "").strip()
        self.external_config: Dict[str, Any] = {
            "provider_mode": "internal_gemini",  # internal_gemini | openai_compatible | custom_webhook | mcp_takeover
            "provider_name": "PRIMA Internal (Google Gemini)",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model_name": "gpt-4o-mini",
            "replace_chat_brain": True,
            "replace_analysis_brain": True,
        }
        self.takeover_queue: List[Dict[str, Any]] = []
        self.takeover_tickets: Dict[str, Dict[str, Any]] = {}
        if _GENAI_AVAILABLE and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(settings.gemini_model)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini SDK model: {e}")
                self.model = None
        else:
            self.model = None

    def set_external_config(self, cfg: Dict[str, Any]) -> None:
        if not isinstance(cfg, dict):
            return
        for k in (
            "provider_mode",
            "provider_name",
            "base_url",
            "api_key",
            "model_name",
            "replace_chat_brain",
            "replace_analysis_brain",
        ):
            if k in cfg and cfg[k] is not None:
                self.external_config[k] = cfg[k]

    def get_external_config_masked(self) -> Dict[str, Any]:
        raw_key = str(self.external_config.get("api_key") or "")
        masked = (
            f"{raw_key[:6]}...{raw_key[-4:]}"
            if len(raw_key) > 10
            else ("***" if raw_key else "")
        )
        return {
            **self.external_config,
            "api_key": masked,
            "has_api_key": bool(raw_key),
        }

    def enqueue_takeover_ticket(
        self,
        user_query: str,
        page_context: str,
        attachment_filename: Optional[str],
        attachment_extracted_text: str,
        conversation_history_text: str,
        workspace_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        import uuid
        from datetime import datetime, timezone

        ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        ticket = {
            "ticket_id": ticket_id,
            "status": "PENDING",  # PENDING | REPLIED
            "user_query": user_query,
            "page_context": page_context,
            "attachment_filename": attachment_filename,
            "attachment_extracted_text": attachment_extracted_text[:12000] if attachment_extracted_text else None,
            "conversation_history": conversation_history_text,
            "workspace_summary_counts": workspace_summary.get("summary_counts", {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "replied_at": None,
            "agent_name": None,
            "response_payload": None,
        }
        self.takeover_tickets[ticket_id] = ticket
        self.takeover_queue = [
            t for t in self.takeover_tickets.values()
        ][-30:]
        return ticket

    def reply_takeover_ticket(
        self,
        ticket_id: str,
        answer: str,
        agent_name: str = "External MCP Agent",
        highlights: Optional[List[str]] = None,
        command: Optional[Dict[str, Any]] = None,
        referenced_items: Optional[List[Dict[str, Any]]] = None,
        suggested_followups: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from datetime import datetime, timezone

        target = self.takeover_tickets.get(ticket_id)
        if not target:
            # If ticket_id is "LATEST", pick the most recent PENDING ticket
            if ticket_id.upper() == "LATEST":
                pending_list = [
                    t for t in self.takeover_tickets.values() if t["status"] == "PENDING"
                ]
                if pending_list:
                    target = pending_list[-1]
            if not target:
                raise ValueError(f"Tiket Takeover '{ticket_id}' tidak ditemukan.")

        target["status"] = "REPLIED"
        target["replied_at"] = datetime.now(timezone.utc).isoformat()
        target["agent_name"] = agent_name
        target["response_payload"] = {
            "intent_kind": "COMMAND" if command else "QUESTION",
            "answer": answer,
            "highlights": highlights or [],
            "referenced_items": referenced_items or [],
            "command": command,
            "suggested_followups": suggested_followups or [],
            "ai_tier_requested": "mcp_takeover",
            "ai_tier_used": "mcp_takeover",
            "ai_model_used": agent_name,
            "ai_fallback_notice": None,
            "takeover_ticket_id": target["ticket_id"],
            "takeover_pending": False,
        }
        return target

    def is_external_active(self, context_kind: str = "analysis") -> bool:
        ext_mode = str(self.external_config.get("provider_mode") or "internal_gemini")
        if ext_mode not in ("openai_compatible", "custom_webhook"):
            return False
        if context_kind == "chat":
            return bool(self.external_config.get("replace_chat_brain", True))
        return bool(self.external_config.get("replace_analysis_brain", True))

    def is_configured_for(self, context_kind: str = "analysis") -> bool:
        return self.is_external_active(context_kind) or self.is_configured()

    def _call_external_provider_sync(
        self,
        parts_payload: List[Dict[str, Any]],
        timeout_sec: float = 45.0,
    ) -> Tuple[str, str]:
        mode = str(self.external_config.get("provider_mode") or "internal_gemini")
        base_url = str(self.external_config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        ext_key = str(self.external_config.get("api_key") or "").strip()
        ext_model = str(self.external_config.get("model_name") or "gpt-4o-mini").strip()

        text_chunks = [p.get("text", "") for p in parts_payload if p.get("text")]
        combined_prompt = "\n\n".join(text_chunks)

        image_parts = [
            p["inline_data"]
            for p in parts_payload
            if isinstance(p.get("inline_data"), dict)
            and str(p["inline_data"].get("mime_type") or "").startswith("image/")
        ]

        if mode == "custom_webhook":
            req_data = json.dumps({
                "prompt": combined_prompt,
                "model": ext_model,
                "response_format": "json",
            }).encode("utf-8")
            headers = {"Content-Type": "application/json", "User-Agent": "PRIMA-AI-Router/1.0"}
            if ext_key:
                headers["Authorization"] = f"Bearer {ext_key}"
            req = urllib.request.Request(base_url, data=req_data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as res:
                    body = json.loads(res.read().decode("utf-8"))
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode("utf-8", errors="ignore")[:300]
                raise RuntimeError(f"HTTP {http_err.code}: {err_body}") from http_err
            if isinstance(body, dict) and "answer" in body:
                return json.dumps(body, ensure_ascii=False), f"webhook:{ext_model}"
            if isinstance(body, dict) and isinstance(body.get("output"), str):
                return body["output"], f"webhook:{ext_model}"
            return json.dumps(body, ensure_ascii=False), f"webhook:{ext_model}"

        # OpenAI-compatible Chat Completions endpoint (OpenAI, Claude via OpenRouter, Groq, Codex, vLLM, Ollama)
        endpoint = (
            base_url
            if base_url.endswith("/chat/completions")
            else f"{base_url}/chat/completions"
        )
        if image_parts:
            user_content: Any = [{"type": "text", "text": combined_prompt}]
            for img in image_parts[:3]:
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['mime_type']};base64,{img['data']}",
                    },
                })
        else:
            user_content = combined_prompt

        payload = {
            "model": ext_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "You are PRIMA External AI Brain. Always return a valid raw JSON object matching the requested schema.",
                },
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Content-Type": "application/json", "User-Agent": "PRIMA-AI-Router/1.0"}
        if ext_key:
            headers["Authorization"] = f"Bearer {ext_key}"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as res:
                body = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as http_err:
            err_body = http_err.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"HTTP {http_err.code}: {err_body}") from http_err
        choices = body.get("choices") or []
        if not choices:
            raise ValueError(f"Empty choices from external AI provider ({endpoint})")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise ValueError("Empty content from external AI provider")
        return content, ext_model

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def normalize_tier(ai_tier: Optional[str]) -> str:
        raw = (ai_tier or "cekatan").strip().lower()
        if raw == "custom":
            return "custom"
        if raw in _TIER_CHAINS:
            return raw
        return "cekatan"

    @staticmethod
    def _build_fallback_notice(requested_tier: str, used_tier: str, used_model: str) -> Optional[str]:
        if used_tier == requested_tier:
            return None
        req_label = AI_TIER_LABELS.get(requested_tier, requested_tier.title())
        used_label = AI_TIER_LABELS.get(used_tier, used_tier.title())
        return (
            f"Mode {req_label} sedang tidak tersedia — dialihkan otomatis ke {used_label} ({used_model})."
        )

    def _model_candidates(self, ai_tier: Optional[str] = "cekatan") -> List[Tuple[str, str]]:
        norm_tier = self.normalize_tier(ai_tier)
        return list(_TIER_CHAINS.get(norm_tier, _CEKATAN_CHAIN))

    def _call_gemini_rest_sync(
        self,
        model_name: str,
        parts_payload: List[Dict[str, Any]],
        timeout_sec: float = 95.0,
    ) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        is_gemma = "gemma" in model_name.lower()

        # Gemma models reject application/pdf inline_data — strip PDF binary parts and rely on extracted text
        effective_parts = parts_payload
        if is_gemma:
            filtered = [
                p for p in parts_payload
                if not (isinstance(p.get("inline_data"), dict) and p["inline_data"].get("mime_type") == "application/pdf")
            ]
            if filtered:
                effective_parts = filtered

        gen_config: Dict[str, Any] = {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        }
        if "gemini-4" in model_name:
            # Avoid reasoning timeouts on large PDF/JSON payloads while keeping full JSON accuracy
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [{"parts": effective_parts}],
            "generationConfig": gen_config,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            body = json.loads(res.read().decode("utf-8"))
        candidates = body.get("candidates") or []
        if not candidates:
            raise ValueError(f"Empty candidates from Gemini model {model_name}")
        content_parts = candidates[0].get("content", {}).get("parts") or []
        text_chunks = [p.get("text", "") for p in content_parts if p.get("text") and not p.get("thought")]
        raw_text = "".join(text_chunks).strip()
        if not raw_text:
            raise ValueError(f"No text in Gemini response from {model_name}")
        return raw_text

    async def _generate_json_with_failover(
        self,
        parts_payload: List[Dict[str, Any]],
        ai_tier: Optional[str] = "cekatan",
        allow_long_timeout: bool = False,
        context_kind: str = "analysis",  # "chat" | "analysis"
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        norm_tier = self.normalize_tier(ai_tier)
        last_error: Optional[Exception] = None

        ext_mode = str(self.external_config.get("provider_mode") or "internal_gemini")
        should_use_external = self.is_external_active(context_kind)

        # Strict non-fallback rule: once a non-default AI model is selected, never fall back to Gemini default
        if should_use_external or (norm_tier == "custom" and ext_mode != "internal_gemini"):
            ext_model = str(self.external_config.get("model_name") or "custom-model").strip()
            ext_timeout = 90.0 if allow_long_timeout else 45.0
            try:
                raw_text, used_ext_model = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._call_external_provider_sync,
                        parts_payload,
                        ext_timeout,
                    ),
                    timeout=ext_timeout + 5.0,
                )
                parsed = self._parse_json(raw_text)
                ai_meta: Dict[str, Any] = {
                    "ai_tier_requested": "custom",
                    "ai_tier_used": "custom",
                    "ai_model_used": used_ext_model,
                    "ai_fallback_notice": None,
                }
                logger.info(f"Custom AI provider succeeded using model '{used_ext_model}' (no fallback mode)")
                return parsed, ai_meta
            except Exception as ext_exc:
                logger.error(f"Custom AI provider ({ext_model}) failed and fallback to default is disabled: {ext_exc}")
                raise AIExtractionError(
                    f"Model AI Custom ({ext_model}) gagal memproses permintaan dan tidak melakukan fallback ke model default: {ext_exc}"
                ) from ext_exc

        effective_tier = "cekatan" if norm_tier == "custom" else norm_tier
        for model_name, candidate_tier in self._model_candidates(effective_tier):
            if allow_long_timeout:
                if candidate_tier == "cerdas":
                    model_timeout = 130.0
                elif candidate_tier == "cermat":
                    model_timeout = 60.0
                elif candidate_tier == "gemma":
                    model_timeout = 75.0
                else:
                    model_timeout = 40.0
            else:
                if candidate_tier == "cerdas":
                    model_timeout = 55.0
                elif candidate_tier == "cermat":
                    model_timeout = 28.0
                elif candidate_tier == "gemma":
                    model_timeout = 28.0
                else:
                    model_timeout = 20.0

            try:
                raw_text = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._call_gemini_rest_sync,
                        model_name,
                        parts_payload,
                        model_timeout,
                    ),
                    timeout=model_timeout + 2.0,
                )
                parsed = self._parse_json(raw_text)
                fallback_notice = self._build_fallback_notice(effective_tier, candidate_tier, model_name)
                ai_meta: Dict[str, Any] = {
                    "ai_tier_requested": effective_tier,
                    "ai_tier_used": candidate_tier,
                    "ai_model_used": model_name,
                    "ai_fallback_notice": fallback_notice,
                }
                if fallback_notice:
                    logger.warning(f"AI tier stepped down: {fallback_notice}")
                else:
                    logger.info(f"AI analysis succeeded using model '{model_name}' (tier={candidate_tier})")
                return parsed, ai_meta
            except urllib.error.HTTPError as http_err:
                err_body = ""
                try:
                    err_body = http_err.read().decode("utf-8", errors="ignore")[:240]
                except Exception:
                    pass
                logger.warning(f"AI model '{model_name}' (tier={candidate_tier}) HTTP {http_err.code}: {err_body}")
                last_error = RuntimeError(f"HTTP {http_err.code} from {model_name}: {err_body}")
            except Exception as exc:
                logger.warning(f"AI model '{model_name}' (tier={candidate_tier}) error: {exc}")
                last_error = exc

        raise AIExtractionError(f"Seluruh model AI (termasuk cadangan Gemma 4 31B) gagal memproses dokumen: {last_error}")

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Handle models (e.g. Gemma) that occasionally emit prose/thinking before or after the JSON object
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end > start:
                data = json.loads(cleaned[start : end + 1])
            else:
                raise
        if not isinstance(data, dict):
            raise ValueError("AI response is not a JSON object")
        return data

    @staticmethod
    def _normalize_guarantee(data: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce AI output into the shape the frontend expects."""
        result = {key: data.get(key) for key in _GUARANTEE_KEYS}
        value = result.get("value")
        if isinstance(value, str):
            digits = re.sub(r"[^\d]", "", value)
            result["value"] = int(digits) if digits else None
        if result.get("issuer_type") not in _ISSUER_TYPES:
            result["issuer_type"] = "Lainnya" if result.get("issuer_type") else None
        return result

    @staticmethod
    def _extract_pdf_text(file_content: bytes) -> str:
        """Extract text from PDF pages if pypdf is available."""
        if not _PYPDF_AVAILABLE:
            return ""
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_content))
            page_texts = []
            for idx, page in enumerate(reader.pages[:25]):
                text = page.extract_text()
                if text:
                    page_texts.append(f"--- Halaman {idx+1} ---\n{text}")
            return "\n\n".join(page_texts)
        except Exception as e:
            logger.warning(f"Could not extract text from PDF via pypdf: {e}")
            return ""

    @staticmethod
    def _extract_docx_text(file_content: bytes) -> str:
        """Extract text and tables from DOCX files."""
        if not _DOCX_AVAILABLE:
            return ""
        try:
            doc = docx.Document(io.BytesIO(file_content))
            parts: List[str] = []
            for p in doc.paragraphs:
                if p.text.strip():
                    parts.append(p.text.strip())
            for t_idx, table in enumerate(doc.tables):
                rows_text = []
                for row in table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        rows_text.append(" | ".join(cells))
                if rows_text:
                    parts.append(f"--- Tabel {t_idx+1} ---\n" + "\n".join(rows_text))
            return "\n".join(parts)
        except Exception as e:
            logger.warning(f"Could not extract text from DOCX: {e}")
            return ""

    @staticmethod
    def _extract_xlsx_text(file_content: bytes) -> str:
        """Extract sheets and rows from XLSX files."""
        if not _OPENPYXL_AVAILABLE:
            return ""
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
            parts: List[str] = []
            for sheet_name in wb.sheetnames[:10]:
                ws = wb[sheet_name]
                rows_text = []
                for row in ws.iter_rows(max_row=200, values_only=True):
                    vals = [str(v).strip() for v in row if v is not None and str(v).strip() != ""]
                    if vals:
                        rows_text.append(" | ".join(vals))
                if rows_text:
                    parts.append(f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows_text))
            return "\n\n".join(parts)
        except Exception as e:
            logger.warning(f"Could not extract text from XLSX: {e}")
            return ""

    @classmethod
    def _extract_document_text(cls, file_content: bytes, mime_type: str, filename: Optional[str] = None) -> str:
        """Unified text extractor across PDF, DOCX, XLSX, CSV, and plain text."""
        fname = (filename or "").lower()
        mtype = (mime_type or "").lower()

        if mtype == "application/pdf" or fname.endswith(".pdf"):
            return cls._extract_pdf_text(file_content)

        if "wordprocessingml" in mtype or fname.endswith(".docx"):
            return cls._extract_docx_text(file_content)

        if "spreadsheetml" in mtype or fname.endswith(".xlsx"):
            return cls._extract_xlsx_text(file_content)

        if "csv" in mtype or fname.endswith(".csv"):
            try:
                decoded = file_content.decode("utf-8-sig", errors="replace")
                reader = csv.reader(io.StringIO(decoded))
                rows = [" | ".join(c.strip() for c in r if c.strip()) for r in reader]
                return "\n".join(r for r in rows if r)
            except Exception:
                return ""

        if mtype.startswith("text/") or fname.endswith((".txt", ".md", ".json")):
            return file_content.decode("utf-8", errors="replace")

        return ""

    @staticmethod
    def _normalize_weights_to_100(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize a list of extracted rule weights proportionally to sum to 100."""
        if not rules:
            return rules
        raw_weights = []
        for r in rules:
            try:
                w = float(r.get("weight", 0))
                raw_weights.append(w if w > 0 else 0.0)
            except (TypeError, ValueError):
                raw_weights.append(0.0)

        total = sum(raw_weights)
        if total <= 0:
            base = round(100.0 / len(rules), 2)
            for idx, r in enumerate(rules):
                if idx == len(rules) - 1:
                    r["weight"] = round(100.0 - base * (len(rules) - 1), 2)
                else:
                    r["weight"] = base
        else:
            running = 0.0
            for idx, r in enumerate(rules):
                if idx == len(rules) - 1:
                    r["weight"] = round(max(0.0, 100.0 - running), 2)
                else:
                    norm = round((raw_weights[idx] / total) * 100.0, 2)
                    r["weight"] = norm
                    running += norm
        return rules

    async def extract_guarantee_data(
        self,
        file_content: bytes,
        mime_type: str,
        filename: Optional[str] = None,
        ai_tier: str = "cekatan",
    ) -> Dict[str, Any]:
        """OCR & parse Bank Guarantee, Surety Bond, Contract, or Bid Letter using real Gemini AI."""
        if not self.is_configured_for("analysis"):
            raise AIExtractionError("Layanan ekstraksi AI belum dikonfigurasi (GEMINI_API_KEY / Custom AI).")

        parts_payload: List[Dict[str, Any]] = []
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            b64_data = base64.b64encode(file_content).decode("ascii")
            parts_payload.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})

        extracted_text = self._extract_document_text(file_content, mime_type, filename)
        if extracted_text:
            prompt = f"TEKS HASIL PEMBACAAN DOKUMEN:\n\"\"\"\n{extracted_text[:18000]}\n\"\"\"\n\n{EXTRACTION_PROMPT}"
        else:
            prompt = EXTRACTION_PROMPT

        parts_payload.append({"text": prompt})

        try:
            parsed, ai_meta = await self._generate_json_with_failover(
                parts_payload,
                ai_tier=ai_tier,
                allow_long_timeout=False,
            )
            result = self._normalize_guarantee(parsed)
            result.update(ai_meta)
            return result
        except AIExtractionError:
            raise
        except Exception as exc:
            logger.exception("Gemini document OCR extraction failed")
            raise AIExtractionError(f"Ekstraksi OCR AI gagal: {exc}") from exc

    async def extract_criteria_from_document(
        self,
        file_content: bytes,
        mime_type: str,
        filename: str,
        ai_tier: str = "cekatan",
    ) -> Dict[str, Any]:
        """
        Extract structured checklist criteria (with categories, guidance, mandatory flags, and weights)
        from an uploaded template file (PDF, DOCX, XLSX, CSV, TXT, or scanned image).
        """
        if not self.is_configured_for("analysis"):
            raise AIExtractionError("Layanan AI belum dikonfigurasi (GEMINI_API_KEY / Custom AI).")

        extracted_text = self._extract_document_text(file_content, mime_type, filename)
        parts_payload: List[Dict[str, Any]] = []

        if mime_type.startswith("image/") or mime_type == "application/pdf":
            b64_data = base64.b64encode(file_content).decode("ascii")
            parts_payload.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})

        prompt = EXTRACT_CRITERIA_PROMPT.replace("{filename}", filename)
        if extracted_text:
            full_prompt = f"ISI DOKUMEN SUMBER KRITERIA:\n\"\"\"\n{extracted_text[:20000]}\n\"\"\"\n\n{prompt}"
        elif not parts_payload:
            raise AIExtractionError(
                "Format file kriteria tidak dapat dibaca. Gunakan berkas PDF, DOCX, XLSX, CSV, TXT, atau gambar (PNG/JPG)."
            )
        else:
            full_prompt = prompt

        parts_payload.append({"text": full_prompt})

        try:
            parsed, ai_meta = await self._generate_json_with_failover(
                parts_payload,
                ai_tier=ai_tier,
                allow_long_timeout=False,
            )
            raw_rules = parsed.get("checklist_rules") or []
            if not isinstance(raw_rules, list) or len(raw_rules) == 0:
                raise ValueError("AI tidak menemukan butir kriteria di dalam berkas yang diunggah.")

            cleaned_rules: List[Dict[str, Any]] = []
            for r in raw_rules:
                if not isinstance(r, dict):
                    continue
                item_text = str(r.get("item", "")).strip()
                if not item_text:
                    continue
                is_mand = bool(r.get("is_mandatory", True))
                cleaned_rules.append({
                    "category": str(r.get("category") or "Umum").strip()[:60],
                    "item": item_text,
                    "guidance": str(r.get("guidance")).strip() if r.get("guidance") else None,
                    "is_mandatory": is_mand,
                    "weight": float(r.get("weight") or 0),
                    "severity_on_failure": "ERROR" if is_mand else "WARNING",
                    "source": "custom",
                })

            if not cleaned_rules:
                raise ValueError("Tidak ada butir kriteria valid yang berhasil diekstrak.")

            self._normalize_weights_to_100(cleaned_rules)

            return {
                "suggested_name": parsed.get("suggested_name") or filename.rsplit(".", 1)[0].replace("_", " ").title(),
                "suggested_document_kind": parsed.get("suggested_document_kind") or "Umum",
                "suggested_system_prompt": parsed.get("suggested_system_prompt") or None,
                "checklist_rules": cleaned_rules,
                **ai_meta,
            }
        except AIExtractionError:
            raise
        except Exception as exc:
            logger.error(f"Gemini criteria extraction failed: {exc}")
            raise AIExtractionError(f"Ekstraksi kriteria dari file gagal: {exc}") from exc

    async def validate_document_checklist(
        self,
        file_content: bytes,
        mime_type: str,
        checklist_items: List[Union[str, Dict[str, Any]]],
        custom_prompt: Optional[str] = None,
        document_name: Optional[str] = None,
        available_workflow_stages: Optional[List[str]] = None,
        ai_tier: str = "cekatan",
        allow_long_timeout: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate any document against user-supplied weighted checklist rules and prompt using real Gemini AI.
        Never uses mock/fallback results.
        """
        if not checklist_items:
            checklist_items = [
                {"item": "Nama pekerjaan dan lingkup kebutuhan", "weight": 20, "is_mandatory": True},
                {"item": "Spesifikasi teknis / Kerangka Acuan Kerja", "weight": 25, "is_mandatory": True},
                {"item": "Perkiraan nilai anggaran / HPS", "weight": 20, "is_mandatory": True},
                {"item": "Jadwal pelaksanaan & jangka waktu pemenuhan", "weight": 20, "is_mandatory": True},
                {"item": "Ketentuan jaminan / garansi penyedia", "weight": 15, "is_mandatory": False},
            ]

        if not self.is_configured_for("analysis"):
            raise AIExtractionError("Layanan validasi AI belum dikonfigurasi (GEMINI_API_KEY / Custom AI).")

        # Format rich checklist lines with weights, mandatory flag, and guidance
        bullet_lines: List[str] = []
        for idx, entry in enumerate(checklist_items, start=1):
            if isinstance(entry, dict):
                item_text = str(entry.get("item", "")).strip()
                weight = entry.get("weight", 0)
                is_mand = bool(entry.get("is_mandatory", False))
                guidance = entry.get("guidance")
                tag = "WAJIB" if is_mand else "OPSIONAL"
                line = f"{idx}. [{tag} | Bobot: {weight}%] {item_text}"
                if guidance:
                    line += f"\n   Panduan/Parameter Pembanding: {guidance}"
                bullet_lines.append(line)
            else:
                bullet_lines.append(f"{idx}. {str(entry).strip()}")

        bullets = "\n".join(bullet_lines)
        stages_ref = (
            "\n".join(f"- {s}" for s in available_workflow_stages)
            if available_workflow_stages
            else "- Penyusunan RKS & Spesifikasi Teknis\n- Rapat Pra-Tender\n- Pengumuman Pengadaan\n- Pemasukan Dokumen Penawaran\n- Evaluasi Dokumen Penawaran\n- Negosiasi Teknis & Harga\n- Penunjukan Pemenang"
        )

        prompt_text = (
            DOCUMENT_CHECKLIST_PROMPT_TEMPLATE
            .replace("{checklist_bullets}", bullets)
            .replace("{custom_prompt}", custom_prompt or "Periksa kelengkapan, akurasi angka/jadwal, konsistensi istilah, dan kepatuhan terhadap pedoman pengadaan barang/jasa Pertamina.")
            .replace("{document_name}", document_name or "Dokumen Pengadaan")
            .replace("{workflow_stages_ref}", stages_ref)
        )

        extracted_text = self._extract_document_text(file_content, mime_type, document_name)
        parts_payload: List[Dict[str, Any]] = []

        # Pass multimodal inline_data for PDF or images
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            b64_data = base64.b64encode(file_content).decode("ascii")
            parts_payload.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})

        if extracted_text:
            full_prompt = f"KANDUNGAN TEKS HASIL EKSTRAKSI DOKUMEN:\n\"\"\"\n{extracted_text[:20000]}\n\"\"\"\n\n{prompt_text}"
        else:
            full_prompt = prompt_text

        parts_payload.append({"text": full_prompt})

        try:
            parsed, ai_meta = await self._generate_json_with_failover(
                parts_payload,
                ai_tier=ai_tier,
                allow_long_timeout=allow_long_timeout,
            )
            if "overall_score" not in parsed or "checklist_evaluations" not in parsed or "extracted_project" not in parsed:
                raise ValueError("Respon JSON dari AI tidak memiliki field wajib (overall_score, checklist_evaluations, extracted_project)")
            parsed["_ai_meta"] = ai_meta
            return parsed
        except AIExtractionError:
            raise
        except Exception as exc:
            logger.error(f"Gemini document validation failed: {exc}")
            raise AIExtractionError(f"Validasi AI terhadap dokumen gagal: {exc}") from exc

    async def generate_omni_assistant_response(
        self,
        user_query: str,
        workspace_context_json: str,
        conversation_history_text: str = "",
        attachment_bytes: Optional[bytes] = None,
        attachment_mime: Optional[str] = None,
        attachment_filename: Optional[str] = None,
        page_context_text: str = "",
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Omni-Search Generative AI Assistant (Strictly locked to 'cekatan' mode with failover, or Custom AI without fallback).
        Answers questions grounded in live PRIMA database context + optional single file attachment
        and parses actionable commands.
        """
        if not self.is_configured_for("chat"):
            raise AIExtractionError("Layanan AI belum dikonfigurasi (GEMINI_API_KEY / Custom AI).")

        attachment_section = ""
        parts_payload: List[Dict[str, Any]] = []

        if attachment_bytes and attachment_filename:
            safe_mime = (attachment_mime or "application/octet-stream").lower()
            extracted_doc_text = self._extract_document_text(
                attachment_bytes, safe_mime, attachment_filename
            )
            if safe_mime.startswith("image/") or safe_mime == "application/pdf":
                b64_data = base64.b64encode(attachment_bytes).decode("ascii")
                parts_payload.append(
                    {"inline_data": {"mime_type": safe_mime, "data": b64_data}}
                )

            attachment_section = f"""
BERKAS LAMPIRAN YANG DIUNGGAH PENGGUNA SAAT INI:
- Nama File: "{attachment_filename}" (Tipe: {safe_mime})
- Ekstraksi Teks Berkas:
\"\"\"
{(extracted_doc_text or "(Analisis langsung dari visual/PDF lampiran di atas)")[:18000]}
\"\"\"
"""

        prompt = f"""Anda adalah **PRIMA Omni-Assistant**, asisten AI eksekutif untuk sistem manajemen pengadaan PT Pertamina Patra Niaga (PRIMA).
Tugas Anda ada 2:
1. **Menjawab Pertanyaan (Data-Grounded & Attachment Q&A):** Jawab pertanyaan pengguna secara akurat, ringkas, to-the-point, dan profesional berdasarkan DATA REAL-TIME PRIMA serta BERKAS LAMPIRAN (jika ada) di bawah ini. Sebutkan angka, kode (REQ/VAL/DOC/D), nama dokumen/pekerjaan, isi lampiran, skor, atau tanggal secara spesifik.
2. **Menjalankan / Menyiapkan Perintah (Command & Action Execution):** Jika input pengguna mengandung instruksi/perintah (misalnya membuka halaman/fitur tertentu, menandai SLA selesai, mengeskalasi SLA ke manajer, menyimpan rencana mitigasi SLA, mengubah status operasional pekerjaan menjadi On Going/On Hold/Batal, menggeser stage pekerjaan, membuat paket pekerjaan baru dari berkas lampiran atau perintah teks, atau menjalankan evaluasi sinkronisasi SLA), sertakan objek `command` yang sesuai agar sistem dapat mengeksekusinya.

DAFTAR ROUTE NAVIGASI VALID (gunakan untuk command type="NAVIGATE"):
- "/dashboard/onboarding" : Halaman Onboarding & Pencarian Terpadu
- "/dashboard/documents" : Daftar Pemeriksaan Dokumen
- "/dashboard/documents/upload" : Unggah & Validasi Dokumen Baru (AI Checklist)
- "/dashboard/documents/templates" : Pustaka Template Standar & Tahapan Pekerjaan
- "/dashboard/documents/templates/form" : Buat Template Standar Baru
- "/dashboard/overview" : Daftar Pekerjaan Pengadaan (Tracker)
- "/dashboard/overview?lens=guarantees" : Manajemen Warkat Jaminan
- "/dashboard/overview/guarantees/upload" : Unggah & OCR Warkat Jaminan Baru
- "/dashboard/overview?lens=sla-actions" : SLA & Tindak Lanjut Prioritas
- "/dashboard/overview?lens=analytics" : Analitik & Performa Pengadaan
- "/dashboard/notifications" : Pusat Notifikasi
- "/dashboard/settings" : Pengaturan Sistem
- "/dashboard/overview/<REQUEST_ID>" : Detail Pekerjaan tertentu (ganti <REQUEST_ID> dengan ID pekerjaan asli dari data, mis. REQ-001)
- "/dashboard/documents/result?id=<VAL_OR_DOC_ID>" : Detail Hasil Pemeriksaan AI / Dokumen tertentu (ganti dengan ID VAL-... atau DOC-... asli dari data)

JENIS COMMAND (`command.type`) YANG DIDUKUNG:
1. "NAVIGATE": Membuka halaman/fitur/detail item.
   - params: {{"url": "<route_valid>"}}
   - auto_execute: true jika pengguna secara eksplisit meminta "buka / arahkan / pergi ke / tampilkan halaman ...", false jika hanya saran navigasi pendamping jawaban.
2. "COMPLETE_SLA": Menandai target SLA / deadline tertentu menjadi "Selesai".
   - params: {{"deadline_id": "<id_deadline_asli>", "task_name": "<nama_tugas>"}}
   - auto_execute: false (agar pengguna menekan tombol konfirmasi 1-klik, kecuali pengguna menulis kata "langsung" / "sekarang").
3. "ESCALATE_SLA": Mengeskalasi SLA / deadline ke manajer.
   - params: {{"deadline_id": "<id_deadline_asli>", "task_name": "<nama_tugas>", "escalated_to": "Manager Pengadaan Korporat", "reason": "<alasan_eskalasi>"}}
   - auto_execute: false
4. "SUBMIT_RECOVERY_PLAN": Menyimpan rencana mitigasi / recovery plan untuk SLA terlambat.
   - params: {{"deadline_id": "<id_deadline_asli>", "task_name": "<nama_tugas>", "recovery_plan": "<rencana_mitigasi>", "recovery_date": "<YYYY-MM-DD>"}}
   - auto_execute: false
5. "UPDATE_JOB_STATUS": Mengubah status operasional pekerjaan ("On Going" | "On Hold" | "Batal").
   - params: {{"request_id": "<id_pekerjaan_asli>", "title": "<judul_pekerjaan>", "status": "On Going|On Hold|Batal", "reason": "<alasan>"}}
   - auto_execute: false
6. "MOVE_JOB_STAGE": Memindahkan tahap utama pekerjaan ("Persiapan" | "Sourcing" | "Evaluasi" | "Contracting" | "Selesai").
   - params: {{"request_id": "<id_pekerjaan_asli>", "title": "<judul_pekerjaan>", "stage": "Persiapan|Sourcing|Evaluasi|Contracting|Selesai", "notes": "<catatan>"}}
   - auto_execute: false
7. "CREATE_PROCUREMENT": Membuat paket pekerjaan pengadaan baru.
   - params: {{"title": "<judul_pekerjaan_baru>", "amount": <angka_rupiah_default_100000000>, "department_name": "<nama_departemen_default_Procurement>", "procurement_method": "Tender Terbuka|Pemilihan Langsung|Penunjukan Langsung", "is_urgent": <true/false>}}
   - auto_execute: false
8. "EVALUATE_SLA": Menjalankan evaluasi & sinkronisasi otomatis seluruh status SLA terhadap tanggal hari ini.
   - params: {{}}
   - auto_execute: false

DATA REAL-TIME WORKSPACE PRIMA SAAT INI:
{workspace_context_json}
{attachment_section}
KONTEKS HALAMAN / ITEM YANG SEDANG DIBUKA PENGGUNA SAAT INI:
{page_context_text or "(Pengguna berada di halaman umum PRIMA)"}

RIWAYAT PERCAKAPAN SEBELUMNYA DI SESI INI:
{conversation_history_text or "(Ini adalah pesan pertama dalam sesi diskusi)"}

PERTANYAAN / PERINTAH PENGGUNA SAAT INI:
"{user_query}"

Kembalikan TEPAT dalam format raw JSON object (tanpa blok markdown ```json):
{{
  "intent_kind": "QUESTION" | "COMMAND" | "HYBRID",
  "answer": "Jawaban atau konfirmasi dalam Bahasa Indonesia yang ringkas, jelas, dan informatif (boleh menggunakan poin-poin singkat dengan tanda - atau **teks tebal**).",
  "highlights": [
    "Maksimal 3 poin ringkasan/temuan kunci singkat (opsional, kosongkan [] jika jawaban sudah sangat pendek)"
  ],
  "referenced_items": [
    {{
      "id": "ID asli dari data (mis. REQ-001, VAL-..., D-...)",
      "category": "Pekerjaan Pengadaan" | "Hasil Analisis AI" | "Dokumen & Template" | "Warkat Jaminan" | "Target SLA",
      "title": "Judul / nama item",
      "subtitle": "Info ringkas status / skor / PIC",
      "badge": "Label status singkat",
      "is_urgent": false,
      "href": "/dashboard/..."
    }}
  ],
  "command": null atau {{
    "type": "NAVIGATE" | "COMPLETE_SLA" | "ESCALATE_SLA" | "SUBMIT_RECOVERY_PLAN" | "UPDATE_JOB_STATUS" | "MOVE_JOB_STAGE" | "CREATE_PROCUREMENT" | "EVALUATE_SLA",
    "label": "Teks tombol aksi singkat, mis. 'Tandai Selesai: Evaluasi Teknis' atau 'Buka Unggah Dokumen'",
    "description": "Penjelasan 1 kalimat tentang aksi yang akan dijalankan",
    "auto_execute": false,
    "params": {{}}
  }},
  "suggested_followups": [
    "2 saran pertanyaan atau perintah lanjutan yang relevan dan singkat"
  ]
}}"""

        parts_payload.append({"text": prompt})
        # Strictly locked to 'cekatan' tier as requested (or routed to external brain if configured)
        parsed, ai_meta = await self._generate_json_with_failover(
            parts_payload,
            ai_tier="cekatan",
            allow_long_timeout=False,
            context_kind="chat",
        )
        return parsed, ai_meta


gemini_service = GeminiService()
