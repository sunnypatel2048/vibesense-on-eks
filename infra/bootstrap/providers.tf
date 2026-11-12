provider "aws" {
  region = var.region

  # Tagged at the provider so nothing is missed; scripts/leftovers.sh (Phase 10)
  # finds anything still billing by the Project tag.
  default_tags {
    tags = {
      Project   = var.project
      Layer     = "bootstrap"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
