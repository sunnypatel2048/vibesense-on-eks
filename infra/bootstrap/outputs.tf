output "state_bucket" {
  description = "Terraform state bucket. Goes in backend.hcl for every layer (not committed)."
  value       = aws_s3_bucket.tfstate.bucket
}

output "region" {
  value = var.region
}
