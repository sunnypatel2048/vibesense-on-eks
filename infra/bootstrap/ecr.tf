# Container registries for the two images built by the Dockerfile.

locals {
  images = toset(["app", "ai"])
}

resource "aws_ecr_repository" "image" {
  for_each = local.images
  name     = "${var.project}-${each.key}"

  # A tag always means the same image, so deploys and rollbacks are exact.
  # CI tags by Git commit SHA, never `latest`.
  image_tag_mutability = "IMMUTABLE"

  # Free basic scan on every push: a second check after Trivy in CI.
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Images are built with --provenance=false --sbom=false (`make images`, CI), so
# each push is one tagged manifest. Untagged images are therefore only leftovers
# (an interrupted push) and safe to expire. With attestations on, a push creates
# an index plus untagged children, and expiring those children would break the
# tagged image.
resource "aws_ecr_lifecycle_policy" "image" {
  for_each   = aws_ecr_repository.image
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged leftovers after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        # The ai image is ~790 MB in ECR; five is plenty of rollback room.
        rulePriority = 2
        description  = "Keep the 5 most recent tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 5
        }
        action = { type = "expire" }
      },
    ]
  })
}
