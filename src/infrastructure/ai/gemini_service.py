import asyncio
import io
import json
import logging
import re
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
        if _GENAI_AVAILABLE and settings.gemini_api_key:
            try:
                genai.configure(api_key=settings.gemini_api_key)
                self.model = genai.GenerativeModel(settings.gemini_model)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini model: {e}")
                self.model = None
        else:
            self.model = None

    def is_configured(self) -> bool:
        return self.model is not None

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

    def _generate_mock_validation(
        self,
        checklist_items: List[str],
        custom_prompt: Optional[str] = None,
        document_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a realistic, dynamic mock evaluation when Gemini is not configured."""
        doc_clean = (document_name or "Dokumen Pengadaan").replace("_", " ").replace(".pdf", "").replace(".docx", "")
        evaluations = []
        passed_count = 0

        for idx, item in enumerate(checklist_items):
            item_lower = item.lower()
            if any(term in item_lower for term in ["tidak", "kurang", "larangan"]):
                status = "Perlu Perhatian"
                severity = "WARNING"
                evidence = None
                explanation = f"Klausul '{item}' memerlukan klarifikasi tertulis lebih lanjut dari pemohon."
            elif idx % 4 == 3:
                status = "Perlu Perhatian"
                severity = "WARNING"
                evidence = f"Ditemukan pada bagian umum dokumen: 'Klausul terkait {item} masih merujuk ketentuan tahun berjalan'."
                explanation = f"Ketentuan mengenai '{item}' tercantum namun format tanggal/referensi perlu disesuaikan dengan pedoman terbaru."
            else:
                status = "Memenuhi"
                severity = "SUCCESS"
                passed_count += 1
                evidence = f"Kutipan klausul Dokumen: 'Penyedia sanggup memenuhi seluruh syarat kualifikasi dan butir teknis {item} secara penuh'."
                explanation = f"Persyaratan '{item}' tertera jelas dan memenuhi standar pengadaan Pertamina."

            evaluations.append({
                "item": item,
                "status": status,
                "evidence_quote": evidence,
                "explanation": explanation,
                "severity": severity,
            })

        total = max(len(checklist_items), 1)
        score = round((passed_count / total) * 100, 1)
        if score >= 80:
            compliance_status = "Lulus Verifikasi"
        elif score >= 60:
            compliance_status = "Catatan Procurement"
        else:
            compliance_status = "Perlu Perbaikan"

        return {
            "overall_score": score,
            "compliance_status": compliance_status,
            "summary": (
                f"Pemeriksaan AI untuk dokumen '{doc_clean}' telah diselesaikan. "
                f"Sebanyak {passed_count} dari {total} butir checklist berhasil diverifikasi dengan tingkat kesesuaian {score}%. "
                f"Dokumen memenuhi prasyarat awal untuk diteruskan ke tahapan proses pengadaan."
            ),
            "checklist_evaluations": evaluations,
            "recommendations": [
                "Pastikan nomor referensi tender dan tanggal berita acara disinkronkan ke dalam sistem e-Procurement.",
                "Lengkapi lampiran pernyataan pakta integritas bermeterai sebelum penandatanganan SPK/Kontrak.",
                "Lakukan review berkala terhadap kepatuhan SLA tahapan berikutnya."
            ],
            "extracted_project": {
                "title": doc_clean.title(),
                "estimated_amount": 1750000000.0,
                "suggested_method": "Tender Terbuka" if score >= 70 else "Pemilihan Langsung",
                "department_name": "Fungsi Pengadaan & Manajemen Fasilitas",
                "stages": [
                    {
                        "step": "Penyusunan RKS & Spesifikasi Teknis",
                        "status": "Done",
                        "auto_cleared": True,
                        "notes": "Otomatis terpenuhi (auto-cleared) berdasarkan kelengkapan berkas spesifikasi teknis dokumen ini."
                    },
                    {
                        "step": "Rapat Pra-Tender",
                        "status": "In Progress",
                        "auto_cleared": False,
                        "notes": "Tahap aktif saat ini untuk klarifikasi rincian kebutuhan."
                    },
                    {
                        "step": "Pengumuman Pengadaan",
                        "status": "Pending",
                        "auto_cleared": False,
                        "notes": None
                    },
                    {
                        "step": "Pemasukan Dokumen Penawaran",
                        "status": "Pending",
                        "auto_cleared": False,
                        "notes": None
                    },
                    {
                        "step": "Evaluasi Dokumen Penawaran",
                        "status": "Pending",
                        "auto_cleared": False,
                        "notes": None
                    },
                    {
                        "step": "Negosiasi Teknis & Harga",
                        "status": "Pending",
                        "auto_cleared": False,
                        "notes": None
                    },
                    {
                        "step": "Penunjukan Pemenang",
                        "status": "Pending",
                        "auto_cleared": False,
                        "notes": None
                    }
                ]
            }
        }

    async def extract_guarantee_data(self, file_content: bytes, mime_type: str) -> Dict[str, Any]:
        """OCR & parse Bank Guarantee or Insurance Bond."""
        if not self.is_configured():
            if settings.allow_mock_ai:
                await asyncio.sleep(1)
                return dict(_MOCK_RESULT)
            raise AIExtractionError("Layanan ekstraksi AI belum dikonfigurasi (GEMINI_API_KEY).")

        try:
            response = await asyncio.to_thread(
                self.model.generate_content,
                [{"mime_type": mime_type, "data": file_content}, EXTRACTION_PROMPT],
            )
            return self._normalize_guarantee(self._parse_json(response.text))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Gemini returned unparsable output: %s", exc)
            if settings.allow_mock_ai:
                return dict(_MOCK_RESULT)
            raise AIExtractionError("Hasil ekstraksi AI tidak dapat dibaca. Isi data secara manual.") from exc
        except Exception as exc:
            logger.warning("Gemini extraction failed (%s)", exc)
            if settings.allow_mock_ai:
                return dict(_MOCK_RESULT)
            logger.exception("Gemini extraction failed (model=%s)", settings.gemini_model)
            raise AIExtractionError("Ekstraksi AI gagal. Isi data secara manual atau coba lagi.") from exc

    async def validate_document_checklist(
        self,
        file_content: bytes,
        mime_type: str,
        checklist_items: List[str],
        custom_prompt: Optional[str] = None,
        document_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate any document against user-supplied checklist items and prompt.
        Outputs checklist evaluation, score, actionable suggestions, and extracted workflow stages.
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
            if settings.allow_mock_ai:
                await asyncio.sleep(1)
                return self._generate_mock_validation(checklist_items, custom_prompt, document_name)
            raise AIExtractionError("Layanan validasi AI belum dikonfigurasi (GEMINI_API_KEY).")

        bullets = "\n".join(f"- {item}" for item in checklist_items)
        prompt_text = (
            DOCUMENT_CHECKLIST_PROMPT_TEMPLATE
            .replace("{checklist_bullets}", bullets)
            .replace("{custom_prompt}", custom_prompt or "Periksa kelengkapan, konsistensi istilah, dan kepatuhan terhadap pedoman pengadaan barang/jasa.")
            .replace("{document_name}", document_name or "Dokumen Pengadaan")
        )

        extracted_text = self._extract_pdf_text(file_content)
        content_parts: List[Any] = []

        # If document is image or PDF, pass the raw bytes part
        if mime_type.startswith("image/") or mime_type == "application/pdf":
            content_parts.append({"mime_type": mime_type, "data": file_content})

        if extracted_text:
            full_prompt = f"KANDUNGAN TEKS HASIL EKSTRAKSI DOKUMEN:\n\"\"\"\n{extracted_text[:14000]}\n\"\"\"\n\n{prompt_text}"
        else:
            full_prompt = prompt_text

        content_parts.append(full_prompt)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.model.generate_content,
                    content_parts,
                ),
                timeout=6.0,
            )
            parsed = self._parse_json(response.text)
            # Ensure critical keys exist
            if "overall_score" not in parsed or "checklist_evaluations" not in parsed or "extracted_project" not in parsed:
                raise ValueError("JSON response missing required fields")
            return parsed
        except Exception as exc:
            logger.warning(f"Gemini document validation failed: {exc}")
            if settings.allow_mock_ai:
                return self._generate_mock_validation(checklist_items, custom_prompt, document_name)
            raise AIExtractionError(f"Validasi AI terhadap dokumen gagal: {exc}") from exc


gemini_service = GeminiService()
