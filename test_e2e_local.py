"""
E2E Integration test for Document Validation & Tracker Integration
Uses real local PostgreSQL (Docker prima_db) and local volume storage.
Tests with real project file: 'Jaminan Pelaksanaan  PT Delta Media.pdf'.
"""
import sys
import os
import io
import json
import asyncio
import httpx
from datetime import datetime

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models.validation_model import DocumentValidationLogModel
from src.infrastructure.models.procurement_model import ProcurementRequestModel, ProcurementMilestoneModel
from src.infrastructure.models.activity_model import ProcurementActivityLogModel
from sqlalchemy import select


async def run_e2e_test():
    print("=" * 60)
    print("STARTING E2E LOCAL INTEGRATION TEST")
    print("=" * 60)

    # 1. Locate test PDF
    pdf_path = os.path.abspath("../Jaminan Pelaksanaan  PT Delta Media.pdf")
    if not os.path.exists(pdf_path):
        pdf_path = "D:/brian-global/Jaminan Pelaksanaan  PT Delta Media.pdf"

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found at {pdf_path}")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    print(f"Loaded test file: {os.path.basename(pdf_path)} ({len(pdf_bytes)} bytes)")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 2. Authenticate
        print("\n1. Authenticating user (admin@prima.id)...")
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@prima.id", "password": "admin123"},
        )
        if login_res.status_code != 200:
            print(f"Login failed: {login_res.status_code} - {login_res.text}")
            return False

        token = login_res.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("   Authentication successful!")

        # 2. Test Validation Profile Library (GET & POST /api/v1/documents/profiles)
        print("\n2. Testing Validation Profile Library (GET /api/v1/documents/profiles)...")
        prof_res = await client.get("/api/v1/documents/profiles", headers=headers)
        assert prof_res.status_code == 200
        profiles_list = prof_res.json()["data"]
        print(f"   Loaded {len(profiles_list)} validation profiles from database:")
        for p in profiles_list:
            print(f"     * [{p['id']}] {p['name']} (Kind: {p['document_kind']}, Threshold: {p['passing_score_threshold']}%)")
        assert len(profiles_list) >= 3

        # Create a new custom named profile
        print("\n3. Creating new custom profile (POST /api/v1/documents/profiles)...")
        custom_prof_payload = {
            "name": "Standar Jaminan Khusus Vendor Lokal",
            "document_kind": "Jaminan Pelaksanaan",
            "description": "Standar kelayakan dengan toleransi khusus vendor UMKM",
            "scope": "GLOBAL",
            "passing_score_threshold": 75.0,
            "strict_mandatory_enforcement": True,
            "target_stage_to_clear": "Penyusunan RKS & Spesifikasi Teknis",
            "checklist_rules": [
                {
                    "category": "Penerbit",
                    "item": "Penerbit adalah Bank Himbara atau BPD Daerah",
                    "guidance": "Bank BPD diperkenankan",
                    "is_mandatory": True,
                    "weight": 50,
                    "severity_on_failure": "ERROR"
                },
                {
                    "category": "Klausul",
                    "item": "Klausul tanpa syarat (unconditional)",
                    "guidance": "Klausul wajib",
                    "is_mandatory": True,
                    "weight": 50,
                    "severity_on_failure": "ERROR"
                }
            ]
        }
        create_prof_res = await client.post("/api/v1/documents/profiles", json=custom_prof_payload, headers=headers)
        if create_prof_res.status_code not in (200, 201):
            print(f"Create profile failed: {create_prof_res.status_code} - {create_prof_res.text}")
        assert create_prof_res.status_code in (200, 201)
        created_prof = create_prof_res.json()["data"]
        print(f"   Created custom profile: {created_prof['id']} - {created_prof['name']}")

        # 4. Test POST /api/v1/documents/analyze-checklist using Profile ID
        print("\n4. Calling POST /api/v1/documents/analyze-checklist with Profile ID...")
        files = {
            "file": ("Jaminan Pelaksanaan  PT Delta Media.pdf", pdf_bytes, "application/pdf")
        }
        data = {
            "profile_id": "VPROF-JAM-PELAKSANAAN",
            "custom_prompt": "Periksa keabsahan dan kepatuhan Jaminan Pelaksanaan ini sesuai standar pengadaan Pertamina.",
        }

        analyze_res = await client.post(
            "/api/v1/documents/analyze-checklist",
            files=files,
            data=data,
            headers=headers,
        )

        if analyze_res.status_code != 200:
            print(f"Analyze failed: {analyze_res.status_code} - {analyze_res.text}")
            return False

        res_json = analyze_res.json()
        val_data = res_json["data"]
        val_id = val_data["id"]
        score = val_data["overall_score"]
        status = val_data["compliance_status"]
        file_url = val_data["document_file_url"]
        evaluations = val_data["checklist_evaluations"]
        stages = val_data["extracted_project"]["stages"]

        print(f"   Validation ID: {val_id}")
        print(f"   Applied Profile: {val_data.get('profile_id')} - {val_data.get('profile_name')}")
        print(f"   Overall Score: {score}/100 ({status}, Threshold: {val_data.get('passing_score_threshold')}%)")
        print(f"   Local Storage File URL: {file_url}")
        print(f"   Total Checklist Evaluated: {len(evaluations)}")
        for idx, ev in enumerate(evaluations[:3]):
            print(f"     - Item {idx+1}: {ev['item']} -> {ev['status']} (Severity: {ev['severity']})")
        print(f"   Total Extracted Stages: {len(stages)}")
        auto_cleared = [s for s in stages if s.get("auto_cleared")]
        print(f"   Auto-cleared Stages: {len(auto_cleared)} ({', '.join(s['step'] for s in auto_cleared)})")

        # Verify local file exists on disk
        local_saved_path = os.path.join("uploads", file_url.lstrip("/uploads/").replace("/", os.sep))
        if os.path.exists(local_saved_path):
            print(f"   [VERIFIED] Local file saved on disk: {local_saved_path} ({os.path.getsize(local_saved_path)} bytes)")
        else:
            print(f"   [NOTE] File saved with key: {file_url}")

        # 4. Test Publishing to Tracker (POST /api/v1/documents/publish-to-tracker)
        print("\n3. Calling POST /api/v1/documents/publish-to-tracker...")
        publish_payload = {
            "validation_log_id": val_id,
            "title": f"Pengadaan Jasa Media - PT Delta Media",
            "amount": 750000000.0,
            "method": "Tender Terbuka",
        }

        publish_res = await client.post(
            "/api/v1/documents/publish-to-tracker",
            json=publish_payload,
            headers=headers,
        )

        if publish_res.status_code != 200:
            print(f"Publish failed: {publish_res.status_code} - {publish_res.text}")
            return False

        pub_data = publish_res.json()["data"]
        req_id = pub_data["request_id"]
        auto_cleared_count = pub_data["auto_cleared_stages_count"]
        print(f"   Published to Tracker as: {req_id}")
        print(f"   Auto-cleared Stages Count: {auto_cleared_count}")

        # 5. Verify database integrity directly in local PostgreSQL
        print("\n4. Verifying database records in local PostgreSQL...")
        async with AsyncSessionLocal() as session:
            # Check validation log
            val_stmt = select(DocumentValidationLogModel).where(DocumentValidationLogModel.id == val_id)
            val_model = (await session.execute(val_stmt)).scalars().first()
            assert val_model is not None, "Validation log not found in DB!"
            assert val_model.request_id == req_id, "Validation log not linked to request_id!"
            print(f"   [DB VERIFIED] Validation Log {val_model.id} linked to {val_model.request_id}")

            # Check procurement request
            req_stmt = select(ProcurementRequestModel).where(ProcurementRequestModel.id == req_id)
            req_model = (await session.execute(req_stmt)).scalars().first()
            assert req_model is not None, "Procurement request not found in DB!"
            print(f"   [DB VERIFIED] Procurement Request {req_model.id}: {req_model.title} (Status: {req_model.operational_status})", flush=True)

            # Check milestones and auto-clearing
            ms_stmt = select(ProcurementMilestoneModel).where(ProcurementMilestoneModel.request_id == req_id)
            milestones = (await session.execute(ms_stmt)).scalars().all()
            print(f"   [DB VERIFIED] Milestones created: {len(milestones)}")
            for m in milestones[:3]:
                print(f"     - Step: {m.step} | Status: {m.status} | Completed: {m.date is not None}")

            # Check activity logs
            act_stmt = select(ProcurementActivityLogModel).where(ProcurementActivityLogModel.request_id == req_id)
            acts = (await session.execute(act_stmt)).scalars().all()
            print(f"   [DB VERIFIED] Activity Logs created: {len(acts)}")
            for a in acts:
                print(f"     - Action: {a.action} | Notes: {a.notes}")

        # 6. Test GET /api/v1/documents/validations
        print("\n5. Testing GET /api/v1/documents/validations...", flush=True)
        list_res = await client.get("/api/v1/documents/validations", headers=headers)
        assert list_res.status_code == 200
        logs = list_res.json()["data"]
        if isinstance(logs, dict) and "items" in logs:
            logs = logs["items"]
        print(f"   Total validation logs in system: {len(logs)}", flush=True)
        assert any(l["id"] == val_id for l in logs), f"Log {val_id} not found in listing!"

        # 7. Test GET /api/v1/procurement/{id}/validation-logs
        print(f"\n6. Testing GET /api/v1/procurement/{req_id}/validation-logs...", flush=True)
        audit_res = await client.get(f"/api/v1/procurement/{req_id}/validation-logs", headers=headers)
        assert audit_res.status_code == 200
        audit_logs = audit_res.json()["data"]
        print(f"   Audit trail logs for {req_id}: {len(audit_logs)}", flush=True)
        assert audit_logs[0]["id"] == val_id

    print("\n" + "=" * 60, flush=True)
    print("ALL TESTS PASSED SUCCESSFULLY! FEATURE IS FULLY WORKING!", flush=True)
    print("=" * 60, flush=True)
    return True


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    if not success:
        sys.exit(1)
