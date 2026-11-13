output "state_bucket" {
  description = "Terraform state bucket. Goes in backend.hcl for every layer (not committed)."
  value       = aws_s3_bucket.tfstate.bucket
}

output "region" {
  value = var.region
}

output "ecr_repositories" {
  description = "Repository URLs by image (contain the account ID; not committed anywhere)."
  value       = { for name, repo in aws_ecr_repository.image : name => repo.repository_url }
}
