import asyncio
import base64
import csv
import io
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Union

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

_FALLBACK_GEMINI_MODELS = [
    "gemini-4-hydrogen",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

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
        primary = (settings.gemini_model or "gemini-4-hydrogen").strip().replace("models/", "")
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
        timeout_sec: float = 95.0,
    ) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        gen_config: Dict[str, Any] = {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        }
        if "gemini-4" in model_name:
            # Avoid reasoning timeouts on large PDF/JSON payloads while keeping full JSON accuracy
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [{"parts": parts_payload}],
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
        timeout_sec: float = 70.0,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for model_name in self._model_candidates():
            # Keep total worst-case failover below Cloudflare's 100s proxy read timeout
            model_timeout = min(max(timeout_sec, 68.0), 70.0) if "gemini-4" in model_name else min(timeout_sec, 25.0)
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
    ) -> Dict[str, Any]:
        """OCR & parse Bank Guarantee, Surety Bond, Contract, or Bid Letter using real Gemini AI."""
        if not self.is_configured():
            raise AIExtractionError("Layanan ekstraksi AI belum dikonfigurasi (GEMINI_API_KEY).")

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
            parsed = await self._generate_json_with_failover(parts_payload, timeout_sec=40.0)
            return self._normalize_guarantee(parsed)
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
    ) -> Dict[str, Any]:
        """
        Extract structured checklist criteria (with categories, guidance, mandatory flags, and weights)
        from an uploaded template file (PDF, DOCX, XLSX, CSV, TXT, or scanned image).
        """
        if not self.is_configured():
            raise AIExtractionError("Layanan AI belum dikonfigurasi (GEMINI_API_KEY).")

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
            parsed = await self._generate_json_with_failover(parts_payload, timeout_sec=45.0)
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

        if not self.is_configured():
            raise AIExtractionError("Layanan validasi AI belum dikonfigurasi (GEMINI_API_KEY).")

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
            parsed = await self._generate_json_with_failover(parts_payload, timeout_sec=50.0)
            if "overall_score" not in parsed or "checklist_evaluations" not in parsed or "extracted_project" not in parsed:
                raise ValueError("Respon JSON dari AI tidak memiliki field wajib (overall_score, checklist_evaluations, extracted_project)")
            return parsed
        except AIExtractionError:
            raise
        except Exception as exc:
            logger.error(f"Gemini document validation failed: {exc}")
            raise AIExtractionError(f"Validasi AI terhadap dokumen gagal: {exc}") from exc


gemini_service = GeminiService()
