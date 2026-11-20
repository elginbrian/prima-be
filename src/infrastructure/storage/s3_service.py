import os
import re
import shutil
import logging
from typing import Any, Dict, Optional
import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Unified Storage Service supporting:
    1. AWS S3 storage (using static IAM keys OR EC2 IAM Instance Profile role)
    2. Local Docker volume / local filesystem storage (development & local fallback)
    """

    def __init__(self):
        self.local_dir = os.path.abspath(settings.local_storage_dir)
        os.makedirs(self.local_dir, exist_ok=True)

        self.s3_client = None
        self.bucket_name = settings.s3_bucket_name

        mode = (settings.storage_backend or "auto").strip().lower()
        want_s3 = mode == "s3" or (mode == "auto" and settings.environment.lower() != "development")

        if want_s3 and self.bucket_name:
            try:
                endpoint_url = settings.s3_endpoint_url or f"https://s3.{settings.aws_region}.amazonaws.com"
                client_kwargs: Dict[str, Any] = {
                    "service_name": "s3",
                    "region_name": settings.aws_region,
                    "endpoint_url": endpoint_url,
                    "config": Config(
                        signature_version="s3v4",
                        s3={"addressing_style": "virtual"},
                        connect_timeout=5,
                        read_timeout=15,
                    ),
                }
                if settings.aws_access_key_id and settings.aws_secret_access_key:
                    client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
                    client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

                candidate_client = boto3.client(**client_kwargs)
                # Verify real AWS credentials (env vars or EC2 Instance Profile) and bucket reachability
                candidate_client.head_bucket(Bucket=self.bucket_name)
                self.s3_client = candidate_client
                self.is_local = False
            except Exception as e:
                logger.warning(f"AWS S3 unavailable ({e}), falling back to local storage")
                self.s3_client = None
                self.is_local = True
        else:
            self.is_local = True

        logger.info(
            f"StorageService initialized (Mode: {'LOCAL_VOLUME' if self.is_local else f'AWS_S3:{self.bucket_name}'}, Dir: {self.local_dir})"
        )

    @staticmethod
    def _clean_key(object_name: str) -> str:
        clean = (object_name or "").strip()
        if clean.startswith("/uploads/"):
            clean = clean[len("/uploads/"):]
        # Prevent path traversal
        parts = [p for p in clean.replace("\\", "/").split("/") if p not in ("", ".", "..")]
        return "/".join(parts)

    def _save_local(self, file_obj, object_name: str) -> str:
        """Helper to save a file stream to local volume directory."""
        clean_key = self._clean_key(object_name)
        dest_path = os.path.join(self.local_dir, clean_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        with open(dest_path, "wb") as f_out:
            shutil.copyfileobj(file_obj, f_out)

        logger.info(f"[Local Storage] Saved file to {dest_path}")
        return clean_key

    def upload_file(self, file_obj, object_name: str, content_type: Optional[str] = None) -> str:
        """Upload a file object to AWS S3 bucket or local volume."""
        clean_key = self._clean_key(object_name)
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        if self.is_local or not self.s3_client:
            return self._save_local(file_obj, clean_key)

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            self.s3_client.upload_fileobj(
                file_obj,
                self.bucket_name,
                clean_key,
                ExtraArgs=extra_args
            )
            return clean_key
        except Exception as e:
            logger.warning(f"S3 upload failed for {clean_key} ({e}), falling back to local storage")
            return self._save_local(file_obj, clean_key)

    def file_exists(self, object_name: Optional[str]) -> bool:
        """Check whether an object exists in S3 or local storage."""
        if not object_name:
            return False
        trimmed = object_name.strip()
        if trimmed.startswith("http://") or trimmed.startswith("https://"):
            return True

        clean_key = self._clean_key(trimmed)
        if not clean_key:
            return False

        local_path = os.path.join(self.local_dir, clean_key)
        if os.path.isfile(local_path):
            return True

        if self.s3_client:
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=clean_key)
                return True
            except Exception:
                return False

        return False

    def delete_file(self, object_name: Optional[str]) -> bool:
        """Delete a file from AWS S3 and/or local storage."""
        if not object_name:
            return False
        trimmed = object_name.strip()
        if trimmed.startswith("http://") or trimmed.startswith("https://"):
            return False

        clean_key = self._clean_key(trimmed)
        if not clean_key:
            return False

        deleted = False
        local_path = os.path.join(self.local_dir, clean_key)
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
                deleted = True
            except Exception as e:
                logger.warning(f"Failed deleting local file {local_path}: {e}")

        if self.s3_client:
            try:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=clean_key)
                deleted = True
            except Exception as e:
                logger.warning(f"Failed deleting S3 object {clean_key}: {e}")

        return deleted

    def generate_presigned_url(
        self,
        object_name: str,
        expiration: int = 3600,
        inline_filename: Optional[str] = None,
    ) -> str:
        """Generate a presigned S3 GET URL or local static URL to access the object."""
        if not object_name:
            return ""

        trimmed = object_name.strip()
        if trimmed.startswith("http://") or trimmed.startswith("https://"):
            return trimmed

        clean_key = self._clean_key(trimmed)
        if not clean_key:
            return ""

        # If file exists strictly on local disk (e.g. uploaded while in local fallback), serve from /uploads
        local_path = os.path.join(self.local_dir, clean_key)
        if (self.is_local or not self.s3_client) and os.path.isfile(local_path):
            return f"/uploads/{clean_key}"

        if self.s3_client and not self.is_local:
            try:
                params: Dict[str, Any] = {"Bucket": self.bucket_name, "Key": clean_key}
                if inline_filename:
                    safe_name = re.sub(r'[^a-zA-Z0-9._ -]', '_', inline_filename)
                    params["ResponseContentDisposition"] = f'inline; filename="{safe_name}"'
                return self.s3_client.generate_presigned_url(
                    "get_object",
                    Params=params,
                    ExpiresIn=expiration,
                )
            except (ClientError, BotoCoreError) as e:
                logger.warning(f"Failed to generate S3 presigned URL for {clean_key}: {e}")

        if os.path.isfile(local_path):
            return f"/uploads/{clean_key}"

        return f"/uploads/{clean_key}"

    def generate_presigned_post(
        self,
        object_name: str,
        content_type: str,
        expiration: int = 3600,
        max_bytes: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate presigned S3 POST or local upload endpoint metadata."""
        clean_key = self._clean_key(object_name)

        if self.is_local or not self.s3_client:
            return {
                "url": "/api/v1/documents/upload-local",
                "fields": {
                    "key": clean_key,
                    "Content-Type": content_type
                }
            }

        conditions = [["eq", "$Content-Type", content_type]]
        if max_bytes:
            conditions.append(["content-length-range", 1, max_bytes])

        try:
            response = self.s3_client.generate_presigned_post(
                self.bucket_name,
                clean_key,
                Fields={"Content-Type": content_type},
                Conditions=conditions,
                ExpiresIn=expiration
            )
            return response
        except (ClientError, BotoCoreError) as e:
            logger.warning(f"Failed to generate S3 presigned post for {clean_key}: {e}, using local post")
            return {
                "url": "/api/v1/documents/upload-local",
                "fields": {
                    "key": clean_key,
                    "Content-Type": content_type
                }
            }

    def read_file_bytes(self, object_name: Optional[str]) -> Optional[bytes]:
        """Read stored file bytes from local storage or AWS S3 (used for AI re-evaluation)."""
        if not object_name:
            return None

        trimmed = object_name.strip()
        if trimmed.startswith("http://") or trimmed.startswith("https://"):
            return None

        clean_key = self._clean_key(trimmed)
        if not clean_key:
            return None

        # 1. Try local storage first
        local_path = os.path.join(self.local_dir, clean_key)
        if os.path.isfile(local_path):
            try:
                with open(local_path, "rb") as f_in:
                    return f_in.read()
            except Exception as e:
                logger.warning(f"Failed reading local file {local_path}: {e}")

        # 2. Try AWS S3 if configured
        if self.s3_client:
            try:
                resp = self.s3_client.get_object(Bucket=self.bucket_name, Key=clean_key)
                return resp["Body"].read()
            except Exception as e:
                logger.warning(f"Failed reading S3 object {clean_key}: {e}")

        return None


# Backwards compatibility alias
S3Service = StorageService
s3_service = StorageService()
