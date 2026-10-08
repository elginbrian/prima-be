resource "random_id" "bucket_id" {
  byte_length = 4
}

resource "aws_s3_bucket" "prima_storage" {
  bucket = "prima-storage-${random_id.bucket_id.hex}"

  tags = {
    Name = "Prima Storage Bucket"
  }
}

resource "aws_s3_bucket_cors_configuration" "prima_storage_cors" {
  bucket = aws_s3_bucket.prima_storage.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "POST", "GET", "DELETE"]
    allowed_origins = ["*"] # In production, restrict to frontend domain
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# Add outputs for backend consumption
output "s3_bucket_name" {
  value = aws_s3_bucket.prima_storage.id
}

output "s3_bucket_region" {
  value = aws_s3_bucket.prima_storage.region
}
