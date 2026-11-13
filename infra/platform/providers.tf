provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Layer     = "platform" # ephemeral: created by `make up`, destroyed by `make down`
      ManagedBy = "terraform"
    }
  }
}
