# Data-lake bucket replacing MinIO — same prefix layout as
# infra/docker/minio/create-buckets.sh (bronze/bronze_rejects/silver/
# silver_rejects/late_events/gold/checkpoints/dq-reports/forecasting), so the
# Spark jobs' own path-building code (services/data-platform/app/s3.py,
# app/config.py's *_path properties) targets real S3 unchanged — only the
# endpoint URL and credential source differ (IAM role vs. MinIO root user).

locals {
  name_prefix = "${var.project}-${var.environment}"
  bucket_name = "${local.name_prefix}-data-lake-${var.bucket_suffix}"
}

resource "aws_kms_key" "data_lake" {
  description         = "KMS key encrypting the ${local.name_prefix} data-lake bucket at rest."
  enable_key_rotation = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-data-lake-kms"
  })
}

resource "aws_kms_alias" "data_lake" {
  name          = "alias/${local.name_prefix}-data-lake"
  target_key_id = aws_kms_key.data_lake.key_id
}

resource "aws_s3_bucket" "data_lake" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy

  tags = merge(var.tags, {
    Name = local.bucket_name
  })
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data_lake.arn
    }
    bucket_key_enabled = true
  }
}

# Bronze/Silver/Gold layers are append-only and, per docs/data-pipeline.md,
# never overwritten in place except by an explicit, confirmed
# app.backfill --apply swap — noncurrent versions from that swap are the
# only thing this lifecycle rule needs to eventually expire.
resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }
  }

  rule {
    id     = "bronze-tiering"
    status = "Enabled"

    filter {
      prefix = "bronze/"
    }

    transition {
      days          = var.standard_ia_transition_days
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = var.glacier_transition_days
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "silver-tiering"
    status = "Enabled"

    filter {
      prefix = "silver/"
    }

    transition {
      days          = var.standard_ia_transition_days
      storage_class = "STANDARD_IA"
    }
  }

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {
      prefix = ""
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Deny any request that isn't over TLS — the same "encrypted in transit"
# requirement CLAUDE.md asks for, expressed as a bucket policy rather than
# relying on every client to opt in.
data "aws_iam_policy_document" "require_tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.data_lake.arn, "${aws_s3_bucket.data_lake.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "require_tls" {
  bucket = aws_s3_bucket.data_lake.id
  policy = data.aws_iam_policy_document.require_tls.json
}
