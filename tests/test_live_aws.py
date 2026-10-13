"""
test_live_aws.py — Full Integration Testing Suite against Live AWS Deployment
Tests all endpoints on http://13.54.230.169:8000
"""
import httpx
import uuid
import sys

BASE_URL = "http://13.54.230.169:8000/api/v1"

results = []

def record(name: str, passed: bool, detail: str = ""):
    status_str = "PASSED" if passed else "FAILED"
    results.append({"name": name, "passed": passed, "detail": detail})
    print(f"[{status_str}] {name} {detail}")

def run_tests():
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    
    print("==================================================")
    print("   Starting Full Live API Test on AWS Server     ")
    print(f"   Target: {BASE_URL}")
    print("==================================================\n")

    # 1. Healthcheck
    try:
        r = client.get("/health")
        passed = r.status_code == 200 and r.json().get("status") == "healthy"
        record("GET /health", passed, f"Status: {r.status_code}, Body: {r.text}")
    except Exception as e:
        record("GET /health", False, str(e))

    # 2. Auth - Login
    token = None
    refresh_token = None
    try:
        r = client.post("/auth/login", json={"email": "admin@prima.id", "password": "admin123"})
        passed = r.status_code == 200 and "access_token" in r.json().get("data", {})
        if passed:
            token = r.json()["data"]["access_token"]
            refresh_token = r.json()["data"]["refresh_token"]
        record("POST /auth/login", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("POST /auth/login", False, str(e))

    if not token:
        print("\nFATAL: Login failed, cannot proceed with authenticated tests.")
        return False

    auth_headers = {"Authorization": f"Bearer {token}"}

    # 3. Auth - Me
    try:
        r = client.get("/auth/me", headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("email") == "admin@prima.id"
        record("GET /auth/me", passed, f"User role: {r.json().get('data', {}).get('role')}")
    except Exception as e:
        record("GET /auth/me", False, str(e))

    # 4. Auth - Refresh
    try:
        r = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        passed = r.status_code == 200 and "access_token" in r.json().get("data", {})
        record("POST /auth/refresh", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("POST /auth/refresh", False, str(e))

    # 5. Users - List active users
    try:
        r = client.get("/users", headers=auth_headers)
        users = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(users, list) and len(users) > 0
        record("GET /users", passed, f"Count: {len(users)} users")
    except Exception as e:
        record("GET /users", False, str(e))

    # 6. Procurement - List
    procurements = []
    try:
        r = client.get("/procurement", headers=auth_headers)
        procurements = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(procurements, list)
        record("GET /procurement", passed, f"Found {len(procurements)} procurements")
    except Exception as e:
        record("GET /procurement", False, str(e))

    # 7. Procurement - Create (Issue 1)
    new_proc_id = None
    try:
        payload = {
            "title": f"Live AWS Test Procurement {uuid.uuid4().hex[:6]}",
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "fpp_id": "FPP-LIVE-001",
            "fpp_name": "FPP Live Tester",
            "amount": 750000000,
            "department_id": "DEPT-IT",
            "department_name": "IT Infrastructure",
            "stage": "Perencanaan",
            "current_step": "Draft",
            "is_urgent": True,
        }
        r = client.post("/procurement", json=payload, headers=auth_headers)
        data = r.json().get("data", {})
        new_proc_id = data.get("id")
        passed = r.status_code in (200, 201) and new_proc_id is not None
        record("POST /procurement (Issue 1)", passed, f"Created ID: {new_proc_id}")
    except Exception as e:
        record("POST /procurement (Issue 1)", False, str(e))

    target_proc_id = new_proc_id or (procurements[0]["id"] if procurements else None)

    # 8. Procurement - Get by ID
    try:
        r = client.get(f"/procurement/{target_proc_id}", headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("id") == target_proc_id
        record(f"GET /procurement/{{id}}", passed, f"Status: {r.status_code}")
    except Exception as e:
        record(f"GET /procurement/{{id}}", False, str(e))

    # 9. Procurement - Move stage
    try:
        r = client.patch(
            f"/procurement/{target_proc_id}/stage",
            json={"stage": "Persiapan", "notes": "Moving stage during live test"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("stage") == "Persiapan"
        record(f"PATCH /procurement/{{id}}/stage", passed, f"New Stage: Persiapan")
    except Exception as e:
        record(f"PATCH /procurement/{{id}}/stage", False, str(e))

    # 10. Procurement - Move step
    try:
        r = client.patch(
            f"/procurement/{target_proc_id}/step",
            json={"step": "Rapat Pra-Tender", "notes": "Moving step live test"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("current_step") == "Rapat Pra-Tender"
        record(f"PATCH /procurement/{{id}}/step", passed, f"New Step: Rapat Pra-Tender")
    except Exception as e:
        record(f"PATCH /procurement/{{id}}/step", False, str(e))

    # 11. Procurement - Update operational status
    try:
        r = client.patch(
            f"/procurement/{target_proc_id}/operational-status",
            json={"status": "On Hold", "reason": "Menunggu persetujuan anggaran"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("operational_status") == "On Hold"
        record(f"PATCH /procurement/{{id}}/operational-status", passed, f"New Status: On Hold")
    except Exception as e:
        record(f"PATCH /procurement/{{id}}/operational-status", False, str(e))

    # 11b. Procurement - Get activities audit trail (New Feature)
    try:
        r = client.get(f"/procurement/{target_proc_id}/activities", headers=auth_headers)
        activities = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(activities, list) and len(activities) > 0
        record("GET /procurement/{id}/activities (Audit Trail)", passed, f"Found {len(activities)} logs")
    except Exception as e:
        record("GET /procurement/{id}/activities (Audit Trail)", False, str(e))

    # 11c. Procurement - Gatekeeper Check (New Feature 2.3)
    try:
        r = client.get(f"/procurement/{target_proc_id}/gatekeeper", headers=auth_headers)
        gk = r.json().get("data", {})
        passed = r.status_code == 200 and "is_ready_to_advance" in gk and "blockers" in gk
        record("GET /procurement/{id}/gatekeeper (Gatekeeper 2.3)", passed, f"Ready: {gk.get('is_ready_to_advance')}")
    except Exception as e:
        record("GET /procurement/{id}/gatekeeper (Gatekeeper 2.3)", False, str(e))

    # 12. Deadlines (D4) - List
    try:
        r = client.get("/deadlines", headers=auth_headers)
        deadlines = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(deadlines, list)
        record("GET /deadlines", passed, f"Found {len(deadlines)} deadlines")
    except Exception as e:
        record("GET /deadlines", False, str(e))

    # 13. Deadlines - Create (Issue 2)
    new_deadline_id = None
    try:
        payload = {
            "request_id": target_proc_id,
            "task_name": "Review Dokumen Spesifikasi Teknis",
            "milestone": "Evaluasi Teknis",
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "department_id": "DEPT-IT",
            "department_name": "IT Infrastructure",
            "target_date": "2026-11-15",
            "status": "On Track",
            "urgency_level": "High",
        }
        r = client.post("/deadlines", json=payload, headers=auth_headers)
        data = r.json().get("data", {})
        new_deadline_id = data.get("id")
        passed = r.status_code in (200, 201) and new_deadline_id is not None
        record("POST /deadlines (Issue 2)", passed, f"Created ID: {new_deadline_id}")
    except Exception as e:
        record("POST /deadlines (Issue 2)", False, str(e))

    # 14. Deadlines - Get by ID
    try:
        r = client.get(f"/deadlines/{new_deadline_id}", headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("id") == new_deadline_id
        record(f"GET /deadlines/{{id}}", passed, f"Status: {r.status_code}")
    except Exception as e:
        record(f"GET /deadlines/{{id}}", False, str(e))

    # 15. Deadlines - Update (Issue 2)
    try:
        r = client.patch(
            f"/deadlines/{new_deadline_id}",
            json={"status": "Selesai", "urgency_level": "Critical"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("status") == "Selesai"
        record(f"PATCH /deadlines/{{id}} (Issue 2)", passed, f"Updated status to Selesai")
    except Exception as e:
        record(f"PATCH /deadlines/{{id}} (Issue 2)", False, str(e))

    # 16. Guarantees (D2) - List
    try:
        r = client.get("/guarantees", headers=auth_headers)
        guars = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(guars, list)
        record("GET /guarantees", passed, f"Found {len(guars)} guarantees")
    except Exception as e:
        record("GET /guarantees", False, str(e))

    # 17. Guarantees - Create
    new_guar_id = None
    try:
        payload = {
            "request_id": target_proc_id,
            "type": "Jaminan Pelaksanaan",
            "vendor_id": "VND-LIVE-01",
            "vendor_name": "PT Sumber Energi Maju",
            "issuer": "Bank Mandiri",
            "issuer_type": "Bank",
            "beneficiary": "PT Pertamina Patra Niaga",
            "reference_no": f"BG-LIVE-{uuid.uuid4().hex[:6].upper()}",
            "value": 350000000,
            "issue_date": "2026-02-01",
            "expiry_date": "2026-12-31",
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "status": "Aktif",
        }
        r = client.post("/guarantees", json=payload, headers=auth_headers)
        data = r.json().get("data", {})
        new_guar_id = data.get("id")
        passed = r.status_code in (200, 201) and new_guar_id is not None
        record("POST /guarantees", passed, f"Created ID: {new_guar_id}")
    except Exception as e:
        record("POST /guarantees", False, str(e))

    # 18. Guarantees - Get by ID
    try:
        r = client.get(f"/guarantees/{new_guar_id}", headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("id") == new_guar_id and "is_threshold_compliant" in r.json().get("data", {})
        record(f"GET /guarantees/{{id}} (Threshold 1.4)", passed, f"Threshold Compliant: {r.json().get('data', {}).get('is_threshold_compliant')}")
    except Exception as e:
        record(f"GET /guarantees/{{id}} (Threshold 1.4)", False, str(e))

    # 19. Guarantees - Update
    try:
        r = client.patch(
            f"/guarantees/{new_guar_id}",
            json={"status": "Mendekati Expiry", "next_action": "Segera hubungi vendor"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("status") == "Mendekati Expiry"
        record(f"PATCH /guarantees/{{id}}", passed, f"Status: Mendekati Expiry")
    except Exception as e:
        record(f"PATCH /guarantees/{{id}}", False, str(e))

    # 20. Guarantees - S3 Presigned URL (Valid MIME)
    try:
        r = client.get(f"/guarantees/{new_guar_id}/upload-url?content_type=application/pdf", headers=auth_headers)
        has_post = "presigned_post" in r.json().get("data", {})
        passed = r.status_code == 200 and has_post
        record("GET /guarantees/{id}/upload-url (Valid PDF)", passed, f"Presigned URL generated")
    except Exception as e:
        record("GET /guarantees/{id}/upload-url (Valid PDF)", False, str(e))

    # 21. Guarantees - S3 MIME Security Validation (Invalid executable)
    try:
        r = client.get(f"/guarantees/{new_guar_id}/upload-url?content_type=application/x-sh", headers=auth_headers)
        passed = r.status_code in (400, 422)
        record("GET /guarantees/{id}/upload-url (Reject .sh)", passed, f"Rejected with {r.status_code}")
    except Exception as e:
        record("GET /guarantees/{id}/upload-url (Reject .sh)", False, str(e))

    # 22. Guarantees - Extract AI OCR
    try:
        dummy_file = b"%PDF-1.4 dummy guarantee file content for extraction"
        files = {"file": ("test_bg.pdf", dummy_file, "application/pdf")}
        r = client.post("/guarantees/extract", files=files, headers=auth_headers)
        data = r.json().get("data", {})
        passed = r.status_code == 200 and "type" in data and "reference_no" in data
        record("POST /guarantees/extract (OCR)", passed, f"Extracted type: {data.get('type')}")
    except Exception as e:
        record("POST /guarantees/extract (OCR)", False, str(e))

    # 22b. Guarantees - View URL Presigned
    try:
        r = client.get(f"/guarantees/{new_guar_id}/view-url", headers=auth_headers)
        data = r.json().get("data", {})
        passed = r.status_code == 200 and "view_url" in data
        record("GET /guarantees/{id}/view-url", passed, f"Presigned View URL generated")
    except Exception as e:
        record("GET /guarantees/{id}/view-url", False, str(e))

    # 22c. Guarantees - Amend (Lifecycle Extension)
    try:
        amend_payload = {
            "amendment_no": "AMD-001/2026",
            "new_expiry_date": "2027-06-30T00:00:00Z",
            "new_value": 750000000,
            "amendment_reason": "Perpanjangan masa kontrak proyek"
        }
        r = client.post(f"/guarantees/{new_guar_id}/amend", json=amend_payload, headers=auth_headers)
        passed = r.status_code == 200 and "Amandemen disetujui" in r.json().get("data", {}).get("next_action", "")
        record("POST /guarantees/{id}/amend", passed, "Amended successfully")
    except Exception as e:
        record("POST /guarantees/{id}/amend", False, str(e))

    # 22d. Guarantees - Claim (Lifecycle Claim)
    try:
        claim_payload = {
            "claim_letter_no": "SRT-KLAIM/2026/088",
            "claim_reason": "Vendor wanprestasi keterlambatan progres",
            "claim_amount": 750000000
        }
        r = client.post(f"/guarantees/{new_guar_id}/claim", json=claim_payload, headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("status") == "Klaim Diajukan"
        record("POST /guarantees/{id}/claim", passed, "Claim submitted")
    except Exception as e:
        record("POST /guarantees/{id}/claim", False, str(e))

    # 22e. Guarantees - Release (Lifecycle Return to Vendor)
    try:
        release_payload = {
            "bast_no": "BAST-PRIMA/2026/999",
            "release_notes": "Pekerjaan selesai 100%, warkat jaminan asli diserahkan kembali"
        }
        r = client.post(f"/guarantees/{new_guar_id}/release", json=release_payload, headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("status") == "Dikembalikan"
        record("POST /guarantees/{id}/release", passed, "Released to vendor")
    except Exception as e:
        record("POST /guarantees/{id}/release", False, str(e))

    # 23. Guarantees - Delete / Rollback
    try:
        r = client.delete(f"/guarantees/{new_guar_id}", headers=auth_headers)
        passed = r.status_code == 200
        record("DELETE /guarantees/{id} (Rollback)", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("DELETE /guarantees/{id} (Rollback)", False, str(e))

    # 24. Documents (D2) - List
    try:
        r = client.get("/documents", headers=auth_headers)
        docs = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(docs, list)
        record("GET /documents", passed, f"Found {len(docs)} documents")
    except Exception as e:
        record("GET /documents", False, str(e))

    # 25. Documents - Create
    new_doc_id = None
    try:
        payload = {
            "request_id": target_proc_id,
            "name": f"Surat_Pernyataan_{uuid.uuid4().hex[:6]}.pdf",
            "type": "Surat Pernyataan Minat",
            "document_kind": "administrative",
            "status": "Catatan Procurement",
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "issues": ["Perlu tandatangan direktur utama"],
            "next_action": "Kirim kembali ke vendor",
        }
        r = client.post("/documents", json=payload, headers=auth_headers)
        data = r.json().get("data", {})
        new_doc_id = data.get("id")
        passed = r.status_code in (200, 201) and new_doc_id is not None
        record("POST /documents", passed, f"Created ID: {new_doc_id}")
    except Exception as e:
        record("POST /documents", False, str(e))

    # 26. Documents - Get by ID
    try:
        r = client.get(f"/documents/{new_doc_id}", headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("id") == new_doc_id
        record(f"GET /documents/{{id}}", passed, f"Status: {r.status_code}")
    except Exception as e:
        record(f"GET /documents/{{id}}", False, str(e))

    # 27. Documents - PATCH status
    try:
        r = client.patch(
            f"/documents/{new_doc_id}/status",
            json={"status": "Tindak Lanjut FPP"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("status") == "Tindak Lanjut FPP"
        record("PATCH /documents/{id}/status", passed, f"Updated to Tindak Lanjut FPP")
    except Exception as e:
        record("PATCH /documents/{id}/status", False, str(e))

    # 28. Documents - PUT status
    try:
        r = client.put(
            f"/documents/{new_doc_id}",
            json={"status": "Lulus Verifikasi"},
            headers=auth_headers,
        )
        passed = r.status_code == 200 and r.json().get("data", {}).get("status") == "Lulus Verifikasi"
        record("PUT /documents/{id}", passed, f"Updated to Lulus Verifikasi")
    except Exception as e:
        record("PUT /documents/{id}", False, str(e))

    # 28b. Documents - View URL Presigned
    try:
        r = client.get(f"/documents/{new_doc_id}/view-url", headers=auth_headers)
        data = r.json().get("data", {})
        passed = r.status_code == 200 and "view_url" in data
        record("GET /documents/{id}/view-url", passed, f"Presigned View URL generated")
    except Exception as e:
        record("GET /documents/{id}/view-url", False, str(e))

    # 29. Notifications - List
    try:
        r = client.get("/notifications", headers=auth_headers)
        notifs = r.json().get("data", [])
        passed = r.status_code == 200 and isinstance(notifs, list)
        record("GET /notifications", passed, f"Found {len(notifs)} notifications")
    except Exception as e:
        record("GET /notifications", False, str(e))

    # 30. Notifications - Create
    new_notif_id = None
    try:
        payload = {
            "title": "Notifikasi Pengujian Otomatis Live",
            "description": "Seluruh endpoint diuji secara otomatis pada server AWS.",
            "message": "Seluruh endpoint diuji secara otomatis pada server AWS.",
            "type": "System",
            "category": "Pengadaan",
        }
        r = client.post("/notifications", json=payload, headers=auth_headers)
        data = r.json().get("data", {})
        new_notif_id = data.get("id")
        passed = r.status_code in (200, 201) and new_notif_id is not None
        record("POST /notifications", passed, f"Created ID: {new_notif_id}")
    except Exception as e:
        record("POST /notifications", False, str(e))

    # 31. Notifications - Mark read
    target_notif_id = new_notif_id or (notifs[0]["id"] if notifs else None)
    try:
        r = client.put(f"/notifications/{target_notif_id}/read", headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("is_read") is True
        record("PUT /notifications/{id}/read", passed, f"is_read=True")
    except Exception as e:
        record("PUT /notifications/{id}/read", False, str(e))

    # 32. Notifications - Mark all read
    try:
        r = client.put("/notifications/read-all", headers=auth_headers)
        passed = r.status_code == 200
        record("PUT /notifications/read-all", passed, f"Status: {r.status_code}")
    except Exception as e:
        record("PUT /notifications/read-all", False, str(e))

    # 33. Settings - Get
    try:
        r = client.get("/settings", headers=auth_headers)
        data = r.json().get("data", {})
        passed = r.status_code == 200 and "ai_sensitivity" in data
        record("GET /settings", passed, f"Theme: {data.get('theme')}")
    except Exception as e:
        record("GET /settings", False, str(e))

    # 34. Settings - Update (RBAC Super Admin / Manager)
    try:
        update_payload = {
            "email_notifications": True,
            "whatsapp_notifications": True,
            "sla_warning_days": 4,
            "auto_escalation": True,
            "auto_escalate_days": 2,
            "escalation_manager_id": "USR-006",
            "approval_threshold": 500000000,
            "department_reviewers": {"DEPT-IT": "USR-001"},
            "milestone_durations": {"Rapat Pra-Tender": 3},
            "ai_sensitivity": "High",
            "theme": "Light",
        }
        r = client.put("/settings", json=update_payload, headers=auth_headers)
        passed = r.status_code == 200 and r.json().get("data", {}).get("sla_warning_days") == 4
        record("PUT /settings", passed, f"sla_warning_days=4")
    except Exception as e:
        record("PUT /settings", False, str(e))

    # 35. Dynamic Milestones by Method (Penunjukan Langsung -> 4 milestones)
    dyn_req_id = None
    try:
        req_payload = {
            "title": "Pengadaan Lisensi Software Database Oracle (Penunjukan Langsung)",
            "pic_id": "USR-001",
            "pic_name": "Ahmad Fauzi",
            "fpp_id": "FPP-2026-901",
            "fpp_name": "FPP TI Database",
            "amount": 250000000,
            "department_id": "DEPT-IT",
            "department_name": "Teknologi Informasi",
            "procurement_method": "Penunjukan Langsung",
        }
        r = client.post("/procurement", json=req_payload, headers=auth_headers)
        if r.status_code in (200, 201):
            dyn_req_id = r.json().get("data", {}).get("id")
            # Fetch milestones
            r_ms = client.get(f"/procurement/{dyn_req_id}/milestones", headers=auth_headers)
            ms_list = r_ms.json().get("data", [])
            passed = len(ms_list) == 4 and ms_list[0]["step"] == "Undangan Penunjukan Langsung"
            record("POST /procurement (Penunjukan Langsung 4 Milestones)", passed, f"Total milestones: {len(ms_list)}")
        else:
            record("POST /procurement (Penunjukan Langsung 4 Milestones)", False, f"Status: {r.status_code}")
    except Exception as e:
        record("POST /procurement (Penunjukan Langsung 4 Milestones)", False, str(e))

    # 36. Assign / Handover PIC & Audit Trail
    if dyn_req_id:
        try:
            handover_payload = {
                "new_pic_id": "USR-002",
                "new_pic_name": "Siti Rahmawati",
                "handover_notes": "Serah terima tugas proyek lisensi database Q4 ke Siti Rahmawati",
            }
            r = client.patch(f"/procurement/{dyn_req_id}/assign-pic", json=handover_payload, headers=auth_headers)
            pic_updated = r.status_code == 200 and r.json().get("data", {}).get("pic", {}).get("name") == "Siti Rahmawati"
            # Verify activity log
            r_act = client.get(f"/procurement/{dyn_req_id}/activities", headers=auth_headers)
            acts = r_act.json().get("data", [])
            has_handover_log = any(a.get("action") == "HANDOVER_PIC" for a in acts)
            passed = pic_updated and has_handover_log
            record("PATCH /procurement/{id}/assign-pic (Handover & Audit Log)", passed, f"PIC updated={pic_updated}, Log recorded={has_handover_log}")
        except Exception as e:
            record("PATCH /procurement/{id}/assign-pic (Handover & Audit Log)", False, str(e))

        # Cleanup
        try:
            client.delete(f"/procurement/{dyn_req_id}", headers=auth_headers)
        except Exception:
            pass

    # 37. Evaluate SLA (Feature 3.1 & 3.2)
    try:
        r = client.post("/deadlines/evaluate-sla", headers=auth_headers)
        eval_data = r.json().get("data", {})
        passed = r.status_code == 200 and "total_evaluated" in eval_data and "on_track" in eval_data
        record("POST /deadlines/evaluate-sla (Feature 3.1 & 3.2)", passed, f"Total: {eval_data.get('total_evaluated')}, Overdue: {eval_data.get('overdue')}, Escalated: {eval_data.get('escalated')}")
    except Exception as e:
        record("POST /deadlines/evaluate-sla (Feature 3.1 & 3.2)", False, str(e))

    # 38. Escalate Deadline Manually
    try:
        esc_payload = {
            "escalated_to": "Manager Pengadaan Korporat",
            "reason": "Keterlambatan penyelesaian dokumen legal tender melebihi 3 hari",
        }
        r = client.post(f"/deadlines/{new_deadline_id}/escalate", json=esc_payload, headers=auth_headers)
        d_esc = r.json().get("data", {})
        passed = r.status_code == 200 and d_esc.get("is_escalated") is True and d_esc.get("escalated_to") == "Manager Pengadaan Korporat"
        record(f"POST /deadlines/{{id}}/escalate (Feature 3.2)", passed, f"Escalated to: {d_esc.get('escalated_to')}")
    except Exception as e:
        record(f"POST /deadlines/{{id}}/escalate (Feature 3.2)", False, str(e))

    # 39. Submit Recovery Plan
    try:
        rec_payload = {
            "recovery_plan": "Penambahan personel analis legal dan percepatan verifikasi vendor paralel",
            "recovery_date": "2026-11-15T00:00:00Z",
        }
        r = client.post(f"/deadlines/{new_deadline_id}/recovery-plan", json=rec_payload, headers=auth_headers)
        d_rec = r.json().get("data", {})
        passed = r.status_code == 200 and d_rec.get("recovery_plan") is not None
        record(f"POST /deadlines/{{id}}/recovery-plan (Feature 3.2)", passed, f"Plan submitted: {d_rec.get('recovery_plan')[:35]}...")
    except Exception as e:
        record(f"POST /deadlines/{{id}}/recovery-plan (Feature 3.2)", False, str(e))

    # 40. Document Revision (Feature 1.3)
    rev_doc_id = None
    try:
        rev_payload = {
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "revision_notes": "Telah dilengkapi tanda tangan Direktur Utama dan materai elektronik",
            "document_number": "SPM/REV/2026/001",
        }
        r = client.post(f"/documents/{new_doc_id}/revision", json=rev_payload, headers=auth_headers)
        data = r.json().get("data", {})
        rev_doc_id = data.get("id")
        passed = r.status_code in (200, 201) and data.get("version_number") == 2 and data.get("parent_document_id") == new_doc_id
        record("POST /documents/{id}/revision (Feature 1.3)", passed, f"Created v{data.get('version_number')} ID: {rev_doc_id}")
    except Exception as e:
        record("POST /documents/{id}/revision (Feature 1.3)", False, str(e))

    # 41. Document Revisions List (Feature 1.3)
    try:
        r = client.get(f"/documents/{new_doc_id}/revisions", headers=auth_headers)
        rev_list = r.json().get("data", [])
        passed = r.status_code == 200 and len(rev_list) >= 2 and any(d.get("version_number") == 2 for d in rev_list)
        record("GET /documents/{id}/revisions (Feature 1.3)", passed, f"Found {len(rev_list)} versions in family")
    except Exception as e:
        record("GET /documents/{id}/revisions (Feature 1.3)", False, str(e))

    # 42. Procurement Analytics Overview (Feature 4.3)
    try:
        r = client.get("/procurement/analytics/overview", headers=auth_headers)
        an_data = r.json().get("data", {})
        passed = (
            r.status_code == 200
            and "summary" in an_data
            and "department_compliance" in an_data
            and "bottlenecks" in an_data
            and "vendor_risk_index" in an_data
        )
        rate = an_data.get("summary", {}).get("overall_compliance_rate")
        record("GET /procurement/analytics/overview (Feature 4.3)", passed, f"Overall SLA Compliance: {rate}%")
    except Exception as e:
        record("GET /procurement/analytics/overview (Feature 4.3)", False, str(e))

    # Summary
    print("\n==================================================")
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = total - passed_count
    print(f"   Summary: {passed_count}/{total} PASSED ({failed_count} FAILED)")
    print("==================================================")
    return failed_count == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
