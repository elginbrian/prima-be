import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from src.infrastructure.config import settings
from src.infrastructure.database import get_db, init_db

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
async def test_health(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    resp = await client.get("/api/v1/procurement")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_me(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["email"] == "admin@prima.id"
    assert data["role"] == "Super Admin"


@pytest.mark.asyncio
async def test_issue_1_procurement_create(client: AsyncClient, auth_headers: dict):
    payload = {
        "title": "Pengadaan Mesin Pompa Sentrifugal Test",
        "pic_id": "USR-ADMIN",
        "pic_name": "Administrator",
        "fpp_id": "FPP-TEST-001",
        "fpp_name": "FPP Test User",
        "amount": 250000000,
        "department_id": "DEPT-IT",
        "department_name": "IT Infrastructure",
        "stage": "Perencanaan",
        "current_step": "Draft",
        "is_urgent": True,
    }
    create_resp = await client.post("/api/v1/procurement", json=payload, headers=auth_headers)
    assert create_resp.status_code in (200, 201), f"Failed to create procurement: {create_resp.text}"
    created = create_resp.json()["data"]
    assert created["title"] == payload["title"]
    assert created["amount"] == 250000000
    assert created["is_urgent"] is True

    # Verify it appears in the listing
    list_resp = await client.get("/api/v1/procurement", headers=auth_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]
    match = any(i["id"] == created["id"] for i in items)
    assert match, "Created procurement item did not appear in /procurement list"


@pytest_asyncio.fixture
async def procurement_id(client: AsyncClient, auth_headers: dict) -> str:
    list_resp = await client.get("/api/v1/procurement", headers=auth_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]
    assert len(items) > 0, "No procurement items available"
    return items[0]["id"]


@pytest.mark.asyncio
async def test_issue_2_deadline_add_and_update(client: AsyncClient, auth_headers: dict, procurement_id: str):
    # 1. Create deadline
    deadline_payload = {
        "request_id": procurement_id,
        "task_name": "Verifikasi Dokumen Penawaran Test",
        "milestone": "Evaluasi Teknis",
        "pic_id": "USR-ADMIN",
        "pic_name": "Administrator",
        "department_id": "DEPT-IT",
        "department_name": "IT Infrastructure",
        "target_date": "2026-11-01",
        "status": "On Track",
        "urgency_level": "High",
    }
    create_resp = await client.post("/api/v1/deadlines", json=deadline_payload, headers=auth_headers)
    assert create_resp.status_code in (200, 201), f"Failed to create deadline: {create_resp.text}"
    created = create_resp.json()["data"]
    deadline_id = created["id"]
    assert created["task_name"] == deadline_payload["task_name"]

    # 2. Update deadline status (Issue 2 SLA update)
    patch_resp = await client.patch(
        f"/api/v1/deadlines/{deadline_id}",
        json={"status": "Selesai", "urgency_level": "Critical"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200, f"Failed to update deadline: {patch_resp.text}"
    updated = patch_resp.json()["data"]
    assert updated["status"] == "Selesai"
    assert updated["urgency_level"] == "Critical"


@pytest.mark.asyncio
async def test_issue_3_guarantee_security_and_delete(client: AsyncClient, auth_headers: dict, procurement_id: str):
    # 1. Create a dummy guarantee
    create_resp = await client.post(
        "/api/v1/guarantees",
        json={
            "request_id": procurement_id,
            "type": "Jaminan Pelaksanaan",
            "vendor_id": "VND-TEST",
            "vendor_name": "PT Test Vendor",
            "issuer": "Bank Mandiri",
            "issuer_type": "Bank",
            "beneficiary": "PT Pertamina Patra Niaga",
            "reference_no": "BG-TEST-001",
            "value": 100000000,
            "issue_date": "2026-01-01",
            "expiry_date": "2026-12-31",
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "status": "Aktif",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code in (200, 201), f"Failed to create guarantee: {create_resp.text}"
    guarantee_id = create_resp.json()["data"]["id"]

    # 2. Try requesting upload URL with invalid MIME type (must reject with 422/400)
    invalid_mime_resp = await client.get(
        f"/api/v1/guarantees/{guarantee_id}/upload-url?content_type=application/x-executable",
        headers=auth_headers,
    )
    assert invalid_mime_resp.status_code in (400, 422)
    assert "tidak didukung" in invalid_mime_resp.json().get("message", "").lower()

    # 3. Rollback / delete guarantee (endpoint added for rollback support)
    del_resp = await client.delete(f"/api/v1/guarantees/{guarantee_id}", headers=auth_headers)
    assert del_resp.status_code == 200

    # 4. Confirm it's gone
    get_resp = await client.get(f"/api/v1/guarantees/{guarantee_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_document_status_update(client: AsyncClient, auth_headers: dict, procurement_id: str):
    # Create test document
    create_resp = await client.post(
        "/api/v1/documents",
        json={
            "request_id": procurement_id,
            "name": "Surat Penawaran Harga Test.pdf",
            "type": "Surat Penawaran",
            "document_kind": "administrative",
            "status": "Catatan Procurement",
            "pic_id": "USR-ADMIN",
            "pic_name": "Administrator",
            "issues": ["Tanda tangan basah belum lengkap"],
            "next_action": "Minta vendor mengunggah ulang dokumen bertanda tangan",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code in (200, 201)
    doc_id = create_resp.json()["data"]["id"]

    # PATCH /documents/{id}/status
    patch_resp = await client.patch(
        f"/api/v1/documents/{doc_id}/status",
        json={"status": "Tindak Lanjut FPP"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["data"]["status"] == "Tindak Lanjut FPP"

    # PUT /documents/{id}
    put_resp = await client.put(
        f"/api/v1/documents/{doc_id}",
        json={"status": "Lulus Verifikasi"},
        headers=auth_headers,
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["data"]["status"] == "Lulus Verifikasi"
