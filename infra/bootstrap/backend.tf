# Partial backend configuration: bucket and region come from backend.hcl
# (gitignored, so the AWS account ID stays out of the repo).
#   terraform init -backend-config=backend.hcl
terraform {
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    encrypt      = true
    use_lockfile = true # native S3 locking; no DynamoDB table
  }
}
