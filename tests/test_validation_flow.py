import io
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from src.infrastructure.config import settings
from src.infrastructure.database import get_db

test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
TestAsyncSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def override_get_db():
    async with TestAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@prima.id", "password": "admin123"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_full_document_validation_and_publish_flow(client: AsyncClient, auth_headers: dict):
    """
    Test Modul D1 -> D3/D4 pipeline:
    1. Upload & analyze document against custom checklist.
    2. Check AI evaluations, score, and extracted workflow stages.
    3. Publish to Tracker as a new Procurement Request with auto-cleared stage.
    4. Verify validation log appears in the request's audit trail.
    """
    # 1. Prepare sample document and checklist
    sample_pdf_content = b"%PDF-1.4 Mock Kerangka Acuan Kerja Pengadaan Server High Availability..."
    checklist = [
        "Spesifikasi teknis Server Rack 42U",
        "Jadwal pengiriman maksimal 60 hari kalender",
        "Ketentuan jaminan pelaksanaan 5%",
        "Termin pembayaran bertahap 30 hari",
    ]
    files = {
        "file": ("KAK_Pengadaan_Server.pdf", io.BytesIO(sample_pdf_content), "application/pdf")
    }
    data = {
        "checklist_items": json.dumps(checklist),
        "custom_prompt": "Fokus pada kelayakan spesifikasi teknis dan kepatuhan klausul garansi."
    }

    # Execute Analysis
    analyze_resp = await client.post(
        "/api/v1/documents/analyze-checklist",
        files=files,
        data=data,
        headers=auth_headers,
    )
    assert analyze_resp.status_code == 200, f"Analyze failed: {analyze_resp.text}"
    val_data = analyze_resp.json()["data"]

    assert "id" in val_data
    assert val_data["id"].startswith("VAL-")
    assert "overall_score" in val_data
    assert "compliance_status" in val_data
    assert "checklist_evaluations" in val_data
    assert len(val_data["checklist_evaluations"]) == len(checklist)
    assert "extracted_project" in val_data
    assert len(val_data["extracted_project"]["stages"]) > 0

    val_id = val_data["id"]

    # 2. Publish to Tracker
    publish_payload = {
        "validation_log_id": val_id,
        "title": "Pengadaan Server Rack 42U Data Center",
        "amount": 2500000000.0,
        "procurement_method": "Tender Terbuka",
        "department_name": "Fungsi Teknologi Informasi",
    }
    publish_resp = await client.post(
        "/api/v1/documents/publish-to-tracker",
        json=publish_payload,
        headers=auth_headers,
    )
    assert publish_resp.status_code == 201, f"Publish failed: {publish_resp.text}"
    pub_data = publish_resp.json()["data"]

    assert pub_data["success"] is True
    request_id = pub_data["request_id"]
    assert request_id.startswith("REQ-")
    assert pub_data["title"] == "Pengadaan Server Rack 42U Data Center"
    assert pub_data["auto_cleared_stages_count"] >= 1

    # 3. Verify Procurement Request appears in Tracker (/api/v1/procurement/{id})
    proc_resp = await client.get(f"/api/v1/procurement/{request_id}", headers=auth_headers)
    assert proc_resp.status_code == 200
    proc_detail = proc_resp.json()["data"]
    assert proc_detail["id"] == request_id
    assert proc_detail["title"] == "Pengadaan Server Rack 42U Data Center"
    assert len(proc_detail["milestones"]) > 0
    # First milestone should be auto-cleared (Done)
    assert proc_detail["milestones"][0]["status"] == "Done"

    # 4. Verify Validation Audit Trail / Log Perubahan (/api/v1/procurement/{id}/validation-logs)
    audit_resp = await client.get(f"/api/v1/procurement/{request_id}/validation-logs", headers=auth_headers)
    assert audit_resp.status_code == 200
    logs = audit_resp.json()["data"]
    assert len(logs) >= 1
    assert logs[0]["id"] == val_id
    assert logs[0]["request_id"] == request_id
    assert logs[0]["checklist_count"] == len(checklist)

    # 5. Verify direct validation detail endpoint (/api/v1/documents/validations/{id})
    detail_resp = await client.get(f"/api/v1/documents/validations/{val_id}", headers=auth_headers)
    assert detail_resp.status_code == 200
    log_detail = detail_resp.json()["data"]
    assert log_detail["id"] == val_id
    assert log_detail["request_id"] == request_id

