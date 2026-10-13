import asyncio
import json
import logging
import re
from typing import Any, Dict

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore
    _GENAI_AVAILABLE = False

from src.domain.exceptions import DomainException, ErrorCode
from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

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
    def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce AI output into the shape the frontend expects."""
        result = {key: data.get(key) for key in _MOCK_RESULT}
        value = result.get("value")
        if isinstance(value, str):
            digits = re.sub(r"[^\d]", "", value)
            result["value"] = int(digits) if digits else None
        if result.get("issuer_type") not in _ISSUER_TYPES:
            result["issuer_type"] = "Lainnya" if result.get("issuer_type") else None
        return result

    async def extract_guarantee_data(self, file_content: bytes, mime_type: str) -> Dict[str, Any]:
        if not self.is_configured():
            if settings.allow_mock_ai:
                await asyncio.sleep(1)
                return dict(_MOCK_RESULT)
            raise AIExtractionError("Layanan ekstraksi AI belum dikonfigurasi (GEMINI_API_KEY).")

        try:
            # The SDK call is blocking — keep it off the event loop.
            response = await asyncio.to_thread(
                self.model.generate_content,
                [{"mime_type": mime_type, "data": file_content}, EXTRACTION_PROMPT],
            )
            return self._normalize(self._parse_json(response.text))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Gemini returned unparsable output: %s", exc)
            if settings.allow_mock_ai:
                return dict(_MOCK_RESULT)
            raise AIExtractionError("Hasil ekstraksi AI tidak dapat dibaca. Isi data secara manual.") from exc
        except Exception as exc:  # provider/network/model errors
            logger.warning("Gemini extraction failed (%s)", exc)
            if settings.allow_mock_ai:
                return dict(_MOCK_RESULT)
            logger.exception("Gemini extraction failed (model=%s)", settings.gemini_model)
            raise AIExtractionError("Ekstraksi AI gagal. Isi data secara manual atau coba lagi.") from exc


gemini_service = GeminiService()
