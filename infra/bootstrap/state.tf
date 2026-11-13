# Bucket that holds Terraform state for every layer of this project.
#
# Bootstrapped in two steps (see infra/bootstrap/README.md): created with local
# state, then the state is migrated into this bucket with `terraform init -migrate-state`.

locals {
  # Globally unique: includes the account ID and region.
  state_bucket = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}-${var.region}"
}

resource "aws_s3_bucket" "tfstate" {
  # Accepted for a single-user, single-region project; production alternatives in docs/security.md.
  #checkov:skip=CKV_AWS_145:SSE-S3 at no cost instead of a customer-managed KMS key
  #checkov:skip=CKV_AWS_18:Access logs need a second bucket; CloudTrail records configuration changes
  #checkov:skip=CKV_AWS_144:Versioning covers corruption and deletion; the project runs in one region
  #checkov:skip=CKV2_AWS_62:Nothing needs to react to state writes
  bucket = local.state_bucket

  # The platform layer is destroyed often; this bucket never should be.
  lifecycle {
    prevent_destroy = true
  }
}

# Every state write keeps the previous version, so a bad state can be restored.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3: encrypted at rest at no cost. Production would use a customer-managed
# KMS key for an audit trail of decrypts (about $1/month).
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# No object ACLs: access is controlled only by IAM and the bucket policy.
resource "aws_s3_bucket_ownership_controls" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  # Keep 90 days of state history, not forever.
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Lifecycle rules on noncurrent versions need versioning in place first.
  depends_on = [aws_s3_bucket_versioning.tfstate]
}

# State never travels unencrypted.
data "aws_iam_policy_document" "tfstate" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.tfstate.arn,
      "${aws_s3_bucket.tfstate.arn}/*",
    ]

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

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate.json

  # Avoid a race where the policy is applied before Block Public Access.
  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}
