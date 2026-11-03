import asyncio
import base64
import io
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

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

from src.domain.exceptions import DomainException, ErrorCode
from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

_FALLBACK_GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

# ── PROMPTS ─────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
Analyze this document (which is a Bank Guarantee or Insurance Bond).
Extract the following fields and return them EXACTLY as a raw JSON object (without Markdown blocks like ```json).
Fields to extract:
- type: String (e.g. "Jaminan Pelaksanaan", "Jaminan Masa Pemeliharaan", "Jaminan Uang Muka")
- vendor_name: String (Name of the vendor / principal)
- issuer: String (Name of the bank or insurance company issuing the guarantee)
- issuer_type: String ("Bank" or "Asuransi" or "Lainnya")
- beneficiary: String (Usually PT Pertamina Patra Niaga or similar)
- reference_no: String (The guarantee / bond number)
- value: Number (The numeric value of the guarantee in IDR, without formatting)
- issue_date: ISO-8601 Date String (e.g. "2026-01-01T00:00:00Z")
- expiry_date: ISO-8601 Date String (e.g. "2026-12-31T00:00:00Z")

If a field is not found, leave it null. Do not invent values.
"""

DOCUMENT_CHECKLIST_PROMPT_TEMPLATE = """
Anda adalah AI Procurement Auditor & Specialist Senior di PT Pertamina Patra Niaga (Sistem PRIMA).
Tugas Anda adalah memeriksa, memvalidasi, dan menilai dokumen pengadaan yang diunggah berdasarkan checklist dan instruksi pengguna berikut:

DAFTAR CHECKLIST YANG HARUS DIPERIKSA:
{checklist_bullets}

INSTRUKSI KHUSUS / PROMPT PENGGUNA:
{custom_prompt}

NAMA DOKUMEN:
{document_name}

TUGAS UTAMA:
1. Validasi Checklist Mendalam:
   Periksa setiap butir checklist secara objektif dan mendalam terhadap isi dokumen:
   - item: Nama butir checklist sesuai yang diminta.
   - status: "Memenuhi" | "Tidak Memenuhi" | "Perlu Perhatian"
   - evidence_quote: Kutipan kalimat atau bagian teks persis dari dokumen yang membuktikan pemenuhan atau kekurangan tersebut (berikan null jika tidak ditemukan sama sekali).
   - explanation: Penjelasan ringkas dan profesional mengenai alasan status tersebut.
   - severity: "SUCCESS" jika Memenuhi, "WARNING" jika Perlu Perhatian, "ERROR" jika Tidak Memenuhi.

2. Penilaian & Status Dokumen:
   - overall_score: Nilai kepatuhan dokumen dari skala 0 sampai 100 berdasarkan pemenuhan checklist dan kelengkapan dokumen.
   - compliance_status:
     * "Lulus Verifikasi" jika overall_score >= 80 dan tidak ada temuan ERROR fatal.
     * "Catatan Procurement" jika overall_score antara 60 sampai 79 atau ada beberapa catatan yang perlu dilengkapi.
     * "Perlu Perbaikan" jika overall_score < 60 atau dokumen belum memadai.

3. Ringkasan Eksekutif & Saran Perbaikan:
   - summary: Rangkuman eksekutif 2-3 kalimat mengenai kondisi kelaikan dokumen ini.
   - recommendations: 2 sampai 4 butir tindakan konkret perbaikan untuk mengatasi kekurangan yang ditemukan.

4. Ekstraksi Informasi Pekerjaan & Tahapan (Workflow Extraction):
   - title: Nama pekerjaan pengadaan yang tertera di dalam dokumen (atau judul representatif).
   - estimated_amount: Perkiraan nilai pagu anggaran/HPS dalam IDR (angka numeric murni, 0 jika tidak ada).
   - suggested_method: "Tender Terbuka" | "Pemilihan Langsung" | "Penunjukan Langsung"
   - department_name: Unit/Fungsi pemohon (misal "Fungsi Pemeliharaan & Aset", "Fungsi Teknologi Informasi", dsb.)
   - stages: Buat urutan tahapan pekerjaan pengadaan yang harus dilalui proyek ini (biasanya 5 - 8 tahapan).
     Contoh alur standar:
       1. "Penyusunan RKS & Spesifikasi Teknis"
       2. "Rapat Pra-Tender"
       3. "Pengumuman Pengadaan"
       4. "Pemasukan Dokumen Penawaran"
       5. "Evaluasi Dokumen Penawaran"
       6. "Negosiasi Teknis & Harga"
       7. "Penetapan & Penunjukan Pemenang"
     PENTING (Auto-Clear): Jika dokumen yang diperiksa ini membuktikan bahwa tahap awal (misal Penyusunan RKS/Spesifikasi) telah selesai dan memenuhi syarat secara sah, tandai tahap pertama tersebut dengan:
       - status: "Done"
       - auto_cleared: true
       - notes: "Otomatis terpenuhi (auto-cleared) oleh dokumen yang divalidasi."
     Tahap berikutnya tandai:
       - status: "In Progress"
       - auto_cleared: false
       - notes: "Tahap aktif saat ini."
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
      },
      {
        "step": "Rapat Pra-Tender",
        "status": "In Progress",
        "auto_cleared": false,
        "notes": "Tahap aktif berikutnya."
      },
      {
        "step": "Pengumuman Pengadaan",
        "status": "Pending",
        "auto_cleared": false,
        "notes": null
      }
    ]
  }
}
"""

_MOCK_RESULT = {
    "type": "Jaminan Pelaksanaan",
    "vendor_name": "PT Dummy Vendor",
    "issuer": "Bank Dummy",
    "issuer_type": "Bank",
    "beneficiary": "PT Pertamina Patra Niaga",
    "reference_no": "BG/DUMMY/2026",
    "value": 5000000000,
    "issue_date": "2026-01-01T00:00:00Z",
    "expiry_date": "2026-12-31T00:00:00Z",
}

_ISSUER_TYPES = {"Bank", "Asuransi", "Lainnya"}


class AIExtractionError(DomainException):
    """Raised when the AI provider is unavailable or returns unusable output."""

    def __init__(self, message: str):
        super().__init__(message, ErrorCode.INTERNAL_ERROR)


class GeminiService:
    def __init__(self):
        self.api_key = (settings.gemini_api_key or "").strip()
        if _GENAI_AVAILABLE and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(settings.gemini_model)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini SDK model: {e}")
                self.model = None
        else:
            self.model = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _model_candidates(self) -> List[str]:
        candidates: List[str] = []
        primary = (settings.gemini_model or "gemini-3.5-flash-lite").strip().replace("models/", "")
        if primary:
            candidates.append(primary)
        for m in _FALLBACK_GEMINI_MODELS:
            if m not in candidates:
                candidates.append(m)
        return candidates

    def _call_gemini_rest_sync(
        self,
        model_name: str,
        parts_payload: List[Dict[str, Any]],
        timeout_sec: float = 35.0,
    ) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": parts_payload}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
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
        if not content_parts or "text" not in content_parts[0]:
            raise ValueError(f"No text in Gemini response from {model_name}")
        return content_parts[0]["text"]

    async def _generate_json_with_failover(
        self,
        parts_payload: List[Dict[str, Any]],
        timeout_sec: float = 35.0,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for model_name in self._model_candidates():
            try:
                raw_text = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._call_gemini_rest_sync,
                        model_name,
                        parts_payload,
                        timeout_sec,
                    ),
                    timeout=timeout_sec + 3.0,
                )
                parsed = self._parse_json(raw_text)
                logger.info(f"Gemini AI analysis succeeded using model '{model_name}'")
                return parsed
            except urllib.error.HTTPError as http_err:
                err_body = ""
                try:
                    err_body = http_err.read().decode("utf-8", errors="ignore")[:240]
                except Exception:
                    pass
                logger.warning(f"Gemini model '{model_name}' HTTP {http_err.code}: {err_body}")
                last_error = RuntimeError(f"HTTP {http_err.code} from {model_name}: {err_body}")
            except Exception as exc:
                logger.warning(f"Gemini model '{model_name}' error: {exc}")
                last_error = exc

        raise AIExtractionError(f"Seluruh model Gemini gagal memproses dokumen: {last_error}")

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("AI response is not a JSON object")
        return data

    @staticmethod
    def _normalize_guarantee(data: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce AI output into the shape the frontend expects."""
        result = {key: data.get(key) for key in _MOCK_RESULT}
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
            for idx, page in enumerate(reader.pages[:20]):  # limit to first 20 pages
                text = page.extract_text()
                if text:
                    page_texts.append(f"--- Halaman {idx+1} ---\n{text}")
            return "\n\n".join(page_texts)
        except Exception as e:
            logger.warning(f"Could not extract text from PDF via pypdf: {e}")
            return ""

    async def extract_guarantee_data(self, file_content: bytes, mime_type: str) -> Dict[str, Any]:
        """OCR & parse Bank Guarantee or Insurance Bond using real Gemini AI."""
        if not self.is_configured():
            raise AIExtractionError("Layanan ekstraksi AI belum dikonfigurasi (GEMINI_API_KEY).")

        b64_data = base64.b64encode(file_content).decode("ascii")
        parts_payload: List[Dict[str, Any]] = [
            {"inline_data": {"mime_type": mime_type, "data": b64_data}},
            {"text": EXTRACTION_PROMPT},
        ]

        try:
            parsed = await self._generate_json_with_failover(parts_payload, timeout_sec=35.0)
            return self._normalize_guarantee(parsed)
        except AIExtractionError:
            raise
        except Exception as exc:
            logger.exception("Gemini guarantee extraction failed")
            raise AIExtractionError(f"Ekstraksi AI gagal: {exc}") from exc

    async def validate_document_checklist(
        self,
        file_content: bytes,
        mime_type: str,
        checklist_items: List[str],
        custom_prompt: Optional[str] = None,
        document_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate any document against user-supplied checklist items and prompt using real Gemini AI.
        Never uses mock/fallback results.
        """
        if not checklist_items:
            checklist_items = [
                "Nama pekerjaan dan lingkup kebutuhan",
                "Spesifikasi teknis / Kerangka Acuan Kerja",
                "Perkiraan nilai anggaran / HPS",
                "Jadwal pelaksanaan & jangka waktu pemenuhan",
                "Ketentuan jaminan / garansi penyedia"
            ]

        if not self.is_configured():
            raise AIExtractionError("Layanan validasi AI belum dikonfigurasi (GEMINI_API_KEY).")

        bullets = "\n".join(f"- {item}" for item in checklist_items)
        prompt_text = (
            DOCUMENT_CHECKLIST_PROMPT_TEMPLATE
            .replace("{checklist_bullets}", bullets)
            .replace("{custom_prompt}", custom_prompt or "Periksa kelengkapan, konsistensi istilah, dan kepatuhan terhadap pedoman pengadaan barang/jasa.")
            .replace("{document_name}", document_name or "Dokumen Pengadaan")
        )

        extracted_text = self._extract_pdf_text(file_content)
        parts_payload: List[Dict[str, Any]] = []

        # Pass multimodal inline_data for PDF or images
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            b64_data = base64.b64encode(file_content).decode("ascii")
            parts_payload.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})

        if extracted_text:
            full_prompt = f"KANDUNGAN TEKS HASIL EKSTRAKSI DOKUMEN:\n\"\"\"\n{extracted_text[:18000]}\n\"\"\"\n\n{prompt_text}"
        else:
            full_prompt = prompt_text

        parts_payload.append({"text": full_prompt})

        try:
            parsed = await self._generate_json_with_failover(parts_payload, timeout_sec=45.0)
            if "overall_score" not in parsed or "checklist_evaluations" not in parsed or "extracted_project" not in parsed:
                raise ValueError("Respon JSON dari AI tidak memiliki field wajib (overall_score, checklist_evaluations, extracted_project)")
            return parsed
        except AIExtractionError:
            raise
        except Exception as exc:
            logger.error(f"Gemini document validation failed: {exc}")
            raise AIExtractionError(f"Validasi AI terhadap dokumen gagal: {exc}") from exc


gemini_service = GeminiService()
