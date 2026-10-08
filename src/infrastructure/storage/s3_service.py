import boto3
from botocore.exceptions import ClientError
from src.infrastructure.config.settings import settings
import logging

logger = logging.getLogger(__name__)

class S3Service:
    def __init__(self):
        client_kwargs = {
            "service_name": "s3",
            "region_name": settings.aws_region
        }
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.s3_endpoint_url:
            client_kwargs["endpoint_url"] = settings.s3_endpoint_url

        self.s3_client = boto3.client(**client_kwargs)
        self.bucket_name = settings.s3_bucket_name

    def upload_file(self, file_obj, object_name: str, content_type: str = None) -> str:
        """Upload a file object to an S3 bucket and return its URL or object key."""
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
            # Depending on if bucket is public, we might return just key or full URL
            return object_name
        except ClientError as e:
            logger.error(f"Failed to upload {object_name} to S3: {e}")
            raise e

    def generate_presigned_url(self, object_name: str, expiration=3600) -> str | None:
        """Generate a presigned URL to share an S3 object."""
        try:
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_name
                },
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            logger.error(f"Failed to generate presigned url for {object_name}: {e}")
            return None

    def generate_presigned_post(self, object_name: str, content_type: str, expiration=3600):
        """Generate a presigned POST URL for direct client uploads to S3."""
        try:
            response = self.s3_client.generate_presigned_post(
                self.bucket_name,
                object_name,
                Fields={
                    "Content-Type": content_type
                },
                Conditions=[
                    ["eq", "$Content-Type", content_type]
                ],
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            logger.error(f"Failed to generate presigned post for {object_name}: {e}")
            return None

s3_service = S3Service()
