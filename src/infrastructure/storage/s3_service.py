import os
import shutil
import logging
from typing import Any, Dict, Optional
import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Unified Storage Service supporting:
    1. Local Docker volume / local filesystem storage (development & local runs)
    2. AWS S3 storage (production & cloud runs)
    """

    def __init__(self):
        # Determine whether to use local volume storage
        self.is_local = (
            settings.storage_backend == "local"
            or (settings.storage_backend == "auto" and (not settings.aws_access_key_id or settings.environment == "development"))
        )

        self.local_dir = os.path.abspath(settings.local_storage_dir)
        os.makedirs(self.local_dir, exist_ok=True)

        self.s3_client = None
        self.bucket_name = settings.s3_bucket_name

        if not self.is_local and settings.aws_access_key_id and settings.aws_secret_access_key:
            try:
                endpoint_url = settings.s3_endpoint_url or f"https://s3.{settings.aws_region}.amazonaws.com"
                client_kwargs = {
                    "service_name": "s3",
                    "region_name": settings.aws_region,
                    "endpoint_url": endpoint_url,
                    "config": Config(
                        signature_version="s3v4",
                        s3={"addressing_style": "virtual"},
                        connect_timeout=5,
                        read_timeout=10,
                    ),
                    "aws_access_key_id": settings.aws_access_key_id,
                    "aws_secret_access_key": settings.aws_secret_access_key,
                }
                self.s3_client = boto3.client(**client_kwargs)
            except Exception as e:
                logger.warning(f"Failed to initialize S3 client, falling back to local storage: {e}")
                self.is_local = True

        logger.info(f"StorageService initialized (Mode: {'LOCAL_VOLUME' if self.is_local else 'AWS_S3'}, Dir: {self.local_dir})")

    def _save_local(self, file_obj, object_name: str) -> str:
        """Helper to save a file stream to local volume directory."""
        clean_key = object_name.lstrip("/\\")
        dest_path = os.path.join(self.local_dir, clean_key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        with open(dest_path, "wb") as f_out:
            shutil.copyfileobj(file_obj, f_out)

        logger.info(f"[Local Storage] Saved file to {dest_path}")
        return clean_key

    def upload_file(self, file_obj, object_name: str, content_type: Optional[str] = None) -> str:
        """Upload a file object to local volume or S3 bucket."""
        if self.is_local or not self.s3_client:
            return self._save_local(file_obj, object_name)

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            self.s3_client.upload_fileobj(
                file_obj,
                self.bucket_name,
                object_name,
                ExtraArgs=extra_args
            )
            return object_name
        except Exception as e:
            logger.warning(f"S3 upload failed for {object_name} ({e}), falling back to local storage")
            return self._save_local(file_obj, object_name)

    def generate_presigned_url(self, object_name: str, expiration: int = 3600) -> str:
        """Generate a presigned URL or local static URL to access the object."""
        if not object_name:
            return ""

        if object_name.startswith("http://") or object_name.startswith("https://"):
            return object_name

        clean_key = object_name.lstrip("/\\")

        if self.is_local or not self.s3_client:
            return f"/uploads/{clean_key}"

        try:
            response = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": clean_key},
                ExpiresIn=expiration
            )
            return response
        except (ClientError, BotoCoreError) as e:
            logger.warning(f"Failed to generate S3 presigned URL for {object_name}: {e}, using local URL")
            return f"/uploads/{clean_key}"

    def generate_presigned_post(
        self,
        object_name: str,
        content_type: str,
        expiration: int = 3600,
        max_bytes: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate presigned POST or local upload endpoint metadata."""
        clean_key = object_name.lstrip("/\\")

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
            logger.warning(f"Failed to generate S3 presigned post for {object_name}: {e}, using local post")
            return {
                "url": "/api/v1/documents/upload-local",
                "fields": {
                    "key": clean_key,
                    "Content-Type": content_type
                }
            }


# Backwards compatibility alias
S3Service = StorageService
s3_service = StorageService()
