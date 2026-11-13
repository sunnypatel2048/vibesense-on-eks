# Same bucket as the bootstrap layer (from backend.hcl, gitignored), own key, so
# destroying the platform can never touch bootstrap resources.
#   terraform init -backend-config=../bootstrap/backend.hcl
terraform {
  backend "s3" {
    key          = "platform/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
