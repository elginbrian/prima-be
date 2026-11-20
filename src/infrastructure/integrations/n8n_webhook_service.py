"""
PRIMA Outbound n8n Webhook Service
- Supports multiple simultaneous webhook destinations with independent event subscriptions
- Signs payloads with HMAC-SHA256 (X-PRIMA-Signature) + optional custom header auth
- Non-blocking async dispatch with bounded retry & in-DB delivery audit trail
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.integrations.n8n_events import (
    ALL_N8N_EVENT_KEYS,
    build_event_envelope,
    validate_webhook_url,
)
from src.infrastructure.models.settings_model import SettingsModel

logger = logging.getLogger(__name__)

_N8N_STORAGE_KEY = "__n8n_plugin_config__"
_MAX_DELIVERY_LOGS = 40
_REQUEST_TIMEOUT_SECONDS = 8.0
_MAX_SEND_ATTEMPTS = 2
_ALLOWED_AUTH_TYPES = {"hmac_and_header", "header", "hmac", "none"}


def _mask_secret(secret: Optional[str]) -> str:
    val = (secret or "").strip()
    if not val:
        return ""
    if len(val) <= 8:
        return "••••"
    return f"{val[:4]}••••{val[-4:]}"


def _is_masked_secret(secret: Optional[str]) -> bool:
    val = (secret or "").strip()
    return "•" in val or "..." in val


def _sign_hmac_sha256(secret: str, timestamp: str, body_bytes: bytes) -> str:
    message = f"{timestamp}.".encode("utf-8") + body_bytes
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _send_http_post_sync(
    url: str,
    body_bytes: bytes,
    headers: Dict[str, str],
    timeout: float = _REQUEST_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Blocking HTTP POST executed inside a worker thread via asyncio.to_thread."""
    req = urllib.request.Request(url=url, data=body_bytes, headers=headers, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_resp = resp.read(1024).decode("utf-8", errors="replace")
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            return {
                "ok": 200 <= resp.status < 300,
                "status_code": int(resp.status),
                "latency_ms": elapsed_ms,
                "response_preview": raw_resp[:400],
                "error": None,
            }
    except urllib.error.HTTPError as http_err:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        err_body = ""
        try:
            err_body = http_err.read(512).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {
            "ok": False,
            "status_code": int(http_err.code),
            "latency_ms": elapsed_ms,
            "response_preview": err_body[:400],
            "error": f"HTTP {http_err.code}: {http_err.reason}",
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": elapsed_ms,
            "response_preview": "",
            "error": str(exc)[:400],
        }


class N8nWebhookService:
    """Modular, concurrency-safe service managing multi-webhook n8n integrations."""

    def __init__(self) -> None:
        self.enabled: bool = True
        self.webhooks: List[Dict[str, Any]] = []
        self.delivery_logs: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def _serialize_config(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "webhooks": self.webhooks,
            "delivery_logs": self.delivery_logs[:_MAX_DELIVERY_LOGS],
        }

    def _apply_raw_config(self, raw: Optional[Dict[str, Any]]) -> None:
        if not isinstance(raw, dict):
            return
        self.enabled = bool(raw.get("enabled", True))
        raw_hooks = raw.get("webhooks")
        if isinstance(raw_hooks, list):
            normalized: List[Dict[str, Any]] = []
            for item in raw_hooks:
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                normalized.append(
                    {
                        "id": str(item.get("id") or f"WH-{uuid4().hex[:8].upper()}"),
                        "name": str(item.get("name") or "n8n Webhook").strip(),
                        "description": str(item.get("description") or "").strip(),
                        "url": str(item.get("url")).strip(),
                        "enabled": bool(item.get("enabled", True)),
                        "events": [
                            str(e).strip()
                            for e in (item.get("events") or ["*"])
                            if str(e).strip()
                        ],
                        "auth_type": (
                            str(item.get("auth_type") or "hmac_and_header")
                            if item.get("auth_type") in _ALLOWED_AUTH_TYPES
                            else "hmac_and_header"
                        ),
                        "secret": str(item.get("secret") or ""),
                        "custom_header_name": str(
                            item.get("custom_header_name") or "X-N8N-Secret"
                        ).strip()
                        or "X-N8N-Secret",
                        "include_presigned_urls": bool(
                            item.get("include_presigned_urls", True)
                        ),
                        "created_at": item.get("created_at")
                        or datetime.now(timezone.utc).isoformat(),
                        "updated_at": item.get("updated_at")
                        or datetime.now(timezone.utc).isoformat(),
                        "last_triggered_at": item.get("last_triggered_at"),
                        "last_status_code": item.get("last_status_code"),
                        "last_error": item.get("last_error"),
                    }
                )
            self.webhooks = normalized
        raw_logs = raw.get("delivery_logs")
        if isinstance(raw_logs, list):
            self.delivery_logs = [
                entry for entry in raw_logs if isinstance(entry, dict)
            ][:_MAX_DELIVERY_LOGS]

    async def load_from_db(self, db: AsyncSession) -> None:
        """Hydrates n8n webhook configuration and recent delivery logs from SettingsModel."""
        res = await db.execute(select(SettingsModel).where(SettingsModel.id == "1"))
        st = res.scalar_one_or_none()
        if st and isinstance(st.department_reviewers, dict):
            raw_json = st.department_reviewers.get(_N8N_STORAGE_KEY)
            if isinstance(raw_json, str) and raw_json.strip():
                try:
                    self._apply_raw_config(json.loads(raw_json))
                except Exception as exc:
                    logger.warning("Failed to parse stored n8n plugin config: %s", exc)
            elif isinstance(raw_json, dict):
                self._apply_raw_config(raw_json)

    async def save_to_db(self, db: AsyncSession) -> None:
        """Persists current n8n config cleanly inside SettingsModel without touching AI config."""
        res = await db.execute(select(SettingsModel).where(SettingsModel.id == "1"))
        st = res.scalar_one_or_none()
        if not st:
            st = SettingsModel(id="1", department_reviewers={})
            db.add(st)
        rev = dict(st.department_reviewers or {})
        rev[_N8N_STORAGE_KEY] = json.dumps(self._serialize_config())
        st.department_reviewers = rev
        await db.commit()

    def get_masked_overview(self) -> Dict[str, Any]:
        """Returns UI-safe masked representation of all webhooks and delivery logs."""
        masked_hooks = []
        for wh in self.webhooks:
            masked_hooks.append(
                {
                    "id": wh["id"],
                    "name": wh["name"],
                    "description": wh.get("description") or "",
                    "url": wh["url"],
                    "enabled": bool(wh.get("enabled", True)),
                    "events": list(wh.get("events") or []),
                    "auth_type": wh.get("auth_type") or "hmac_and_header",
                    "has_secret": bool(wh.get("secret")),
                    "secret_masked": _mask_secret(wh.get("secret")),
                    "custom_header_name": wh.get("custom_header_name") or "X-N8N-Secret",
                    "include_presigned_urls": bool(wh.get("include_presigned_urls", True)),
                    "created_at": wh.get("created_at"),
                    "updated_at": wh.get("updated_at"),
                    "last_triggered_at": wh.get("last_triggered_at"),
                    "last_status_code": wh.get("last_status_code"),
                    "last_error": wh.get("last_error"),
                }
            )
        return {
            "enabled": self.enabled,
            "webhooks": masked_hooks,
            "delivery_logs": list(self.delivery_logs[:_MAX_DELIVERY_LOGS]),
        }

    def _normalize_events(self, events: Optional[List[str]]) -> List[str]:
        if not events:
            return ["*"]
        cleaned = [str(e).strip() for e in events if str(e).strip()]
        if "*" in cleaned:
            return ["*"]
        valid = [e for e in cleaned if e in ALL_N8N_EVENT_KEYS]
        if not valid:
            raise ValueError("Pilih minimal satu event pemicu yang valid.")
        return list(dict.fromkeys(valid))

    async def set_global_enabled(self, db: AsyncSession, enabled: bool) -> Dict[str, Any]:
        async with self._lock:
            self.enabled = bool(enabled)
            await self.save_to_db(db)
            return self.get_masked_overview()

    async def create_webhook(
        self,
        db: AsyncSession,
        *,
        name: str,
        url: str,
        description: str = "",
        enabled: bool = True,
        events: Optional[List[str]] = None,
        auth_type: str = "hmac_and_header",
        secret: Optional[str] = None,
        custom_header_name: str = "X-N8N-Secret",
        include_presigned_urls: bool = True,
    ) -> Dict[str, Any]:
        clean_url = validate_webhook_url(url)
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Nama webhook wajib diisi.")
        if auth_type not in _ALLOWED_AUTH_TYPES:
            raise ValueError("Tipe autentikasi webhook tidak valid.")
        norm_events = self._normalize_events(events)

        resolved_secret = (secret or "").strip()
        if not resolved_secret and auth_type != "none":
            resolved_secret = f"whsec_{secrets.token_hex(16)}"

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": f"WH-{uuid4().hex[:8].upper()}",
            "name": clean_name,
            "description": (description or "").strip(),
            "url": clean_url,
            "enabled": bool(enabled),
            "events": norm_events,
            "auth_type": auth_type,
            "secret": "" if auth_type == "none" else resolved_secret,
            "custom_header_name": (custom_header_name or "X-N8N-Secret").strip(),
            "include_presigned_urls": bool(include_presigned_urls),
            "created_at": now,
            "updated_at": now,
            "last_triggered_at": None,
            "last_status_code": None,
            "last_error": None,
        }
        async with self._lock:
            self.webhooks.append(record)
            await self.save_to_db(db)
            return {
                "overview": self.get_masked_overview(),
                "created_id": record["id"],
                "plain_secret_once": record["secret"] if record["secret"] else None,
            }

    async def update_webhook(
        self,
        db: AsyncSession,
        webhook_id: str,
        *,
        name: Optional[str] = None,
        url: Optional[str] = None,
        description: Optional[str] = None,
        enabled: Optional[bool] = None,
        events: Optional[List[str]] = None,
        auth_type: Optional[str] = None,
        secret: Optional[str] = None,
        clear_secret: bool = False,
        custom_header_name: Optional[str] = None,
        include_presigned_urls: Optional[bool] = None,
    ) -> Dict[str, Any]:
        async with self._lock:
            target = next((w for w in self.webhooks if w["id"] == webhook_id), None)
            if not target:
                raise KeyError(f"Webhook '{webhook_id}' tidak ditemukan.")

            if name is not None:
                clean_name = name.strip()
                if not clean_name:
                    raise ValueError("Nama webhook tidak boleh kosong.")
                target["name"] = clean_name
            if description is not None:
                target["description"] = description.strip()
            if url is not None:
                target["url"] = validate_webhook_url(url)
            if enabled is not None:
                target["enabled"] = bool(enabled)
            if events is not None:
                target["events"] = self._normalize_events(events)
            if auth_type is not None:
                if auth_type not in _ALLOWED_AUTH_TYPES:
                    raise ValueError("Tipe autentikasi webhook tidak valid.")
                target["auth_type"] = auth_type
            if custom_header_name is not None:
                target["custom_header_name"] = custom_header_name.strip() or "X-N8N-Secret"
            if include_presigned_urls is not None:
                target["include_presigned_urls"] = bool(include_presigned_urls)

            if clear_secret or target["auth_type"] == "none":
                target["secret"] = ""
            elif secret is not None and secret.strip() and not _is_masked_secret(secret):
                target["secret"] = secret.strip()
            elif target["auth_type"] != "none" and not target.get("secret"):
                target["secret"] = f"whsec_{secrets.token_hex(16)}"

            target["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self.save_to_db(db)
            return self.get_masked_overview()

    async def delete_webhook(self, db: AsyncSession, webhook_id: str) -> Dict[str, Any]:
        async with self._lock:
            before = len(self.webhooks)
            self.webhooks = [w for w in self.webhooks if w["id"] != webhook_id]
            if len(self.webhooks) == before:
                raise KeyError(f"Webhook '{webhook_id}' tidak ditemukan.")
            await self.save_to_db(db)
            return self.get_masked_overview()

    async def clear_delivery_logs(self, db: AsyncSession) -> Dict[str, Any]:
        async with self._lock:
            self.delivery_logs = []
            await self.save_to_db(db)
            return self.get_masked_overview()

    def _build_request_headers(
        self,
        *,
        event_name: str,
        delivery_id: str,
        timestamp: str,
        body_bytes: bytes,
        auth_type: str,
        secret: str,
        custom_header_name: str,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "PRIMA-n8n-Webhook/1.0",
            "X-PRIMA-Event": event_name,
            "X-PRIMA-Delivery-Id": delivery_id,
            "X-PRIMA-Timestamp": timestamp,
        }
        if secret and auth_type in ("hmac_and_header", "hmac"):
            headers["X-PRIMA-Signature"] = _sign_hmac_sha256(secret, timestamp, body_bytes)
        if secret and auth_type in ("hmac_and_header", "header"):
            header_key = (custom_header_name or "X-N8N-Secret").strip()
            headers[header_key] = secret
        return headers

    async def _send_to_single_webhook(
        self,
        webhook: Dict[str, Any],
        event_name: str,
        envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        delivery_id = envelope["event_id"]
        timestamp = str(int(time.time()))
        body_to_send = envelope
        if not webhook.get("include_presigned_urls", True) and isinstance(envelope.get("data"), dict):
            # Strip temporary presigned file links if webhook disables them
            cleaned_data = {
                k: v
                for k, v in envelope["data"].items()
                if k not in ("file_url_signed", "file_view_url")
            }
            body_to_send = {**envelope, "data": cleaned_data}

        body_bytes = json.dumps(body_to_send, ensure_ascii=False, default=str).encode("utf-8")
        headers = self._build_request_headers(
            event_name=event_name,
            delivery_id=delivery_id,
            timestamp=timestamp,
            body_bytes=body_bytes,
            auth_type=webhook.get("auth_type") or "hmac_and_header",
            secret=webhook.get("secret") or "",
            custom_header_name=webhook.get("custom_header_name") or "X-N8N-Secret",
        )

        last_result: Dict[str, Any] = {
            "ok": False,
            "status_code": None,
            "latency_ms": 0.0,
            "response_preview": "",
            "error": "Tidak ada percobaan",
        }
        for attempt in range(1, _MAX_SEND_ATTEMPTS + 1):
            last_result = await asyncio.to_thread(
                _send_http_post_sync, webhook["url"], body_bytes, headers
            )
            status_code = last_result.get("status_code")
            if last_result["ok"]:
                break
            # Do not retry 4xx client errors (misconfiguration / wrong auth)
            if status_code is not None and 400 <= status_code < 500:
                break
            if attempt < _MAX_SEND_ATTEMPTS:
                await asyncio.sleep(0.8)

        return {
            "delivery_id": delivery_id,
            "webhook_id": webhook["id"],
            "webhook_name": webhook["name"],
            "url": webhook["url"],
            "event": event_name,
            "ok": bool(last_result["ok"]),
            "status_code": last_result.get("status_code"),
            "latency_ms": last_result.get("latency_ms"),
            "response_preview": last_result.get("response_preview") or "",
            "error": last_result.get("error"),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_webhook_by_id(self, db: AsyncSession, webhook_id: str) -> Dict[str, Any]:
        target = next((w for w in self.webhooks if w["id"] == webhook_id), None)
        if not target:
            raise KeyError(f"Webhook '{webhook_id}' tidak ditemukan.")

        envelope = build_event_envelope(
            "prima.webhook_test",
            {
                "message": "Pengujian koneksi webhook PRIMA -> n8n berhasil.",
                "webhook_id": target["id"],
                "webhook_name": target["name"],
                "sample_request_id": "REQ-SAMPLE01",
            },
            actor={"id": "SYSTEM", "name": "PRIMA Webhook Tester"},
        )
        log_entry = await self._send_to_single_webhook(target, "prima.webhook_test", envelope)

        async with self._lock:
            target["last_triggered_at"] = log_entry["sent_at"]
            target["last_status_code"] = log_entry["status_code"]
            target["last_error"] = log_entry["error"]
            self.delivery_logs = [log_entry, *self.delivery_logs][:_MAX_DELIVERY_LOGS]
            await self.save_to_db(db)

        return log_entry

    async def test_ad_hoc_url(
        self,
        *,
        url: str,
        auth_type: str = "hmac_and_header",
        secret: str = "",
        custom_header_name: str = "X-N8N-Secret",
    ) -> Dict[str, Any]:
        clean_url = validate_webhook_url(url)
        pseudo_hook = {
            "id": "WH-PREVIEW",
            "name": "Ad-hoc Webhook Test",
            "url": clean_url,
            "auth_type": auth_type if auth_type in _ALLOWED_AUTH_TYPES else "hmac_and_header",
            "secret": secret,
            "custom_header_name": custom_header_name or "X-N8N-Secret",
            "include_presigned_urls": True,
        }
        envelope = build_event_envelope(
            "prima.webhook_test",
            {
                "message": "Tes koneksi URL webhook sebelum disimpan di PRIMA.",
                "sample_request_id": "REQ-SAMPLE01",
            },
            actor={"id": "SYSTEM", "name": "PRIMA Webhook Tester"},
        )
        return await self._send_to_single_webhook(pseudo_hook, "prima.webhook_test", envelope)

    async def _dispatch_matching_webhooks(
        self,
        event_name: str,
        envelope: Dict[str, Any],
        matching_hooks: List[Dict[str, Any]],
    ) -> None:
        tasks = [
            self._send_to_single_webhook(dict(wh), event_name, envelope)
            for wh in matching_hooks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        entries: List[Dict[str, Any]] = []
        for res in results:
            if isinstance(res, dict):
                entries.append(res)
            elif isinstance(res, Exception):
                logger.warning("n8n webhook dispatch exception for %s: %s", event_name, res)

        if not entries:
            return

        async with self._lock:
            by_id = {w["id"]: w for w in self.webhooks}
            for entry in entries:
                wh = by_id.get(entry["webhook_id"])
                if wh:
                    wh["last_triggered_at"] = entry["sent_at"]
                    wh["last_status_code"] = entry["status_code"]
                    wh["last_error"] = entry["error"]
            self.delivery_logs = [*entries, *self.delivery_logs][:_MAX_DELIVERY_LOGS]
            try:
                async with AsyncSessionLocal() as db:
                    await self.save_to_db(db)
            except Exception as exc:
                logger.warning("Failed to persist n8n webhook delivery stats: %s", exc)

    def emit(
        self,
        event_name: str,
        data: Dict[str, Any],
        *,
        actor: Optional[Dict[str, Optional[str]]] = None,
        links: Optional[Dict[str, Optional[str]]] = None,
        source: str = "prima",
    ) -> None:
        """
        Schedules asynchronous delivery to every enabled webhook subscribed to `event_name`.
        Safe to call after DB commit: never raises or blocks the main user request.
        """
        if source == "n8n" or not self.enabled or not self.webhooks:
            return

        matching = [
            wh
            for wh in self.webhooks
            if wh.get("enabled", True)
            and ("*" in (wh.get("events") or []) or event_name in (wh.get("events") or []))
        ]
        if not matching:
            return

        envelope = build_event_envelope(
            event_name,
            data,
            actor=actor,
            links=links,
        )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._dispatch_matching_webhooks(event_name, envelope, matching))
        except RuntimeError:
            # No running event loop (e.g. unit test without async loop)
            logger.debug("Skipped n8n webhook emit for %s: no active event loop", event_name)


n8n_webhook_service = N8nWebhookService()
