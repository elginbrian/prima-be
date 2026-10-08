import json
import base64
from typing import Dict, Any
from src.infrastructure.config.settings import settings
import google.generativeai as genai

class GeminiService:
    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None

    def is_configured(self):
        return self.model is not None

    async def extract_guarantee_data(self, file_content: bytes, mime_type: str) -> Dict[str, Any]:
        import asyncio
        if not self.is_configured():
            # Return dummy data if not configured
            await asyncio.sleep(2)
            return {
                "type": "Jaminan Pelaksanaan",
                "vendor_name": "PT Dummy Vendor",
                "issuer": "Bank Dummy",
                "issuer_type": "Bank",
                "beneficiary": "PT Pertamina Patra Niaga",
                "reference_no": "BG/DUMMY/2026",
                "value": 5000000000,
                "issue_date": "2026-01-01T00:00:00Z",
                "expiry_date": "2026-12-31T00:00:00Z"
            }

        prompt = """
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
        
        If a field is not found, try to infer it from the context or leave it empty/null.
        """
        
        try:
            response = self.model.generate_content([
                {'mime_type': mime_type, 'data': file_content},
                prompt
            ])
            
            response_text = response.text.strip()
            # Clean up markdown formatting if Gemini includes it
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
                
            data = json.loads(response_text.strip())
            return data
        except Exception as e:
            print(f"Gemini extraction failed: {e}")
            raise Exception("Failed to extract data using AI")

gemini_service = GeminiService()

